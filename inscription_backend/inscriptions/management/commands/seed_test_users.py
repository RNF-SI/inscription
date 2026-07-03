from __future__ import annotations

import random
import time
import uuid

import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from inscriptions.keycloak_client import KeycloakAdminClient, KeycloakAdminError
from inscriptions.models import Application
from inscriptions.services import application_access as app_access_svc
from inscriptions.services import provisioning as prov

SEED_EMAIL_DOMAIN = "test.inscription.local"
SEED_USERNAME_PREFIX = "seed-user-"
SEED_PASSWORD = "SeedTest123!"
_FORBIDDEN_REALMS = {"rnf", "si-rnf", "master", "production", "prod"}

FIRST_NAMES = [
    "Alice",
    "Bernard",
    "Camille",
    "David",
    "Émilie",
    "François",
    "Gabrielle",
    "Hugo",
    "Isabelle",
    "Julien",
    "Karine",
    "Lucas",
    "Marine",
    "Nicolas",
    "Olivia",
    "Paul",
    "Quentin",
    "Rose",
    "Sophie",
    "Thomas",
    "Valérie",
    "William",
    "Yann",
    "Zoé",
]

LAST_NAMES = [
    "Martin",
    "Bernard",
    "Dubois",
    "Thomas",
    "Robert",
    "Richard",
    "Petit",
    "Durand",
    "Leroy",
    "Moreau",
    "Simon",
    "Laurent",
    "Lefebvre",
    "Michel",
    "Garcia",
    "David",
    "Bertrand",
    "Roux",
    "Vincent",
    "Fournier",
    "Morel",
    "Girard",
    "André",
    "Mercier",
]


def _realm_is_safe(realm: str) -> bool:
    normalized = (realm or "").strip().lower()
    if not normalized:
        return False
    if normalized in _FORBIDDEN_REALMS:
        return False
    return "test" in normalized or normalized.endswith("-dev") or normalized.endswith("-local")


def _iter_keycloak_users_search(kc: KeycloakAdminClient, query: str, page_size: int = 100):
    first = 0
    while True:
        r = kc._get(f"/users?search={requests.utils.quote(query)}&first={first}&max={page_size}")
        if r.status_code != 200:
            raise KeycloakAdminError(f"list_users_search:{r.status_code}")
        batch = r.json() or []
        if not isinstance(batch, list) or not batch:
            break
        for user in batch:
            yield user
        if len(batch) < page_size:
            break
        first += page_size


def _is_seed_user(user: dict) -> bool:
    username = (user.get("username") or "").strip().lower()
    email = (user.get("email") or "").strip().lower()
    return username.startswith(SEED_USERNAME_PREFIX) or email.endswith(f"@{SEED_EMAIL_DOMAIN}")


class Command(BaseCommand):
    help = (
        "Crée des utilisateurs de test dans Keycloak, leurs profils locaux, "
        "et leur attribue aléatoirement des accès applicatifs."
    )

    def add_arguments(self, parser):
        parser.add_argument("--count", type=int, default=300, help="Nombre d'utilisateurs à créer (défaut: 300).")
        parser.add_argument(
            "--purge",
            action="store_true",
            help="Supprime d'abord les utilisateurs seed existants (préfixe seed-user-).",
        )
        parser.add_argument("--dry-run", action="store_true", help="Simule sans écrire dans Keycloak ni la base.")
        parser.add_argument(
            "--force",
            action="store_true",
            help="Autorise l'exécution hors realm de test (déconseillé).",
        )
        parser.add_argument(
            "--seed",
            type=int,
            default=42,
            help="Graine aléatoire pour la répartition des accès (défaut: 42).",
        )
        parser.add_argument(
            "--min-apps",
            type=int,
            default=1,
            help="Nombre minimum d'applications par utilisateur (défaut: 1).",
        )
        parser.add_argument(
            "--max-apps",
            type=int,
            default=4,
            help="Nombre maximum d'applications par utilisateur (défaut: 4).",
        )

    def handle(self, *args, **options):
        count = max(1, int(options["count"]))
        purge = bool(options["purge"])
        dry_run = bool(options["dry_run"])
        force = bool(options["force"])
        rng_seed = int(options["seed"])
        min_apps = max(0, int(options["min_apps"]))
        max_apps = max(min_apps, int(options["max_apps"]))

        realm = (settings.KEYCLOAK_REALM or "").strip()
        if not force and not _realm_is_safe(realm):
            raise CommandError(
                f"Realm « {realm} » non autorisé pour le seed de test. "
                "Utilisez un realm de test (ex. inscription-test) ou --force."
            )
        if not settings.KEYCLOAK_SYNC_ENABLED:
            raise CommandError("KEYCLOAK_SYNC_ENABLED doit être activé pour créer des utilisateurs Keycloak.")

        apps = list(app_access_svc.si_managed_applications().filter(requires_access_request=True))
        if not apps:
            raise CommandError("Aucune application SI avec demande d'accès trouvée. Lancez seed_catalog d'abord.")

        if max_apps > len(apps):
            max_apps = len(apps)
        if min_apps > max_apps:
            min_apps = max_apps

        rng = random.Random(rng_seed)
        kc = KeycloakAdminClient()
        self._verify_keycloak_permissions(kc, dry_run=dry_run)

        if purge:
            removed = self._purge_seed_users(kc, dry_run=dry_run)
            self.stdout.write(self.style.WARNING(f"{removed} utilisateur(s) seed supprimé(s)."))

        created = 0
        access_grants = 0
        errors = 0
        consecutive_errors = 0
        batch_tag = uuid.uuid4().hex[:8]

        for index in range(1, count + 1):
            if index % 15 == 1 and index > 1:
                kc.reset_token()

            first_name = rng.choice(FIRST_NAMES)
            last_name = rng.choice(LAST_NAMES)
            username = f"{SEED_USERNAME_PREFIX}{batch_tag}-{index:04d}"
            email = f"{username}@{SEED_EMAIL_DOMAIN}"

            try:
                if dry_run:
                    user_id = f"dry-run-{index}"
                    app_count = rng.randint(min_apps, max_apps) if max_apps else 0
                    access_grants += app_count
                else:
                    user_id = self._create_seed_user(kc, username, email, first_name, last_name)

                    app_count = rng.randint(min_apps, max_apps) if max_apps else 0
                    chosen_apps = rng.sample(apps, app_count) if app_count else []
                    for app in chosen_apps:
                        self._provision_with_retry(kc, user_id, app)
                        access_grants += 1

                created += 1
                consecutive_errors = 0
                if index % 25 == 0 or index == count:
                    self.stdout.write(f"Progression : {index}/{count}")
                time.sleep(0.05)
            except KeycloakAdminError as exc:
                errors += 1
                consecutive_errors += 1
                self.stderr.write(self.style.ERROR(f"Échec {username}: {exc}"))
                if consecutive_errors >= 10:
                    raise CommandError(
                        "Trop d'erreurs Keycloak consécutives. "
                        "Vérifiez les rôles realm-management du client inscription-admin "
                        "(manage-users, manage-groups, view-users, view-groups)."
                    ) from exc

        prefix = "[dry-run] " if dry_run else ""
        self.stdout.write(
            self.style.SUCCESS(
                f"{prefix}{created} utilisateur(s) seed créé(s), {access_grants} accès applicatifs accordés, {errors} erreur(s)."
            )
        )
        if not dry_run:
            self.stdout.write(f"Mot de passe commun : {SEED_PASSWORD}")
            self.stdout.write(f"Préfixe utilisateur : {SEED_USERNAME_PREFIX}{batch_tag}-")

    def _verify_keycloak_permissions(self, kc: KeycloakAdminClient, *, dry_run: bool) -> None:
        if dry_run:
            return
        probe_username = f"{SEED_USERNAME_PREFIX}probe-{uuid.uuid4().hex[:8]}"
        probe_email = f"{probe_username}@{SEED_EMAIL_DOMAIN}"
        user_id = kc.create_user(
            username=probe_username,
            email=probe_email,
            first_name="Probe",
            last_name="Seed",
            password=SEED_PASSWORD,
            temporary_password=False,
            require_verify_email=False,
        )
        r = kc._delete(f"/users/{user_id}")
        if r.status_code not in (200, 204, 404):
            raise CommandError(
                "Le client Keycloak admin ne peut pas gérer les utilisateurs (manage-users requis)."
            )

    def _create_seed_user(
        self,
        kc: KeycloakAdminClient,
        username: str,
        email: str,
        first_name: str,
        last_name: str,
    ) -> str:
        for attempt in range(2):
            try:
                return kc.create_user(
                    username=username,
                    email=email,
                    first_name=first_name,
                    last_name=last_name,
                    password=SEED_PASSWORD,
                    temporary_password=False,
                    require_verify_email=False,
                )
            except KeycloakAdminError as exc:
                if attempt == 0:
                    kc.reset_token()
                    continue
                raise exc
        raise KeycloakAdminError("create_user_failed")

    def _provision_with_retry(self, kc: KeycloakAdminClient, user_id: str, app) -> None:
        for attempt in range(2):
            try:
                prov.provision_application_access(kc, user_id, app)
                return
            except KeycloakAdminError:
                if attempt == 0:
                    kc.reset_token()
                    continue
                raise

    def _purge_seed_users(self, kc: KeycloakAdminClient, *, dry_run: bool) -> int:
        removed = 0
        seen_ids: set[str] = set()
        for user in _iter_keycloak_users_search(kc, SEED_USERNAME_PREFIX):
            user_id = (user.get("id") or "").strip()
            if not user_id or user_id in seen_ids or not _is_seed_user(user):
                continue
            seen_ids.add(user_id)
            if dry_run:
                removed += 1
                continue
            r = kc._delete(f"/users/{user_id}")
            if r.status_code not in (200, 204, 404):
                raise KeycloakAdminError(f"delete_user:{r.status_code}")
            removed += 1
        return removed
