"""
Importe des utilisateurs legacy (utilisateurs.t_roles) vers Keycloak.

Prérequis :
  - LEGACY_DATABASE_URL configuré
  - KEYCLOAK_SYNC_ENABLED=true

Exemples :
  python manage.py migrate_legacy_users_to_keycloak --dry-run --limit 20
  python manage.py migrate_legacy_users_to_keycloak --clear --limit 20
  python manage.py migrate_legacy_users_to_keycloak --legacy-id 42
"""

from __future__ import annotations

import csv
import os
import time
import uuid

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from inscriptions.keycloak_client import KeycloakAdminClient, KeycloakAdminError
from inscriptions.models import Application
from inscriptions.services.legacy_user_migration import (
    build_legacy_application_slug_map,
    clear_keycloak_users,
    load_legacy_applications,
    load_legacy_users,
    migrate_legacy_user_to_keycloak,
    prepare_migration_groups,
    realm_is_safe_for_migration,
)


class Command(BaseCommand):
    help = "Migre des utilisateurs legacy UsersHub vers Keycloak (phase test)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=20,
            help="Nombre d'utilisateurs à migrer (défaut: 20). Utiliser 0 pour tout migrer.",
        )
        parser.add_argument("--offset", type=int, default=0, help="Décalage dans la liste legacy.")
        parser.add_argument(
            "--legacy-id",
            type=int,
            default=None,
            help="Migrer un seul utilisateur legacy (id_role).",
        )
        parser.add_argument(
            "--clear",
            action="store_true",
            help="Supprime tous les utilisateurs Keycloak du realm avant import.",
        )
        parser.add_argument("--dry-run", action="store_true", help="Simule sans écrire dans Keycloak.")
        parser.add_argument(
            "--force",
            action="store_true",
            help="Autorise l'exécution hors realm de test (déconseillé).",
        )
        parser.add_argument(
            "--shared-password",
            default="",
            help=(
                "Mot de passe commun de secours si le hash legacy est absent "
                "(déconseillé — nécessite --allow-shared-password)."
            ),
        )
        parser.add_argument(
            "--allow-shared-password",
            action="store_true",
            help="Autorise explicitement un mot de passe commun de secours.",
        )
        parser.add_argument(
            "--password-report",
            default="",
            help="Fichier CSV pour les mots de passe générés (comptes sans hash legacy).",
        )

    def handle(self, *args, **options):
        limit = int(options["limit"])
        offset = int(options["offset"])
        legacy_id = options["legacy_id"]
        clear = bool(options["clear"])
        dry_run = bool(options["dry_run"])
        force = bool(options["force"])
        shared_password = (options["shared_password"] or os.environ.get("MIGRATION_TEMP_PASSWORD") or "").strip()
        allow_shared = bool(options["allow_shared_password"])
        password_report = (options["password_report"] or "").strip()

        if shared_password and not allow_shared:
            raise CommandError(
                "Le mot de passe commun est désactivé par défaut (risque de sécurité). "
                "Par défaut, les hash legacy (bcrypt/md5) sont importés. "
                "Pour forcer un mot de passe commun de secours : --allow-shared-password --shared-password '...'"
            )

        realm = (settings.KEYCLOAK_REALM or "").strip()
        if not force and not realm_is_safe_for_migration(realm):
            raise CommandError(
                f"Realm « {realm} » non autorisé pour la migration de test. "
                "Utilisez un realm de test ou --force."
            )
        if not settings.KEYCLOAK_SYNC_ENABLED:
            raise CommandError("KEYCLOAK_SYNC_ENABLED doit être activé.")

        if not Application.objects.exists():
            raise CommandError("Catalogue applications vide. Lancez seed_catalog d'abord.")

        legacy_apps = load_legacy_applications()
        app_map = build_legacy_application_slug_map(legacy_apps)
        self.stdout.write(f"Applications legacy mappées : {len(app_map)}")
        for app_id, slug in sorted(app_map.items()):
            self.stdout.write(f"  - {app_id} → {slug}")

        users = load_legacy_users(
            limit=None if limit == 0 else max(1, limit),
            offset=offset,
            legacy_id=legacy_id,
        )
        if not users:
            raise CommandError("Aucun utilisateur legacy trouvé pour les critères donnés.")

        kc = KeycloakAdminClient()
        if not dry_run:
            self._verify_keycloak_permissions(kc)

        if clear:
            removed = clear_keycloak_users(kc, dry_run=dry_run)
            prefix = "[dry-run] " if dry_run else ""
            self.stdout.write(self.style.WARNING(f"{prefix}{removed} utilisateur(s) Keycloak supprimé(s)."))

        group_stats = prepare_migration_groups(kc, users, dry_run=dry_run)
        self.stdout.write(
            self.style.SUCCESS(
                "Groupes préparés : "
                f"{group_stats['organismes_synced']} organismes synchronisés, "
                f"{group_stats['organisme_groups']} groupes organismes, "
                f"{group_stats['reserve_groups']} groupes réserves."
            )
        )

        created = 0
        skipped = 0
        errors = 0
        legacy_passwords = 0
        generated_passwords = 0
        batch_tag = uuid.uuid4().hex[:8]
        generated_rows: list[dict[str, str]] = []

        for index, user in enumerate(users, start=1):
            if index % 10 == 1 and index > 1 and not dry_run:
                kc.reset_token()

            try:
                if not dry_run and kc.find_user_by_username(user.username):
                    skipped += 1
                    self.stderr.write(self.style.WARNING(f"Utilisateur déjà présent, ignoré : {user.username}"))
                    continue

                user_id, password_mode, generated_plain = migrate_legacy_user_to_keycloak(
                    kc,
                    user,
                    fallback_password=shared_password or None,
                    fallback_temporary=True,
                    dry_run=dry_run,
                )
                created += 1
                if password_mode in ("legacy-bcrypt", "legacy-md5"):
                    legacy_passwords += 1
                elif password_mode == "generated":
                    generated_passwords += 1
                    generated_rows.append(
                        {
                            "username": user.username,
                            "email": user.email,
                            "legacy_id_role": str(user.id_role),
                            "password_mode": password_mode,
                            "temporary_password": generated_plain or "",
                        }
                    )

                self.stdout.write(
                    f"[{index}/{len(users)}] {user.username} ({user.email}) → {user_id} | "
                    f"mdp={password_mode} | org={user.id_organisme or '-'} | "
                    f"réserves={len(user.reserve_codes)} | référents={len(user.referent_valid_codes)} | "
                    f"apps={len(user.app_member_slugs)} | admins={len(user.app_admin_slugs)} | "
                    f"super={user.is_super_admin}"
                )
                if user.referent_pending_codes:
                    self.stdout.write(
                        self.style.WARNING(
                            f"  Référent en attente (non migré) : {', '.join(user.referent_pending_codes)}"
                        )
                    )
                time.sleep(0.05)
            except KeycloakAdminError as exc:
                errors += 1
                self.stderr.write(self.style.ERROR(f"Échec {user.username} (id_role={user.id_role}): {exc}"))

        if generated_rows and password_report and not dry_run:
            with open(password_report, "w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(generated_rows[0].keys()))
                writer.writeheader()
                writer.writerows(generated_rows)
            self.stdout.write(self.style.WARNING(f"Comptes sans hash legacy listés dans {password_report}"))

        prefix = "[dry-run] " if dry_run else ""
        self.stdout.write(
            self.style.SUCCESS(
                f"{prefix}Migration terminée ({batch_tag}) : {created} créé(s), {skipped} ignoré(s), "
                f"{errors} erreur(s), {legacy_passwords} mot(s) de passe legacy importé(s), "
                f"{generated_passwords} mot(s) de passe généré(s)."
            )
        )
        if not dry_run and created:
            self.stdout.write(
                "Les mots de passe legacy (bcrypt pass_plus ou md5 pass) sont conservés. "
                "Aucun e-mail de vérification n'est envoyé (emailVerified=true)."
            )

    def _verify_keycloak_permissions(self, kc: KeycloakAdminClient) -> None:
        probe_username = f"migrate-probe-{uuid.uuid4().hex[:8]}"
        probe_email = f"{probe_username}@legacy-migration.local"
        user_id = kc.create_user(
            username=probe_username,
            email=probe_email,
            first_name="Probe",
            last_name="Migration",
            password="ProbePass123!",
            temporary_password=True,
            require_verify_email=False,
            email_verified=True,
        )
        resp = kc._delete(f"/users/{user_id}")
        if resp.status_code not in (200, 204, 404):
            raise CommandError("Permissions Keycloak insuffisantes (manage-users requis).")
