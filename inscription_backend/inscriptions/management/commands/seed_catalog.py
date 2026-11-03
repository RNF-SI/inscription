from django.core.management.base import BaseCommand

from inscriptions.legacy_groups import GROUPES_HISTORIQUES, SANS_GROUPE_HISTORIQUE
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
        self._poser_groupes_historiques()
        self._signaler_les_manquantes()

    def _poser_groupes_historiques(self) -> None:
        """Pose la correspondance vers les groupes de la base historique.

        La migration 0011 la posait déjà, mais elle ne pouvait rien faire sur une base
        neuve : à l'heure de ``migrate``, le catalogue n'existe pas encore, et c'est
        cette commande qui le crée juste après. Ses sept ``UPDATE`` ne trouvaient donc
        aucune ligne, en silence, et aucune application n'écrivait plus rien côté
        historique — un accès validé n'ajoutait l'usager qu'à Keycloak. Constaté en
        production le 2026-11-03, après la bascule, sur une demande d'accès à PSDRF.

        Appliquer la correspondance ici la rend indépendante de l'ordre des commandes :
        rejouer ``seed_catalog`` suffit, sur une base neuve comme sur une base en place.
        """
        pose = 0
        for slug, id_role in GROUPES_HISTORIQUES.items():
            # Uniquement si rien n'est posé : une valeur saisie à la main fait foi.
            pose += Application.objects.filter(
                slug=slug, legacy_group_id_role__isnull=True
            ).update(legacy_group_id_role=id_role)
        if pose:
            self.stdout.write(self.style.SUCCESS(f"{pose} correspondance(s) de groupe posée(s)."))

    def _signaler_les_manquantes(self) -> None:
        """Nomme les applications à demande d'accès dépourvues de groupe historique.

        Sans ce rappel, l'absence de correspondance ne se voit nulle part : l'accès
        est accordé dans Keycloak, l'interface affiche un succès, et seul un
        ``logger.info`` côté Django mentionne que rien n'a été écrit.

        Les applications dont l'absence de groupe est normale sont écartées : les
        nommer à chaque déploiement apprendrait à ignorer l'avertissement, et il
        n'aurait plus servi à rien le jour où il désigne un vrai trou.
        """
        orphelines = (
            Application.objects.filter(
                requires_access_request=True,
                managed_by_si=True,
                legacy_group_id_role__isnull=True,
            )
            .exclude(slug__in=SANS_GROUPE_HISTORIQUE)
            .order_by("slug")
            .values_list("slug", flat=True)
        )
        if orphelines:
            self.stdout.write(
                self.style.WARNING(
                    "Sans groupe historique, leurs accès ne seront écrits que dans "
                    "Keycloak : " + ", ".join(orphelines)
                )
            )
