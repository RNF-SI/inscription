"""Le catalogue doit emporter la correspondance vers les groupes historiques.

Sans elle, ``mirror.legacy_grant_application`` n'écrit rien : un accès validé
n'ajoute l'usager qu'à Keycloak, et les applications RNF ne le voient pas.
"""

from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from inscriptions.legacy_groups import GROUPES_HISTORIQUES
from inscriptions.models import Application
from inscriptions.services import mirror


class SeedCatalogTests(TestCase):
    def test_pose_les_groupes_sur_une_base_neuve(self):
        """Le scénario exact de la production : rien en base, puis seed_catalog.

        La migration 0011 ne pouvait pas le faire — à l'heure de ``migrate`` le
        catalogue n'existe pas encore. C'est ce trou qui a laissé toutes les
        applications sans correspondance après la bascule du 2026-11-03.
        """
        self.assertFalse(Application.objects.exists())

        call_command("seed_catalog", stdout=StringIO())

        psdrf = Application.objects.get(slug="geonature-psdrf")
        self.assertEqual(psdrf.legacy_group_id_role, GROUPES_HISTORIQUES["geonature-psdrf"])
        for slug, id_role in GROUPES_HISTORIQUES.items():
            app = Application.objects.filter(slug=slug).first()
            if app:  # geonature-global n'est pas au catalogue, mais la clé y reste
                self.assertEqual(app.legacy_group_id_role, id_role, slug)

    def test_le_groupe_pose_rend_l_application_ecrivable_cote_historique(self):
        """Ce que la correspondance change concrètement, vu de l'écriture miroir."""
        call_command("seed_catalog", stdout=StringIO())
        psdrf = Application.objects.get(slug="geonature-psdrf")

        mapping = mirror._application_mapping(psdrf)

        self.assertIsNotNone(mapping, "sans correspondance, aucun accès n'est répercuté")
        _id_application, id_profil, group_id_role = mapping
        self.assertEqual(group_id_role, GROUPES_HISTORIQUES["geonature-psdrf"])
        self.assertEqual(id_profil, 1, "Lecteur, ce qu'accordait UsersHub")

    def test_une_valeur_saisie_a_la_main_fait_foi(self):
        """Rejouer la commande ne doit pas écraser une correspondance corrigée."""
        call_command("seed_catalog", stdout=StringIO())
        Application.objects.filter(slug="geonature-psdrf").update(legacy_group_id_role=4242)

        call_command("seed_catalog", stdout=StringIO())

        self.assertEqual(
            Application.objects.get(slug="geonature-psdrf").legacy_group_id_role, 4242
        )

    def test_signale_les_applications_restees_sans_groupe(self):
        """L'absence de correspondance ne doit plus être silencieuse.

        C'est ce silence qui a fait passer le défaut : l'accès était accordé dans
        Keycloak, l'interface affichait un succès, et rien ne disait que la base
        historique n'avait pas suivi.
        """
        sortie = StringIO()
        call_command("seed_catalog", stdout=sortie)
        texte = sortie.getvalue()

        self.assertIn("Sans groupe historique", texte)
        self.assertIn("site-internet", texte, "aucun groupe ne lui correspond")
        self.assertNotIn("geonature-psdrf", texte.split("Sans groupe historique")[1])
