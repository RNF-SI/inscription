from django.core.management.base import BaseCommand

from inscriptions.models import UserProfile


class Command(BaseCommand):
    help = "Passe un utilisateur en super-admin (par email ou keycloak_sub)."

    def add_arguments(self, parser):
        parser.add_argument("--email", type=str, default="")
        parser.add_argument("--sub", type=str, default="")

    def handle(self, *args, **options):
        email = (options.get("email") or "").strip()
        sub = (options.get("sub") or "").strip()
        if not email and not sub:
            self.stderr.write(self.style.ERROR("Utiliser --email= ou --sub="))
            return
        prof = None
        if email:
            prof = UserProfile.objects.filter(email__iexact=email).first()
        if not prof and sub:
            prof = UserProfile.objects.filter(keycloak_sub=sub).first()
        if not prof:
            self.stderr.write(self.style.ERROR("Profil introuvable."))
            return
        prof.is_super_admin = True
        prof.save(update_fields=["is_super_admin", "updated_at"])
        self.stdout.write(self.style.SUCCESS(f"Super-admin accordé à {prof.email} ({prof.keycloak_sub})."))
