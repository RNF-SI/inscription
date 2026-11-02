"""Aligne l'identifiant historique des comptes d'annuaire sur celui de Keycloak.

Un compte d'annuaire — fédéré depuis le LDAP, ``federationLink`` posé — porte
l'identifiant que lui donne l'annuaire. La plateforme ne peut pas le renommer : le
bandeau de régularisation de « Mon compte » n'aurait donc aucun effet, et c'est
l'inverse qu'il faut faire, écrire dans ``utilisateurs.t_roles`` ce que Keycloak
connaît. Ces comptes sont ceux de l'équipe : leur imposer le changement coûte moins
que de laisser deux identifiants coexister.

⚠️ **Cette commande change le login de ces personnes sur toutes les applications
RNF à la fois.** L'UPDATE de ``t_roles`` déclenche la chaîne de triggers décrite dans
CLAUDE.md : ``sync_table_t_roles`` recopie vers ``utilisateurs_saisie`` et
``utilisateurs_sinp``, ``user_change`` vers ``site_internet_utilisateurs`` (MySQL).
D'où le rapport seul par défaut, et ``--apply`` pour écrire.

    python manage.py aligner_identifiants_annuaire
    python manage.py aligner_identifiants_annuaire --legacy-id 42 --apply
    python manage.py aligner_identifiants_annuaire --apply --csv /tmp/alignes.csv
"""

from __future__ import annotations

import csv

from django.core.management.base import BaseCommand, CommandError

from inscriptions.keycloak_client import KeycloakAdminClient
from inscriptions.services import legacy_writer
from inscriptions.services.legacy_user_migration import load_legacy_users
from inscriptions.services.mirror import LEGACY_ID_ROLE_ATTRIBUTE

CHAMPS = ["nom", "prenom", "ancien_login", "nouveau_login", "email", "legacy_id_role"]


class Command(BaseCommand):
    help = "Écrit dans t_roles l'identifiant Keycloak des comptes fédérés depuis l'annuaire."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Écrit réellement. Sans ce drapeau, la commande ne fait que rapporter.",
        )
        parser.add_argument(
            "--legacy-id",
            type=int,
            default=None,
            help="N'examiner qu'un compte historique (id_role), pour un premier essai.",
        )
        parser.add_argument("--csv", default="", help="Consigne les alignements dans ce fichier.")

    def handle(self, *args, **options):
        if not legacy_writer.is_enabled():
            raise CommandError(
                "Écriture historique indisponible : renseignez LEGACY_DATABASE_URL "
                "et LEGACY_WRITE_ENABLED."
            )
        kc = KeycloakAdminClient()
        if not kc.is_configured():
            raise CommandError("Client Keycloak non configuré.")

        apply_changes = bool(options["apply"])
        try:
            legacy = load_legacy_users(limit=None, offset=0, legacy_id=options["legacy_id"])
            keycloak = kc.list_all_users()
        except Exception as exc:  # noqa: BLE001 - lecture distante, cause reportée telle quelle
            raise CommandError(f"Lecture impossible : {exc}") from exc

        comptes = _index_keycloak(keycloak)
        federes = sum(1 for compte in keycloak if compte.get("federationLink"))
        self.stdout.write(
            f"{len(legacy)} compte(s) historique(s) examiné(s), {len(keycloak)} compte(s) "
            f"Keycloak dont {federes} fédéré(s) depuis un annuaire."
        )
        if not federes:
            self.stdout.write(
                "Aucun compte d'annuaire dans ce realm : rien à aligner. "
                "La fédération LDAP n'y est probablement pas configurée."
            )
            return

        a_aligner: list[tuple[int, dict[str, str]]] = []
        conflits: list[str] = []
        for user in legacy:
            compte = comptes.get(user.id_role) or comptes.get(user.email.strip().lower())
            if not compte or not compte.get("federationLink"):
                continue
            cible = (compte.get("username") or "").strip()
            if not cible or cible.lower() == user.username.strip().lower():
                continue

            # Deux comptes historiques partageant un identifiant casseraient la
            # connexion des applications qui le lisent : on refuse plutôt qu'on écrase.
            occupant = legacy_writer.find_role_id(identifiant=cible)
            if occupant is not None and occupant != user.id_role:
                conflits.append(
                    f"{user.username} → {cible} : déjà porté par id_role={occupant}"
                )
                continue

            a_aligner.append(
                (
                    user.id_role,
                    {
                        "nom": user.last_name,
                        "prenom": user.first_name,
                        "ancien_login": user.username,
                        "nouveau_login": cible,
                        "email": user.email,
                        "legacy_id_role": str(user.id_role),
                    },
                )
            )

        if conflits:
            self.stdout.write(self.style.ERROR(f"\n{len(conflits)} conflit(s), non traité(s) :"))
            for ligne in conflits:
                self.stdout.write(f"  {ligne}")

        if not a_aligner:
            self.stdout.write(self.style.SUCCESS("\nAucun identifiant d'annuaire à aligner."))
            return

        prefixe = "" if apply_changes else "[rapport] "
        self.stdout.write(
            self.style.WARNING(f"\n{prefixe}{len(a_aligner)} identifiant(s) à aligner :")
        )
        ecrits: list[dict[str, str]] = []
        echecs = 0
        for id_role, ligne in a_aligner:
            self.stdout.write(
                "  %-28s %-24s -> %-24s %s"
                % (
                    f"{ligne['prenom']} {ligne['nom']}".strip()[:28],
                    ligne["ancien_login"][:24],
                    ligne["nouveau_login"][:24],
                    ligne["email"],
                )
            )
            if not apply_changes:
                continue
            try:
                # Un UPDATE par compte, chacun validé pour lui-même : un échec sur
                # l'un ne doit pas annuler les alignements déjà faits, d'autant que
                # les triggers ont déjà propagé vers les bases satellites.
                legacy_writer.update_role_profile(id_role, identifiant=ligne["nouveau_login"])
                ecrits.append(ligne)
            except legacy_writer.LegacyWriteError as exc:
                echecs += 1
                self.stderr.write(self.style.ERROR(f"    échec sur id_role={id_role} : {exc}"))

        if not apply_changes:
            self.stdout.write(
                "\nRapport seul. Relancez avec --apply pour écrire ; le login de ces "
                "personnes changera alors sur toutes les applications RNF."
            )
            return

        self.stdout.write(
            self.style.SUCCESS(f"\n{len(ecrits)} identifiant(s) aligné(s), {echecs} échec(s).")
        )
        chemin = (options["csv"] or "").strip()
        if chemin and ecrits:
            with open(chemin, "w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=CHAMPS)
                writer.writeheader()
                writer.writerows(ecrits)
            self.stdout.write(self.style.SUCCESS(f"Liste écrite dans {chemin}"))


def _index_keycloak(comptes: list[dict]) -> dict:
    """Indexe les comptes Keycloak par ``legacy_id_role`` et par e-mail.

    Même ordre de résolution que le miroir : l'attribut d'abord, l'e-mail en repli.
    """
    index: dict = {}
    for compte in comptes:
        email = (compte.get("email") or "").strip().lower()
        if email:
            index.setdefault(email, compte)
        brut = (compte.get("attributes") or {}).get(LEGACY_ID_ROLE_ATTRIBUTE)
        if isinstance(brut, list) and brut:
            brut = brut[0]
        if brut:
            try:
                index[int(str(brut).strip())] = compte
            except ValueError:
                continue
    return index
