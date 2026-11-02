import shutil
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from inscriptions.models import Application
from inscriptions.services.application_images import application_images_dir


class Command(BaseCommand):
    help = "Importe les vignettes applications depuis un dossier source vers media/application-images/."

    def add_arguments(self, parser):
        default_source = Path(settings.BASE_DIR).parent / "frontend" / "src" / "assets" / "images"
        parser.add_argument(
            "--source",
            default=str(default_source),
            help=f"Dossier source (défaut : {default_source})",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Écrase les fichiers déjà présents dans media/",
        )

    def handle(self, *args, **options):
        source = Path(options["source"]).resolve()
        dest = application_images_dir()
        dest.mkdir(parents=True, exist_ok=True)

        if not source.is_dir():
            self.stderr.write(self.style.ERROR(f"Dossier source introuvable : {source}"))
            return

        copied = 0
        skipped = 0
        missing = 0

        for app in Application.objects.exclude(image="").order_by("slug"):
            filename = Path(app.image).name
            src = source / filename
            target = dest / filename
            if not src.is_file():
                missing += 1
                self.stdout.write(f"  manquant : {filename} ({app.slug})")
                continue
            if target.exists() and not options["force"]:
                skipped += 1
                continue
            shutil.copy2(src, target)
            copied += 1
            self.stdout.write(f"  copié : {filename}")

        self.stdout.write(
            self.style.SUCCESS(
                f"Import terminé : {copied} copié(s), {skipped} ignoré(s), {missing} manquant(s). "
                f"Destination : {dest}"
            )
        )
