"""État des lieux des identifiants divergents entre Keycloak et la base historique.

L'import a dû renommer les identifiants que Keycloak refuse — espaces, caractères
interdits, moins de trois caractères. L'identifiant historique, lui, reste inchangé
dans ``utilisateurs.t_roles`` : ces comptes portent donc deux noms, et leurs titulaires
sont invités, via un bandeau dans « Mon compte », à en choisir un conforme.

Cette commande dit où en est ce rattrapage. Elle est en lecture seule, et la liste
rétrécit à mesure que les gens régularisent : quand quelqu'un change son identifiant
depuis la plateforme, les deux côtés sont écrits et la divergence disparaît.

    python manage.py audit_identifiants
    python manage.py audit_identifiants --csv /tmp/identifiants-a-regulariser.csv
"""

from __future__ import annotations

import csv

from django.core.management.base import BaseCommand, CommandError
from django.db import connections

from inscriptions.keycloak_client import KeycloakAdminClient
from inscriptions.services.legacy_user_migration import load_legacy_users
from inscriptions.services.mirror import LEGACY_ID_ROLE_ATTRIBUTE

CHAMPS = ["nom", "prenom", "ancien_login", "nouveau_login", "email", "legacy_id_role"]


class Command(BaseCommand):
    help = "Liste les comptes dont l'identifiant Keycloak diffère de l'identifiant historique."

    def add_arguments(self, parser):
        parser.add_argument("--csv", default="", help="Écrit la liste dans ce fichier.")
        parser.add_argument(
            "--limit", type=int, default=0, help="Nombre de comptes examinés (0 = tous)."
        )

    def handle(self, *args, **options):
        # Commande en lecture seule : la connexion historique suffit, inutile
        # d'exiger LEGACY_WRITE_ENABLED.
        if "legacy" not in connections.databases:
            raise CommandError("Base historique indisponible : renseignez LEGACY_DATABASE_URL.")
        kc = KeycloakAdminClient()
        if not kc.is_configured():
            raise CommandError("Client Keycloak non configuré.")

        limit = int(options["limit"]) or None
        try:
            legacy = load_legacy_users(limit=limit, offset=0)
            keycloak = kc.list_all_users()
        except Exception as exc:  # noqa: BLE001
            raise CommandError(f"Lecture impossible : {exc}") from exc

        # Un compte Keycloak se rattache à son compte historique par l'attribut
        # legacy_id_role, et à défaut par l'e-mail — le même ordre que le miroir.
        par_id_role: dict[int, dict] = {}
        par_email: dict[str, dict] = {}
        for compte in keycloak:
            email = (compte.get("email") or "").strip().lower()
            if email:
                par_email.setdefault(email, compte)
            brut = (compte.get("attributes") or {}).get(LEGACY_ID_ROLE_ATTRIBUTE)
            if isinstance(brut, list) and brut:
                brut = brut[0]
            if brut:
                try:
                    par_id_role[int(str(brut).strip())] = compte
                except ValueError:
                    continue

        divergents: list[dict[str, str]] = []
        absents = 0
        federes = 0
        for user in legacy:
            compte = par_id_role.get(user.id_role) or par_email.get(user.email.strip().lower())
            if not compte:
                absents += 1
                continue
            actuel = (compte.get("username") or "").strip()
            # Keycloak replie les identifiants en minuscules : « Amelieptj » devenu
            # « amelieptj » n'est pas une divergence à faire corriger, chaque monde
            # authentifie le sien. Seul un identifiant réécrit compte.
            if not actuel or actuel.lower() == user.username.strip().lower():
                continue
            # L'identifiant d'un compte fédéré appartient à l'annuaire : inutile de
            # demander à son titulaire de le régulariser, il ne peut pas.
            if compte.get("federationLink"):
                federes += 1
            else:
                divergents.append(
                    {
                        "nom": user.last_name,
                        "prenom": user.first_name,
                        "ancien_login": user.username,
                        "nouveau_login": actuel,
                        "email": user.email,
                        "legacy_id_role": str(user.id_role),
                    }
                )

        self.stdout.write(
            f"{len(legacy)} comptes historiques examinés, {len(keycloak)} comptes Keycloak."
        )
        if absents:
            self.stdout.write(
                self.style.WARNING(f"{absents} compte(s) historique(s) sans équivalent Keycloak.")
            )
        if federes:
            self.stdout.write(
                f"{federes} compte(s) fédéré(s) portent un autre identifiant : c'est "
                "l'annuaire qui le fixe, leur titulaire ne peut rien y faire. "
                "« aligner_identifiants_annuaire » écrit celui de Keycloak dans t_roles."
            )

        if not divergents:
            self.stdout.write(self.style.SUCCESS("Aucune divergence d'identifiant."))
            return

        self.stdout.write(
            self.style.WARNING(f"\n{len(divergents)} identifiant(s) à régulariser :")
        )
        for ligne in divergents[:40]:
            self.stdout.write(
                "  %-28s %-24s -> %-24s %s"
                % (
                    f"{ligne['prenom']} {ligne['nom']}".strip()[:28],
                    ligne["ancien_login"][:24],
                    ligne["nouveau_login"][:24],
                    ligne["email"],
                )
            )
        if len(divergents) > 40:
            self.stdout.write(f"  … et {len(divergents) - 40} autres")

        chemin = (options["csv"] or "").strip()
        if chemin:
            with open(chemin, "w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=CHAMPS)
                writer.writeheader()
                writer.writerows(divergents)
            self.stdout.write(self.style.SUCCESS(f"\nListe écrite dans {chemin}"))
        else:
            self.stdout.write("\n  (--csv <fichier> pour obtenir la liste complète)")
