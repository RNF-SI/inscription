from django.core.management.base import BaseCommand

from inscriptions.models import Application


# Données initiales alignées sur l’ancien frontend (home.component) + slugs d’inscription.
APPLICATIONS = [
    {
        "slug": "geonature-saisie",
        "nom": "GeoNature Saisie",
        "url": "https://geonature-saisie.reserves-naturelles.org",
        "image": "geonature-saisie.png",
        "description": "Application GeoNature Saisie.",
        "managed_by_si": True,
    },
    {
        "slug": "geonature-psdrf",
        "nom": "GeoNature PSDRF",
        "url": "https://geonature.reserves-naturelles.org",
        "image": "geonature-global.png",
        "description": "Module PSDRF de GeoNature.",
        "managed_by_si": True,
    },
    {
        "slug": "ancrage",
        "nom": "BAO Diagnostic d'Ancrage Territorial",
        "url": "https://ancrage.reserves-naturelles.org/",
        "image": "ancrage.png",
        "description": "Boîte à outils Ancrage.",
        "managed_by_si": True,
    },
    {
        "slug": "socle",
        "nom": "SOCLE",
        "url": "https://socle.reserves-naturelles.org/",
        "image": "socle.png",
        "description": "SOCLE — patrimoine géologique.",
        "managed_by_si": True,
        "requires_access_request": False,
    },
    {
        "slug": "naturadapt",
        "nom": "Natur'Adapt",
        "url": "https://naturadapt.com/",
        "image": "naturadapt.png",
        "description": "Communauté adaptation au changement climatique.",
        "managed_by_si": False,
    },
    {
        "slug": "opnl",
        "nom": "Plateforme OPNL",
        "url": "https://opnl.fr",
        "image": "opnl.png",
        "description": "Observatoire du patrimoine naturel littoral.",
        "managed_by_si": True,
    },
    {
        "slug": "portail-membres",
        "nom": "Portail des membres",
        "url": "https://www.portail.reserves-naturelles.org/",
        "image": "assoconnect.png",
        "description": "Portail des membres RNF.",
        "managed_by_si": False,
    },
    {
        "slug": "site-internet",
        "nom": "Site Internet",
        "url": "https://www.reserves-naturelles.org/",
        "image": "site.png",
        "description": "Site internet RNF.",
        "managed_by_si": True,
    },
    {
        "slug": "pearltrees",
        "nom": "Pearltrees",
        "url": "https://www.pearltrees.com/ressources_rnf",
        "image": "pearltrees.png",
        "description": "Pearltrees RNF.",
        "managed_by_si": False,
    },
    {
        "slug": "boutique",
        "nom": "Boutique uniformes",
        "url": "https://rnf-boutique.fr/",
        "image": "boutique.png",
        "description": "Boutique uniformes.",
        "managed_by_si": False,
    },
    {
        "slug": "tourbieres",
        "nom": "Tourbières du réseau",
        "url": "https://tourbieres.reserves-naturelles.org/",
        "image": "tourbieres.png",
        "description": "Données tourbières du réseau.",
        "managed_by_si": True,
        "requires_access_request": False,
    },
    {
        "slug": "waterwise",
        "nom": "Waterwise DB management",
        "url": "https://waterwise.reserves-naturelles.org/",
        "image": "tourbieres.png",
        "description": "Import données temporelles Waterwise.",
        "managed_by_si": True,
    },
    {
        "slug": "syrphes",
        "nom": "Syrphes",
        "url": "",
        "image": "",
        "description": "Accès Syrphes.",
        "managed_by_si": True,
    },
]


class Command(BaseCommand):
    help = "Charge le catalogue applications (idempotent)."

    def handle(self, *args, **options):
        for row in APPLICATIONS:
            Application.objects.update_or_create(slug=row["slug"], defaults=row)
        self.stdout.write(self.style.SUCCESS(f"{len(APPLICATIONS)} applications synchronisées."))
