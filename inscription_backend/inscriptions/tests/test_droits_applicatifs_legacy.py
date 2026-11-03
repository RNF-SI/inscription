"""Les droits applicatifs lus par l'import viennent des groupes, pas des profils.

``utilisateurs.cor_role_app_profil`` ne compte que 31 lignes pour 993 comptes :
s'y limiter laissait presque tous les comptes repris sans application dans
Keycloak. Ce sont les groupes de ``utilisateurs.cor_roles`` qui portent les droits.
"""

from contextlib import contextmanager
from unittest.mock import patch

from django.test import TestCase

from inscriptions.models import Application
from inscriptions.services import legacy_user_migration as mig


class _CurseurFactice:
    """Rend la réponse voulue selon la table interrogée."""

    def __init__(self, profils, appartenances):
        self._profils = profils
        self._appartenances = appartenances
        self._rows: list = []

    def execute(self, sql, params=None):
        self._rows = self._appartenances if "cor_roles g" in sql and "cor_role_app_profil" not in sql else self._profils

    def fetchall(self):
        return self._rows


def _patch_cursor(curseur):
    @contextmanager
    def _fake():
        yield curseur

    return patch.object(mig, "_legacy_cursor", _fake)


class DroitsDepuisLesGroupesTests(TestCase):
    def setUp(self):
        self.psdrf = Application.objects.create(
            slug="geonature-psdrf", nom="GeoNature PSDRF", legacy_group_id_role=1
        )
        self.ancrage = Application.objects.create(
            slug="ancrage", nom="Ancrage", legacy_group_id_role=64
        )

    def test_les_membres_du_groupe_recoivent_l_application(self):
        """Le cas constaté en production : Grp_global_et_psdrf et Grp_ancrage.

        Aucune ligne dans ``cor_role_app_profil``, et pourtant les trois comptes
        doivent ressortir avec leur application.
        """
        curseur = _CurseurFactice(
            profils=[],
            appartenances=[(10, 1), (11, 1), (12, 64)],
        )
        with _patch_cursor(curseur):
            droits = mig._load_app_rights({})

        self.assertEqual(set(droits[10]), {"geonature-psdrf"})
        self.assertEqual(set(droits[11]), {"geonature-psdrf"})
        self.assertEqual(set(droits[12]), {"ancrage"})

    def test_un_groupe_peut_porter_plusieurs_applications(self):
        """Le groupe 1 est ``Grp_global_et_psdrf`` : il en vaut deux."""
        Application.objects.create(
            slug="geonature-global", nom="GeoNature Global", legacy_group_id_role=1
        )
        curseur = _CurseurFactice(profils=[], appartenances=[(10, 1)])
        with _patch_cursor(curseur):
            droits = mig._load_app_rights({})

        self.assertEqual(set(droits[10]), {"geonature-psdrf", "geonature-global"})

    def test_le_profil_d_administration_n_est_pas_dilue_par_le_groupe(self):
        """Un admin de `cor_role_app_profil` membre du groupe reste admin.

        ``load_legacy_users`` lit ce dictionnaire en faisant gagner le profil
        d'administration : l'ajout du profil Lecteur ne doit pas le déclasser.
        """
        curseur = _CurseurFactice(
            profils=[(10, 77, mig.LEGACY_ADMIN_PROFIL_ID)],
            appartenances=[(10, 1)],
        )
        with _patch_cursor(curseur):
            droits = mig._load_app_rights({77: "geonature-psdrf"})

        profils = droits[10]["geonature-psdrf"]
        self.assertIn(mig.LEGACY_ADMIN_PROFIL_ID, profils)
        self.assertIn(mig.LEGACY_MEMBER_PROFIL_ID, profils)

    def test_la_correspondance_lue_est_celle_de_la_base(self):
        """Une valeur corrigée à la main doit faire foi, pas le dictionnaire figé."""
        Application.objects.filter(slug="ancrage").update(legacy_group_id_role=4242)
        curseur = _CurseurFactice(profils=[], appartenances=[(12, 4242), (13, 64)])
        with _patch_cursor(curseur):
            droits = mig._load_app_rights({})

        self.assertEqual(set(droits[12]), {"ancrage"})
        self.assertNotIn(13, droits, "le groupe 64 n'est plus déclaré")

    def test_sans_correspondance_declaree_aucune_requete_de_groupe(self):
        """Rien à demander à la base historique si aucune application n'est reliée."""
        Application.objects.update(legacy_group_id_role=None)
        curseur = _CurseurFactice(profils=[], appartenances=[(10, 1)])
        with _patch_cursor(curseur):
            self.assertEqual(mig._load_app_rights_from_groups(), {})
