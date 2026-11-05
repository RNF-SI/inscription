"""Synchronise le référentiel des réserves et des organismes depuis l'API de RADIS.

Remplace ``migrate_legacy`` comme mise à jour courante du référentiel : celui-ci lisait
la base historique, que RADIS alimente par un push partiel et qui ne réconcilie jamais.
``migrate_legacy`` reste utile une fois, pour l'amorçage.

    python manage.py synchro_radis --a-blanc    # montre ce qui changerait
    python manage.py synchro_radis

Idempotente : un second passage ne modifie rien. Conçue pour un minuteur nocturne.
"""

from django.core.management.base import BaseCommand, CommandError

from inscriptions.services import radis


class Command(BaseCommand):
    help = "Synchronise réserves, organismes et liens depuis l'API v1 de RADIS."

    def add_arguments(self, parser):
        parser.add_argument(
            "--a-blanc",
            action="store_true",
            dest="a_blanc",
            help="Montre ce qui changerait sans rien écrire.",
        )
        parser.add_argument(
            "--declencheur",
            default="commande",
            choices=["commande", "minuteur"],
            help="Consigné dans la trace du passage ; le minuteur systemd passe « minuteur ».",
        )
        parser.add_argument(
            "--tous-organismes",
            action="store_true",
            dest="tous_organismes",
            help="Crée aussi les organismes de RADIS qui ne gèrent aucune réserve "
                 "(agences de l'eau, ministères, fondations…).",
        )
        parser.add_argument(
            "--sans-creation",
            action="store_true",
            dest="sans_creation",
            help="N'écrit aucun organisme dans utilisateurs.bib_organismes ; les manquants "
                 "sont seulement listés.",
        )

    def handle(self, *args, **options):
        a_blanc = options["a_blanc"]
        try:
            _passage, rapport = radis.executer(
                a_blanc=a_blanc,
                declencheur=options["declencheur"],
                creer_organismes=not options["sans_creation"],
                creer_tous_organismes=options["tous_organismes"],
            )
        except radis.ErreurRadis as exc:
            raise CommandError(str(exc))

        ecrire = self.stdout.write
        if a_blanc:
            ecrire(self.style.WARNING("--- à blanc : rien n'a été écrit ---"))

        ecrire(f"{rapport['reserves_radis']} réserves dans RADIS")
        ecrire(f"  créées       : {len(rapport['reserves_creees'])}")
        ecrire(f"  modifiées    : {len(rapport['reserves_modifiees'])}")
        ecrire(f"  inchangées   : {rapport['reserves_inchangees']}")
        ecrire(f"  déclassées   : {len(rapport['reserves_declassees'])}")
        for code in rapport["reserves_creees"]:
            ecrire(f"  + {code}")
        for code, raison in rapport["reserves_ignorees"]:
            ecrire(f"  ! {code} ignorée — {raison}")

        ecrire(f"\n{rapport['organismes_radis']} organismes dans RADIS")
        ecrire(f"  rapprochés   : {len(rapport['organismes_rattaches'])}")
        ecrire(f"  renommés     : {len(rapport['organismes_renommes'])}")
        libelle_creation = "à créer" if a_blanc else "créés"
        libelle_adoption = "à adopter" if a_blanc else "adoptés"
        ecrire(f"  {libelle_creation:12} : {len(rapport['organismes_crees'])}")
        ecrire(f"  {libelle_adoption:12} : {len(rapport['organismes_adoptes'])}")
        for pk, ancien, nouveau in rapport["organismes_renommes"]:
            ecrire(f"  ~ {pk} « {ancien} » → « {nouveau} »")
        for pk, nom in rapport["organismes_crees"]:
            ecrire(f"  + {pk if pk is not None else '?'} — {nom}")
        for pk, nom in rapport["organismes_adoptes"]:
            ecrire(f"  = {pk} — {nom} (ligne bib_organismes existante)")

        ecrire(
            f"\nliens réserve ↔ organisme : "
            f"{rapport['liens_crees']} créés, "
            f"{rapport['liens_modifies']} modifiés, "
            f"{rapport['liens_supprimes']} supprimés"
        )

        # Ce qui demande un arbitrage humain : rien n'a été touché, et chacune de ces
        # listes désigne un écart entre les deux référentiels, pas une erreur.
        partages = rapport["organismes_uuid_partage"]
        if partages:
            ecrire(
                self.style.WARNING(
                    f"\n{len(partages)} organisme(s) de RADIS dont l'UUID du SINP est partagé "
                    "avec un autre : non rapprochés, à corriger dans RADIS."
                )
            )
            for radis_id, nom, uuid_org in partages:
                ecrire(f"  ! {radis_id} — {nom} ({uuid_org})")

        # Les organismes sans correspondance ne sont listés que lorsqu'ils restent à
        # faire : à blanc (la création n'écrit rien) ou quand elle est coupée. Une fois
        # créés, ils figurent déjà plus haut.
        # Quand la création est active, ces organismes figurent déjà plus haut, créés
        # ou adoptés. La liste n'a d'intérêt que si rien ne les prend en charge.
        sans_corr = rapport["organismes_sans_correspondance"]
        if sans_corr and not rapport["creation_organismes"]:
            ecrire(
                self.style.WARNING(
                    f"\n{len(sans_corr)} organisme(s) de RADIS sans correspondance ici, non créés "
                    "(écriture historique désactivée ou --sans-creation) :"
                )
            )
            for radis_id, nom in sans_corr:
                ecrire(f"  ? {radis_id} — {nom}")

        sans_reserve = rapport["organismes_sans_reserve"]
        if sans_reserve:
            ecrire(
                f"\n{len(sans_reserve)} organisme(s) de RADIS sans réserve en gestion, "
                "non créés (--tous-organismes pour les ajouter quand même)."
            )

        refuses = rapport["organismes_non_creables"]
        if refuses:
            ecrire(
                self.style.ERROR(
                    f"\n{len(refuses)} organisme(s) que la création a refusés :"
                )
            )
            for radis_id, raison in refuses:
                ecrire(f"  ! {radis_id} — {raison}")

        disparus = rapport["organismes_disparus_de_radis"]
        if disparus:
            ecrire(
                self.style.WARNING(
                    f"\n{len(disparus)} organisme(s) rapproché(s) que RADIS ne renvoie plus "
                    "(désactivé là-bas ?), laissés en place :"
                )
            )
            for pk, nom in disparus:
                ecrire(f"  ? {pk} — {nom}")

        supprimees = rapport["reserves_supprimees"]
        if supprimees:
            ecrire(
                self.style.WARNING(
                    f"\n{len(supprimees)} réserve(s) inconnue(s) de RADIS "
                    f"{'à supprimer' if a_blanc else 'supprimées'} — la liste de RADIS fait loi :"
                )
            )
            for code, nom in supprimees:
                ecrire(f"  - {code} — {nom}")

        absentes = rapport["reserves_absentes_ref_geo"]
        if absentes:
            ecrire(
                self.style.WARNING(
                    f"\n{len(absentes)} réserve(s) absente(s) de ref_geo.l_areas : elles ne "
                    "seront pas proposées, un rattachement y échouerait côté base historique :"
                )
            )
            for code in absentes:
                ecrire(f"  ? {code}")
        elif not rapport["ref_geo_consulte"]:
            ecrire(
                self.style.WARNING(
                    "\nBase historique non consultée (LEGACY_DATABASE_URL absente) : "
                    "la présence des réserves dans ref_geo.l_areas n'a pas été vérifiée."
                )
            )
