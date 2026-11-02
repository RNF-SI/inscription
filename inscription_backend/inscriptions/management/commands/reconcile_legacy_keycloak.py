"""Compare la base historique et Keycloak, et signale les écarts.

Tant que des comptes peuvent être créés ou modifiés ailleurs que dans cette
plateforme — l'interface UsersHub écrit dans le même schéma ``utilisateurs`` —, les
deux référentiels peuvent diverger sans que personne ne s'en aperçoive : Keycloak
n'est consommé que par cette application, un compte qui y manque ne se voit pas.

La commande ne fait par défaut que **rapporter**. Avec ``--apply`` elle se limite à
reposer l'attribut ``legacy_id_role`` sur les comptes Keycloak qu'elle a su apparier :
c'est la seule correction sans risque. Créer dans Keycloak les comptes qui n'y sont pas
reste le travail de ``migrate_legacy_users_to_keycloak``, qui sait importer les hashs
de mots de passe.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from inscriptions.keycloak_client import KeycloakAdminClient, KeycloakAdminError
from inscriptions.services import legacy_writer
from inscriptions.services.legacy_user_migration import load_legacy_users
from inscriptions.services.mirror import LEGACY_ID_ROLE_ATTRIBUTE


class Command(BaseCommand):
    help = "Compare utilisateurs.t_roles et Keycloak, et signale les écarts."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Repose l'attribut legacy_id_role sur les comptes Keycloak appariés.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Nombre de comptes historiques à examiner (tous par défaut).",
        )

    def handle(self, *args, **options):
        if not legacy_writer.is_enabled():
            raise CommandError(
                "Base historique indisponible : renseignez LEGACY_DATABASE_URL "
                "et LEGACY_WRITE_ENABLED."
            )

        kc = KeycloakAdminClient()
        if not kc.is_configured():
            raise CommandError("Client Keycloak non configuré.")

        apply_changes = options["apply"]

        try:
            legacy_users = load_legacy_users(limit=options["limit"], offset=0)
            keycloak_users = kc.list_all_users()
        except Exception as exc:  # noqa: BLE001 - lecture distante, cause reportée telle quelle
            raise CommandError(f"Lecture impossible : {exc}") from exc

        by_email: dict[str, dict] = {}
        by_username: dict[str, dict] = {}
        known_id_roles: set[int] = set()
        for user in keycloak_users:
            email = (user.get("email") or "").strip().lower()
            username = (user.get("username") or "").strip().lower()
            if email:
                by_email.setdefault(email, user)
            if username:
                by_username.setdefault(username, user)
            raw = (user.get("attributes") or {}).get(LEGACY_ID_ROLE_ATTRIBUTE)
            if isinstance(raw, list) and raw:
                raw = raw[0]
            if raw:
                try:
                    known_id_roles.add(int(str(raw).strip()))
                except ValueError:
                    self.stdout.write(
                        self.style.WARNING(
                            f"Attribut illisible sur {user.get('username')!r} : {raw!r}"
                        )
                    )

        absents = []
        attribut_manquant = []
        email_divergent = []

        for legacy in legacy_users:
            if legacy.id_role in known_id_roles:
                continue
            email = (legacy.email or "").strip().lower()
            username = (legacy.username or "").strip().lower()
            match = by_email.get(email) or by_username.get(username)
            if not match:
                absents.append(legacy)
                continue
            attribut_manquant.append((legacy, match))
            match_email = (match.get("email") or "").strip().lower()
            if email and match_email and email != match_email:
                email_divergent.append((legacy, match))

        self.stdout.write(
            f"{len(legacy_users)} comptes historiques, {len(keycloak_users)} comptes Keycloak."
        )

        if absents:
            self.stdout.write(
                self.style.WARNING(f"\n{len(absents)} compte(s) absent(s) de Keycloak :")
            )
            for legacy in absents[:50]:
                self.stdout.write(f"  id_role={legacy.id_role} {legacy.username} <{legacy.email}>")
            if len(absents) > 50:
                self.stdout.write(f"  … et {len(absents) - 50} autres")
            self.stdout.write(
                "  → les créer avec : manage.py migrate_legacy_users_to_keycloak"
            )

        if email_divergent:
            self.stdout.write(
                self.style.WARNING(f"\n{len(email_divergent)} e-mail(s) divergent(s) :")
            )
            for legacy, match in email_divergent[:50]:
                self.stdout.write(
                    f"  id_role={legacy.id_role} historique={legacy.email} keycloak={match.get('email')}"
                )

        if attribut_manquant:
            self.stdout.write(
                self.style.WARNING(
                    f"\n{len(attribut_manquant)} compte(s) apparié(s) sans attribut "
                    f"{LEGACY_ID_ROLE_ATTRIBUTE}."
                )
            )
            if not apply_changes:
                self.stdout.write("  → relancer avec --apply pour le reposer.")
            else:
                reposes = 0
                for legacy, match in attribut_manquant:
                    try:
                        kc.set_user_attribute(
                            match["id"], LEGACY_ID_ROLE_ATTRIBUTE, str(legacy.id_role)
                        )
                        reposes += 1
                    except KeycloakAdminError as exc:
                        self.stdout.write(
                            self.style.ERROR(f"  échec sur {match.get('username')} : {exc}")
                        )
                self.stdout.write(self.style.SUCCESS(f"  {reposes} attribut(s) reposé(s)."))

        if not absents and not attribut_manquant and not email_divergent:
            self.stdout.write(self.style.SUCCESS("\nAucun écart."))
