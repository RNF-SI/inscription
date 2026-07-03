from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from inscriptions.keycloak_client import KeycloakAdminClient, KeycloakAdminError
from inscriptions.user_identity import resolve_user_sub


class Command(BaseCommand):
    help = "Ajoute un utilisateur Keycloak au groupe super-admin (/super-admin)."

    def add_arguments(self, parser):
        parser.add_argument("--email", type=str, help="E-mail de l'utilisateur")
        parser.add_argument("--sub", type=str, help="Keycloak sub (id utilisateur)")

    def handle(self, *args, **options):
        if not settings.KEYCLOAK_SYNC_ENABLED:
            raise CommandError("KEYCLOAK_SYNC_ENABLED doit être activé pour cette commande.")
        email = (options.get("email") or "").strip()
        sub = (options.get("sub") or "").strip()
        if not email and not sub:
            raise CommandError("Indiquez --email ou --sub")
        resolved = resolve_user_sub(keycloak_sub=sub, email=email)
        if not resolved:
            raise CommandError("Utilisateur introuvable dans Keycloak")
        try:
            kc = KeycloakAdminClient()
            group_id = kc.ensure_super_admin_group()
            kc.user_join_group(resolved, group_id)
        except KeycloakAdminError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(f"Super-admin Keycloak : {resolved}"))
