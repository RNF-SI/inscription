"""Tests de la synchronisation du référentiel depuis RADIS.

Hermétiques : ``_appel`` est remplacé par un répartiteur qui rejoue des charges utiles
en mémoire, aucune requête HTTP ne part. Ce qui est vérifié ici n'est pas tant le
format de l'API que les refus de la synchronisation — ne pas supprimer une réserve
déclassée, ne pas inventer un organisme, ne pas toucher à ce qui ne vient pas de RADIS
— puisque c'est là que porte le risque.
"""

import json
from contextlib import contextmanager
from unittest import mock

from django.test import TestCase, override_settings

from inscriptions.models import AuditLog, Organisme, OrganismeReserveLink, Reserve, SynchroRadisRun
from inscriptions.services import radis
from inscriptions.tests.helpers import BaseApiTestCase, auth_client, make_profile, make_reserve

UUID_PNR = "4d2b2f3a-6c1e-4a9f-8b55-0c3d7e1f9a42"
UUID_SMGA = "9f1c7d20-3b8e-4c51-a0d6-7e2b4f8a1c33"


def og(radis_id: int, nom: str, uuid_org: str, *, reserves=("RNN41",), date_fin=None) -> dict:
    """Organisme tel que ``/organismes`` le rend.

    ``reserves`` porte ses gestions ; par défaut une gestion en cours, parce que c'est
    la condition pour être créé — RADIS tient aussi 150 organismes qui n'en gèrent
    aucune. ``date_fin`` les fait toutes passer pour terminées.
    """
    return {
        "id": radis_id,
        "name": nom,
        "uuid_organisme": uuid_org,
        "active": True,
        "reserves": [
            {
                "id_local": code,
                "nom_site": f"Réserve {code}",
                "gestionnaire_principal": False,
                "date_debut": "2020-01-01",
                "date_fin": date_fin,
            }
            for code in reserves
        ],
    }


def liaison(organisme: dict, *, principal: bool = False, date_fin=None) -> dict:
    return {
        "gestionnaire_principal": principal,
        "date_debut": "2020-01-01",
        "date_fin": date_fin,
        "organisme": organisme,
    }


def reserve(
    code: str,
    nom: str,
    *,
    type_rn: str = "RNN",
    ancienne: bool = False,
    date_declassement=None,
    organismes=None,
) -> dict:
    return {
        "id_local": code,
        "nom_site": nom,
        "type_rn": {"label": type_rn, "mnemonique": type_rn.lower()},
        "ancienne_reserve": ancienne,
        "date_declassement": date_declassement,
        "organismes": organismes or [],
    }


@contextmanager
def faux_radis(reserves=None, organismes=None, inventaire=None):
    """Remplace les appels HTTP par les charges utiles données.

    ``inventaire`` est déduit des réserves quand il n'est pas fourni : c'est le cas
    normal, les deux endpoints décrivant le même réseau.
    """
    reserves = list(reserves or [])
    organismes = list(organismes or [])
    if inventaire is None:
        inventaire = [
            {
                "id_local": item["id_local"],
                "nom_site": item["nom_site"],
                "type_rn": "RNN",
                "ancienne_reserve": item.get("ancienne_reserve", False),
            }
            for item in reserves
        ]

    def _appel(chemin, params=None):
        params = params or {}
        if chemin == "/reserves/inventaire":
            return {"items": inventaire, "total": len(inventaire)}
        if chemin == "/reserves":
            return _page(reserves, params)
        if chemin == "/organismes":
            return _page(organismes, params)
        raise AssertionError(f"endpoint inattendu : {chemin}")

    def _page(items, params):
        per_page = int(params.get("per_page") or 100)
        page = int(params.get("page") or 1)
        debut = (page - 1) * per_page
        pages = max(1, -(-len(items) // per_page))
        return {
            "items": items[debut : debut + per_page],
            "page": page,
            "per_page": per_page,
            "total": len(items),
            "pages": pages,
        }

    with mock.patch.object(radis, "_appel", side_effect=_appel) as appel:
        yield appel


class SynchroReservesTests(TestCase):
    def test_cree_les_reserves_absentes(self):
        with faux_radis(reserves=[reserve("RNN41", "Grand Lieu")]):
            rapport = radis.synchroniser()

        ligne = Reserve.objects.get(pk="RNN41")
        self.assertEqual(ligne.area_name, "Grand Lieu")
        self.assertEqual(ligne.type_rn, "RNN")
        self.assertFalse(ligne.ancienne_reserve)
        self.assertEqual(rapport["reserves_creees"], ["RNN41"])

    def test_renommage_applique_sans_toucher_au_reste(self):
        make_reserve(area_code="RNN41", area_name="Ancien nom", id_type="5")
        with faux_radis(reserves=[reserve("RNN41", "Grand Lieu")]):
            rapport = radis.synchroniser()

        ligne = Reserve.objects.get(pk="RNN41")
        self.assertEqual(ligne.area_name, "Grand Lieu")
        # L'id_type hérité de la base historique n'est pas la propriété de RADIS.
        self.assertEqual(ligne.id_type, "5")
        self.assertEqual(rapport["reserves_modifiees"], ["RNN41"])

    def test_second_passage_ne_modifie_rien(self):
        with faux_radis(reserves=[reserve("RNN41", "Grand Lieu")]):
            radis.synchroniser()
            rapport = radis.synchroniser()

        self.assertEqual(rapport["reserves_modifiees"], [])
        self.assertEqual(rapport["reserves_inchangees"], 1)

    def test_declassement_repercute_sans_supprimer(self):
        make_reserve(area_code="RNN99", area_name="Camargue")
        with faux_radis(
            reserves=[reserve("RNN99", "Camargue", ancienne=True, date_declassement="2024-03-12")]
        ):
            rapport = radis.synchroniser()

        ligne = Reserve.objects.get(pk="RNN99")
        self.assertTrue(ligne.ancienne_reserve)
        self.assertEqual(str(ligne.date_declassement), "2024-03-12")
        self.assertEqual(rapport["reserves_declassees"], ["RNN99"])

    def test_type_non_reconnu_ignore_a_la_creation(self):
        """Un périmètre de protection n'est pas une réserve où l'on se rattache."""
        with faux_radis(reserves=[reserve("PP12", "Périmètre", type_rn="PP")]):
            rapport = radis.synchroniser()

        self.assertFalse(Reserve.objects.filter(pk="PP12").exists())
        self.assertEqual([code for code, _ in rapport["reserves_ignorees"]], ["PP12"])

    def test_reserve_inconnue_de_radis_supprimee(self):
        """La liste de RADIS fait loi : son inventaire porte aussi les déclassées."""
        make_reserve(area_code="RNR338", area_name="Réserve disparue")
        with faux_radis(reserves=[reserve("RNN41", "Grand Lieu")]):
            rapport = radis.synchroniser()

        self.assertFalse(Reserve.objects.filter(pk="RNR338").exists())
        self.assertEqual(rapport["reserves_supprimees"], [("RNR338", "Réserve disparue")])

    def test_a_blanc_ne_supprime_pas(self):
        make_reserve(area_code="RNR338", area_name="Réserve disparue")
        with faux_radis(reserves=[reserve("RNN41", "Grand Lieu")]):
            rapport = radis.synchroniser(a_blanc=True)

        self.assertTrue(Reserve.objects.filter(pk="RNR338").exists())
        self.assertEqual(rapport["reserves_supprimees"], [("RNR338", "Réserve disparue")])

    def test_reserve_declassee_conservee(self):
        """Déclassée n'est pas absente : elle est dans l'inventaire, donc elle reste."""
        make_reserve(area_code="RNN99", area_name="Camargue")
        with faux_radis(reserves=[reserve("RNN99", "Camargue", ancienne=True)]):
            radis.synchroniser()

        self.assertTrue(Reserve.objects.filter(pk="RNN99").exists())

    def test_inventaire_vide_refuse(self):
        """Un inventaire vide déclarerait tout le réseau déclassé."""
        make_reserve(area_code="RNN41")
        with faux_radis(reserves=[], inventaire=[]):
            with self.assertRaises(radis.ErreurRadis):
                radis.synchroniser()

        self.assertTrue(Reserve.objects.filter(pk="RNN41").exists())

    def test_a_blanc_n_ecrit_rien(self):
        make_reserve(area_code="RNN41", area_name="Ancien nom")
        with faux_radis(
            reserves=[reserve("RNN41", "Grand Lieu"), reserve("RNR12", "Nouvelle")]
        ):
            rapport = radis.synchroniser(a_blanc=True)

        self.assertEqual(Reserve.objects.get(pk="RNN41").area_name, "Ancien nom")
        self.assertFalse(Reserve.objects.filter(pk="RNR12").exists())
        # Le rapport dit pourtant ce qui aurait changé.
        self.assertEqual(rapport["reserves_creees"], ["RNR12"])
        self.assertEqual(rapport["reserves_modifiees"], ["RNN41"])


class SynchroOrganismesTests(TestCase):
    def setUp(self):
        self.pnr = Organisme.objects.create(
            id_organisme=7,
            uuid_organisme=UUID_PNR,
            nom_organisme="PNR de Camargue",
            keycloak_slug="pnr-de-camargue",
        )

    def test_rapproche_par_uuid_puis_renomme(self):
        with faux_radis(
            reserves=[reserve("RNN41", "Grand Lieu")],
            organismes=[og(31, "Parc naturel régional de Camargue", UUID_PNR)],
        ):
            rapport = radis.synchroniser()

        self.pnr.refresh_from_db()
        self.assertEqual(self.pnr.radis_id, 31)
        self.assertEqual(self.pnr.nom_organisme, "Parc naturel régional de Camargue")
        # Le slug est dans le chemin du groupe Keycloak, donc dans les jetons émis.
        self.assertEqual(self.pnr.keycloak_slug, "pnr-de-camargue")
        self.assertEqual(rapport["organismes_rattaches"], [(7, 31)])
        self.assertEqual(
            rapport["organismes_renommes"], [(7, "PNR de Camargue", "Parc naturel régional de Camargue")]
        )

    def test_uuid_insensible_a_la_casse(self):
        self.pnr.uuid_organisme = UUID_PNR.upper()
        self.pnr.save(update_fields=["uuid_organisme"])
        with faux_radis(
            reserves=[reserve("RNN41", "Grand Lieu")],
            organismes=[og(31, "PNR de Camargue", UUID_PNR)],
        ):
            radis.synchroniser()

        self.pnr.refresh_from_db()
        self.assertEqual(self.pnr.radis_id, 31)

    def test_organisme_sans_correspondance_signale_jamais_cree(self):
        """L'id_organisme est la clé primaire de bib_organismes : on ne l'invente pas."""
        with faux_radis(
            reserves=[reserve("RNN41", "Grand Lieu")],
            organismes=[og(99, "Syndicat mixte inconnu", UUID_SMGA)],
        ):
            rapport = radis.synchroniser()

        self.assertEqual(Organisme.objects.count(), 1)
        self.assertEqual(rapport["organismes_sans_correspondance"], [(99, "Syndicat mixte inconnu")])

    def test_organisme_local_intouche(self):
        """Un organisme qui ne gère pas de réserve n'a rien à voir avec RADIS."""
        local = Organisme.objects.create(
            id_organisme=800, nom_organisme="Association locale", keycloak_slug="association-locale"
        )
        with faux_radis(
            reserves=[reserve("RNN41", "Grand Lieu")],
            organismes=[og(31, "PNR de Camargue", UUID_PNR)],
        ):
            rapport = radis.synchroniser()

        local.refresh_from_db()
        self.assertIsNone(local.radis_id)
        self.assertEqual(local.nom_organisme, "Association locale")
        self.assertEqual(rapport["organismes_disparus_de_radis"], [])

    def test_organisme_rapproche_puis_absent_est_signale(self):
        self.pnr.radis_id = 31
        self.pnr.save(update_fields=["radis_id"])
        with faux_radis(reserves=[reserve("RNN41", "Grand Lieu")], organismes=[]):
            rapport = radis.synchroniser()

        self.pnr.refresh_from_db()
        self.assertEqual(self.pnr.radis_id, 31)
        self.assertEqual(rapport["organismes_disparus_de_radis"], [(7, "PNR de Camargue")])


class UuidPartageTests(TestCase):
    """La production compte dix UUID du SINP portés par plusieurs organismes de RADIS.

    Ils ne désignent pas des doublons : « Conservatoire d'espaces naturels de
    Normandie » et « Région Normandie » partagent le même. Rapprocher par cette valeur
    renommerait le conservatoire en région.
    """

    def setUp(self):
        self.cen = Organisme.objects.create(
            id_organisme=148,
            uuid_organisme=UUID_PNR,
            nom_organisme="Conservatoire d'espaces naturels de Normandie",
            keycloak_slug="cen-normandie",
        )

    def test_uuid_partage_ne_rapproche_pas(self):
        with faux_radis(
            reserves=[reserve("RNN41", "Grand Lieu")],
            organismes=[og(139, "Région Normandie", UUID_PNR), og(309, "CEN Normandie", UUID_PNR)],
        ):
            rapport = radis.synchroniser()

        self.cen.refresh_from_db()
        self.assertEqual(
            self.cen.nom_organisme, "Conservatoire d'espaces naturels de Normandie"
        )
        self.assertIsNone(self.cen.radis_id)
        self.assertEqual(rapport["organismes_renommes"], [])
        self.assertEqual(
            sorted(radis_id for radis_id, _, _ in rapport["organismes_uuid_partage"]), [139, 309]
        )

    def test_radis_id_deja_pose_resiste_a_l_ambiguite(self):
        """Un organisme déjà rapproché garde sa clé : le radis_id passe avant l'UUID."""
        self.cen.radis_id = 309
        self.cen.save(update_fields=["radis_id"])
        with faux_radis(
            reserves=[reserve("RNN41", "Grand Lieu")],
            organismes=[og(139, "Région Normandie", UUID_PNR), og(309, "CEN Normandie", UUID_PNR)],
        ):
            rapport = radis.synchroniser()

        self.cen.refresh_from_db()
        self.assertEqual(self.cen.nom_organisme, "CEN Normandie")
        self.assertEqual(rapport["organismes_sans_correspondance"], [(139, "Région Normandie")])


class FauxLegacy:
    """Écriture historique bouchonnée : la séquence de bib_organismes en mémoire."""

    def __init__(self, *, existants=None, prochain_id=500):
        self.existants = existants or {}
        self.prochain_id = prochain_id
        self.crees: list[dict] = []

    def is_enabled(self):
        return True

    def find_organisme(self, *, uuid_organisme="", nom_organisme=""):
        for cle in (uuid_organisme, (nom_organisme or "").lower()):
            if cle and cle in self.existants:
                return self.existants[cle]
        return None

    def create_organisme(self, **kwargs):
        from inscriptions.services.legacy_writer import NouvelOrganisme

        self.crees.append(kwargs)
        ligne = NouvelOrganisme(
            self.prochain_id, kwargs.get("uuid_organisme") or f"uuid-{self.prochain_id}"
        )
        self.prochain_id += 1
        return ligne


@contextmanager
def faux_legacy(**kwargs):
    faux = FauxLegacy(**kwargs)
    with mock.patch.object(radis, "legacy_writer", faux):
        yield faux


class CreationOrganismesTests(TestCase):
    """Un organisme créé dans RADIS doit exister ici — et d'abord dans bib_organismes."""

    def test_cree_dans_bib_organismes_puis_ici(self):
        with faux_legacy() as legacy:
            with faux_radis(
                reserves=[reserve("RNN41", "Grand Lieu")],
                organismes=[
                    {
                        **og(44, "Agence de l'eau Loire-Bretagne", UUID_SMGA),
                        "street1": "9 avenue Buffon",
                        "postal_code": "45100",
                        "city": "Orléans",
                        "logo_url": "https://radis/logo.png",
                    }
                ],
            ):
                rapport = radis.synchroniser()

        org = Organisme.objects.get(nom_organisme="Agence de l'eau Loire-Bretagne")
        # L'identifiant vient de la base historique, il n'est pas choisi ici.
        self.assertEqual(org.id_organisme, 500)
        self.assertEqual(org.uuid_organisme, UUID_SMGA)
        self.assertEqual(org.radis_id, 44)
        self.assertEqual(org.keycloak_slug, "agence-de-leau-loire-bretagne")
        self.assertEqual(rapport["organismes_crees"], [(500, "Agence de l'eau Loire-Bretagne")])
        self.assertEqual(legacy.crees[0]["ville_organisme"], "Orléans")
        self.assertEqual(legacy.crees[0]["adresse_organisme"], "9 avenue Buffon")

    def test_organisme_deja_dans_bib_organismes_adopte(self):
        """Une ligne historique posée à la main ne doit pas être dupliquée."""
        from inscriptions.services.legacy_writer import NouvelOrganisme

        existant = NouvelOrganisme(312, UUID_SMGA)
        with faux_legacy(existants={UUID_SMGA: existant}) as legacy:
            with faux_radis(
                reserves=[reserve("RNN41", "Grand Lieu")],
                organismes=[og(44, "Agence de l'eau Loire-Bretagne", UUID_SMGA)],
            ):
                rapport = radis.synchroniser()

        self.assertEqual(legacy.crees, [])
        org = Organisme.objects.get(pk=312)
        self.assertEqual(org.radis_id, 44)
        self.assertEqual(rapport["organismes_adoptes"], [(312, "Agence de l'eau Loire-Bretagne")])

    def test_adoption_corrige_le_nom_dans_le_meme_passage(self):
        """Sinon le second passage renommait encore, et la commande n'était pas idempotente."""
        from inscriptions.services.legacy_writer import NouvelOrganisme

        Organisme.objects.create(
            id_organisme=268,
            uuid_organisme=UUID_SMGA,
            nom_organisme="Parc National de la Réunion",
            keycloak_slug="parc-national-de-la-reunion",
        )
        existant = NouvelOrganisme(268, UUID_SMGA)
        with faux_legacy(existants={"parc national de la réunion": existant}):
            with faux_radis(
                reserves=[reserve("RNN41", "Grand Lieu")],
                organismes=[og(90, "Parc national de la Réunion", "")],
            ):
                rapport = radis.synchroniser()

        org = Organisme.objects.get(pk=268)
        self.assertEqual(org.nom_organisme, "Parc national de la Réunion")
        self.assertEqual(org.radis_id, 90)
        self.assertEqual(org.keycloak_slug, "parc-national-de-la-reunion")
        self.assertEqual(
            rapport["organismes_renommes"],
            [(268, "Parc National de la Réunion", "Parc national de la Réunion")],
        )

    def test_uuid_partage_non_recopie_a_la_creation(self):
        """Propager un UUID déjà porté par un autre organisme aggraverait le problème."""
        with faux_legacy() as legacy:
            with faux_radis(
                reserves=[reserve("RNN41", "Grand Lieu")],
                organismes=[og(44, "Région Normandie", UUID_SMGA), og(45, "CEN Normandie", UUID_SMGA)],
            ):
                radis.synchroniser()

        self.assertEqual([c["uuid_organisme"] for c in legacy.crees], [None, None])

    def test_organisme_sans_reserve_non_cree(self):
        """Les agences de l'eau, ministères et fondations que RADIS porte n'ont rien à
        faire dans une table que toutes les applications RNF lisent."""
        with faux_legacy() as legacy:
            with faux_radis(
                reserves=[reserve("RNN41", "Grand Lieu")],
                organismes=[og(61, "Agence de l'eau Adour-Garonne", UUID_SMGA, reserves=())],
            ):
                rapport = radis.synchroniser()

        self.assertEqual(legacy.crees, [])
        self.assertFalse(Organisme.objects.exists())
        self.assertEqual(rapport["organismes_sans_reserve"], [(61, "Agence de l'eau Adour-Garonne")])

    def test_ancien_gestionnaire_non_cree(self):
        """Une gestion terminée ne propose plus rien : elle ne justifie pas la création."""
        with faux_legacy() as legacy:
            with faux_radis(
                reserves=[reserve("RNN41", "Grand Lieu")],
                organismes=[og(62, "Ancien gestionnaire", UUID_SMGA, date_fin="2023-12-31")],
            ):
                rapport = radis.synchroniser()

        self.assertEqual(legacy.crees, [])
        self.assertEqual(rapport["organismes_sans_reserve"], [(62, "Ancien gestionnaire")])

    def test_creer_tous_leve_la_regle(self):
        with faux_legacy() as legacy:
            with faux_radis(
                reserves=[reserve("RNN41", "Grand Lieu")],
                organismes=[og(61, "Agence de l'eau Adour-Garonne", UUID_SMGA, reserves=())],
            ):
                rapport = radis.synchroniser(creer_tous_organismes=True)

        self.assertEqual(len(legacy.crees), 1)
        self.assertEqual(rapport["organismes_sans_reserve"], [])
        self.assertTrue(Organisme.objects.exists())

    def test_a_blanc_ne_cree_rien_mais_annonce(self):
        with faux_legacy() as legacy:
            with faux_radis(
                reserves=[reserve("RNN41", "Grand Lieu")],
                organismes=[og(44, "Agence de l'eau Loire-Bretagne", UUID_SMGA)],
            ):
                rapport = radis.synchroniser(a_blanc=True)

        self.assertEqual(legacy.crees, [])
        self.assertFalse(Organisme.objects.exists())
        # Sans identifiant : la séquence de bib_organismes n'a pas été sollicitée.
        self.assertEqual(rapport["organismes_crees"], [(None, "Agence de l'eau Loire-Bretagne")])

    def test_a_blanc_distingue_l_adoption_de_la_creation(self):
        """La recherche dans bib_organismes est en lecture seule : elle a lieu à blanc."""
        from inscriptions.services.legacy_writer import NouvelOrganisme

        with faux_legacy(existants={UUID_SMGA: NouvelOrganisme(312, UUID_SMGA)}):
            with faux_radis(
                reserves=[reserve("RNN41", "Grand Lieu")],
                organismes=[
                    og(44, "Agence de l'eau Loire-Bretagne", UUID_SMGA),
                    og(45, "Agence Bretonne de la Biodiversité", ""),
                ],
            ):
                rapport = radis.synchroniser(a_blanc=True)

        self.assertEqual(rapport["organismes_adoptes"], [(312, "Agence de l'eau Loire-Bretagne")])
        self.assertEqual(rapport["organismes_crees"], [(None, "Agence Bretonne de la Biodiversité")])
        self.assertFalse(Organisme.objects.exists())

    def test_sans_ecriture_historique_rien_n_est_cree(self):
        """Créer ici sans ligne bib_organismes casserait la création de compte des membres."""
        with faux_radis(
            reserves=[reserve("RNN41", "Grand Lieu")],
            organismes=[og(44, "Agence de l'eau Loire-Bretagne", UUID_SMGA)],
        ):
            rapport = radis.synchroniser()

        self.assertFalse(Organisme.objects.exists())
        self.assertFalse(rapport["creation_organismes"])

    def test_organisme_cree_recoit_ses_liens_dans_le_meme_passage(self):
        item = og(44, "Agence de l'eau Loire-Bretagne", UUID_SMGA)
        with faux_legacy():
            with faux_radis(
                reserves=[reserve("RNN41", "Grand Lieu", organismes=[liaison(item, principal=True)])],
                organismes=[item],
            ):
                rapport = radis.synchroniser()

        lien = OrganismeReserveLink.objects.get(reserve_id="RNN41")
        self.assertEqual(lien.organisme.radis_id, 44)
        self.assertEqual(rapport["liens_crees"], 1)


class SynchroLiensTests(TestCase):
    def setUp(self):
        self.pnr = Organisme.objects.create(
            id_organisme=7, uuid_organisme=UUID_PNR, nom_organisme="PNR de Camargue"
        )
        self.item_pnr = og(31, "PNR de Camargue", UUID_PNR)

    def test_lien_cree_depuis_les_gestionnaires_en_cours(self):
        with faux_radis(
            reserves=[
                reserve("RNN41", "Grand Lieu", organismes=[liaison(self.item_pnr, principal=True)])
            ],
            organismes=[self.item_pnr],
        ):
            rapport = radis.synchroniser()

        lien = OrganismeReserveLink.objects.get(organisme=self.pnr, reserve_id="RNN41")
        self.assertTrue(lien.principal)
        self.assertEqual(rapport["liens_crees"], 1)

    def test_gestionnaire_termine_ignore(self):
        with faux_radis(
            reserves=[
                reserve(
                    "RNN41",
                    "Grand Lieu",
                    organismes=[liaison(self.item_pnr, date_fin="2023-12-31")],
                )
            ],
            organismes=[self.item_pnr],
        ):
            radis.synchroniser()

        self.assertFalse(OrganismeReserveLink.objects.exists())

    def test_lien_perime_supprime(self):
        """Un lien n'est pas un droit : il propose une réserve, et doit cesser de le faire."""
        res = make_reserve(area_code="RNN41", area_name="Grand Lieu")
        self.pnr.radis_id = 31
        self.pnr.save(update_fields=["radis_id"])
        OrganismeReserveLink.objects.create(organisme=self.pnr, reserve=res, principal=True)

        with faux_radis(reserves=[reserve("RNN41", "Grand Lieu")], organismes=[self.item_pnr]):
            rapport = radis.synchroniser()

        self.assertFalse(OrganismeReserveLink.objects.exists())
        self.assertEqual(rapport["liens_supprimes"], 1)

    def test_lien_d_organisme_local_non_supprime(self):
        res = make_reserve(area_code="RNN41", area_name="Grand Lieu")
        local = Organisme.objects.create(id_organisme=800, nom_organisme="Association locale")
        OrganismeReserveLink.objects.create(organisme=local, reserve=res)

        with faux_radis(reserves=[reserve("RNN41", "Grand Lieu")], organismes=[self.item_pnr]):
            rapport = radis.synchroniser()

        self.assertTrue(OrganismeReserveLink.objects.filter(organisme=local).exists())
        self.assertEqual(rapport["liens_supprimes"], 0)

    def test_principal_mis_a_jour(self):
        res = make_reserve(area_code="RNN41", area_name="Grand Lieu")
        self.pnr.radis_id = 31
        self.pnr.save(update_fields=["radis_id"])
        OrganismeReserveLink.objects.create(organisme=self.pnr, reserve=res, principal=False)

        with faux_radis(
            reserves=[
                reserve("RNN41", "Grand Lieu", organismes=[liaison(self.item_pnr, principal=True)])
            ],
            organismes=[self.item_pnr],
        ):
            rapport = radis.synchroniser()

        self.assertTrue(OrganismeReserveLink.objects.get(organisme=self.pnr).principal)
        self.assertEqual(rapport["liens_modifies"], 1)


class RefGeoTests(TestCase):
    """Marquage des réserves que ``ref_geo.l_areas`` ignore."""

    @contextmanager
    def _fausse_base(self, presentes):
        class Curseur:
            def execute(self, sql, params=None):
                self.params = params

            def fetchall(self):
                return [(code,) for code in presentes]

        @contextmanager
        def _cursor():
            yield Curseur()

        connections = mock.MagicMock()
        connections.databases = {"default": {}, "legacy": {}}
        connections.__getitem__.return_value.cursor = _cursor
        with mock.patch.object(radis, "connections", connections):
            yield

    def test_reserve_absente_de_ref_geo_marquee(self):
        with self._fausse_base(presentes=["RNN41"]):
            with faux_radis(
                reserves=[reserve("RNN41", "Grand Lieu"), reserve("RNR338", "Fantôme")]
            ):
                rapport = radis.synchroniser()

        self.assertFalse(Reserve.objects.get(pk="RNN41").absente_ref_geo)
        self.assertTrue(Reserve.objects.get(pk="RNR338").absente_ref_geo)
        self.assertEqual(rapport["reserves_absentes_ref_geo"], ["RNR338"])

    def test_retour_dans_ref_geo_demarque(self):
        with self._fausse_base(presentes=[]):
            with faux_radis(reserves=[reserve("RNR338", "Fantôme")]):
                radis.synchroniser()
        self.assertTrue(Reserve.objects.get(pk="RNR338").absente_ref_geo)

        with self._fausse_base(presentes=["RNR338"]):
            with faux_radis(reserves=[reserve("RNR338", "Fantôme")]):
                radis.synchroniser()
        self.assertFalse(Reserve.objects.get(pk="RNR338").absente_ref_geo)

    def test_base_historique_absente_ne_marque_rien(self):
        """Sans la base, « présente » n'est pas une conclusion qu'on peut tirer."""
        make_reserve(area_code="RNR338", area_name="Fantôme", absente_ref_geo=True)
        with faux_radis(reserves=[reserve("RNR338", "Fantôme")]):
            rapport = radis.synchroniser()

        self.assertTrue(Reserve.objects.get(pk="RNR338").absente_ref_geo)
        self.assertFalse(rapport["ref_geo_consulte"])


class ListesPubliquesTests(BaseApiTestCase):
    """Ce que la synchronisation change pour les listes où l'on se rattache."""

    def test_reserve_declassee_absente_de_la_liste(self):
        make_reserve(area_code="RNN41", area_name="Grand Lieu")
        make_reserve(area_code="RNN99", area_name="Camargue", ancienne_reserve=True)
        reponse = self.client.get("/api/reserves/")
        codes = [item["area_code"] for item in reponse.json()]
        self.assertEqual(codes, ["RNN41"])

    def test_reserve_absente_de_ref_geo_absente_de_la_liste(self):
        make_reserve(area_code="RNN41", area_name="Grand Lieu")
        make_reserve(area_code="RNR338", area_name="Fantôme", absente_ref_geo=True)
        reponse = self.client.get("/api/reserves/")
        codes = [item["area_code"] for item in reponse.json()]
        self.assertEqual(codes, ["RNN41"])

    def test_reserve_creee_par_radis_sans_id_type_reste_proposee(self):
        """Le filtre sur id_type écartait les réserves que RADIS crée."""
        with faux_radis(reserves=[reserve("RNR12", "Nouvelle")]):
            radis.synchroniser()
        reponse = self.client.get("/api/reserves/")
        self.assertEqual([item["area_code"] for item in reponse.json()], ["RNR12"])


@override_settings(RADIS_API_URL="", RADIS_API_KEY="")
class ConfigurationTests(TestCase):
    def test_sans_configuration_erreur_claire(self):
        with self.assertRaises(radis.ErreurRadis):
            radis.lire_inventaire()


class PassagesJournalisesTests(TestCase):
    """``executer()`` laisse une trace, que le bouton comme le minuteur alimentent."""

    def test_passage_reussi_journalise(self):
        with faux_radis(reserves=[reserve("RNN41", "Grand Lieu")]):
            passage, _rapport = radis.executer(declencheur="minuteur")

        passage.refresh_from_db()
        self.assertTrue(passage.ok)
        self.assertEqual(passage.declencheur, "minuteur")
        self.assertIsNotNone(passage.finished_at)
        self.assertEqual(passage.report["reserves"]["creees"], ["RNN41"])
        self.assertEqual(passage.error, "")

    def test_passage_en_echec_journalise_et_releve(self):
        """L'erreur doit remonter à l'appelant, et rester lisible le lendemain."""
        with faux_radis(reserves=[], inventaire=[]):
            with self.assertRaises(radis.ErreurRadis):
                radis.executer(declencheur="bouton", actor_sub="sub-admin")

        passage = SynchroRadisRun.objects.get()
        self.assertFalse(passage.ok)
        self.assertIn("inventaire", passage.error.lower())
        self.assertEqual(passage.actor_sub, "sub-admin")
        self.assertIsNotNone(passage.finished_at)

    def test_resume_est_serialisable_en_json(self):
        """``report`` est une colonne JSON : ni date ni ensemble ne doivent y entrer."""
        with faux_radis(
            reserves=[
                reserve("RNN41", "Grand Lieu", organismes=[liaison(og(31, "PNR", UUID_PNR))]),
                reserve("PP12", "Périmètre", type_rn="PP"),
            ],
            organismes=[og(31, "PNR", UUID_PNR)],
        ):
            _passage, rapport = radis.executer()

        json.dumps(radis.resume(rapport))  # ne doit pas lever

    def test_a_blanc_journalise_aussi(self):
        with faux_radis(reserves=[reserve("RNN41", "Grand Lieu")]):
            passage, _ = radis.executer(a_blanc=True)

        self.assertTrue(passage.a_blanc)
        self.assertTrue(passage.report["a_blanc"])
        self.assertFalse(Reserve.objects.exists())


class RouteSynchroRadisTests(BaseApiTestCase):
    def setUp(self):
        super().setUp()
        self.super_admin = make_profile(is_super_admin=True)
        self.simple = make_profile()

    def test_refusee_hors_super_admin(self):
        auth_client(self.client, self.simple)
        self.assertEqual(self.client.get("/api/admin/synchro-radis/").status_code, 403)
        self.assertEqual(self.client.post("/api/admin/synchro-radis/").status_code, 403)

    def test_bouton_declenche_et_journalise(self):
        auth_client(self.client, self.super_admin)
        with faux_radis(reserves=[reserve("RNN41", "Grand Lieu")]):
            reponse = self.client.post("/api/admin/synchro-radis/", {}, format="json")

        self.assertEqual(reponse.status_code, 200)
        corps = reponse.json()
        self.assertTrue(corps["ok"])
        self.assertEqual(corps["declencheur"], "bouton")
        self.assertEqual(corps["report"]["reserves"]["creees"], ["RNN41"])
        self.assertTrue(Reserve.objects.filter(pk="RNN41").exists())
        self.assertTrue(AuditLog.objects.filter(action="synchro_radis").exists())

    def test_simulation_n_ecrit_rien(self):
        auth_client(self.client, self.super_admin)
        with faux_radis(reserves=[reserve("RNN41", "Grand Lieu")]):
            reponse = self.client.post(
                "/api/admin/synchro-radis/", {"a_blanc": True}, format="json"
            )

        self.assertEqual(reponse.status_code, 200)
        self.assertTrue(reponse.json()["a_blanc"])
        self.assertFalse(Reserve.objects.exists())

    def test_echec_radis_repond_503(self):
        """La demande est valide : c'est RADIS qui manque, et le passage est à retenter."""
        auth_client(self.client, self.super_admin)
        with faux_radis(reserves=[], inventaire=[]):
            reponse = self.client.post("/api/admin/synchro-radis/", {}, format="json")

        self.assertEqual(reponse.status_code, 503)
        self.assertIn("inventaire", reponse.json()["detail"].lower())

    def test_historique_des_passages(self):
        auth_client(self.client, self.super_admin)
        with faux_radis(reserves=[reserve("RNN41", "Grand Lieu")]):
            radis.executer(declencheur="minuteur")
        reponse = self.client.get("/api/admin/synchro-radis/")

        self.assertEqual(reponse.status_code, 200)
        corps = reponse.json()
        self.assertEqual(len(corps["passages"]), 1)
        self.assertEqual(corps["passages"][0]["declencheur"], "minuteur")
        self.assertIn("configure", corps)
