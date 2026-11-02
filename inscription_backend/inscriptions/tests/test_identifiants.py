"""Régularisation de l'identifiant par son titulaire.

L'import a dû renommer les identifiants que Keycloak refuse (voir
``test_legacy_user_migration``), sans toucher à ``t_roles.identifiant`` dont dépendent
les applications qui lisent encore la base. Ces comptes portent donc deux noms, et
« Mon compte » propose d'en choisir un conforme, écrit des deux côtés.

Ces tests verrouillent le signalement de la divergence, les règles qui empêchent le
nouvel identifiant de recréer l'écart, et le refus d'un identifiant déjà pris.
"""

from unittest import mock

from django.core.cache import cache
from django.test import SimpleTestCase, TestCase

from inscriptions.keycloak_client import KeycloakAdminError
from inscriptions.serializers import MeUpdateSerializer
from inscriptions.services import legacy_writer, mirror
from inscriptions.services.legacy_user_migration import normalize_username
from inscriptions.tests.helpers import legacy_user_row


class DivergenceTests(TestCase):
    """``/api/me/`` dit s'il faut inviter l'usager à régulariser son identifiant."""

    def setUp(self):
        # L'état est mémorisé : chaque cas doit repartir d'un cache vide.
        cache.clear()
        self.addCleanup(cache.clear)

    def _kc(self, *, username: str, federation: bool = False):
        kc = mock.MagicMock()
        kc.get_user.return_value = {
            "id": "sub-1",
            "username": username,
            "attributes": {"legacy_id_role": ["42"]},
            **({"federationLink": "ldap-rnf"} if federation else {}),
        }
        return kc

    def _etat(self, kc, identifiant_historique):
        with mock.patch.object(legacy_writer, "is_enabled", return_value=True), \
             mock.patch.object(
                 legacy_writer, "get_role_identifiant", return_value=identifiant_historique
             ):
            return mirror.legacy_username_state(kc, "sub-1")

    def test_identifiant_renomme_est_signale(self):
        etat = self._etat(self._kc(username="paul.lesiak"), "Paul Lesiak")
        self.assertEqual(etat, ("Paul Lesiak", True))

    def test_identifiants_identiques_ne_signalent_rien(self):
        etat = self._etat(self._kc(username="paul.lesiak"), "paul.lesiak")
        self.assertEqual(etat, ("paul.lesiak", False))

    def test_compte_federe_nest_jamais_signale(self):
        """Son identifiant appartient à l'annuaire : la plateforme ne peut pas le
        renommer, et le bandeau ne disparaîtrait jamais."""
        kc = self._kc(username="zacharie.moulin", federation=True)
        self.assertEqual(self._etat(kc, "z.moulin"), ("z.moulin", False))

    def test_sans_base_historique_rien_a_dire(self):
        kc = self._kc(username="paul.lesiak")
        with mock.patch.object(legacy_writer, "is_enabled", return_value=False):
            self.assertEqual(mirror.legacy_username_state(kc, "sub-1"), ("", False))
        kc.get_user.assert_not_called()

    def test_keycloak_injoignable_ne_fait_pas_echouer_la_lecture(self):
        kc = mock.MagicMock()
        kc.get_user.side_effect = KeycloakAdminError("get_user_failed:503")
        with mock.patch.object(legacy_writer, "is_enabled", return_value=True):
            self.assertEqual(mirror.legacy_username_state(kc, "sub-1"), ("", False))

class ReglesDeSaisieTests(SimpleTestCase):
    """Le nouvel identifiant est écrit dans les deux mondes : il doit être identique
    des deux côtés, donc en minuscules — Keycloak replie les identifiants — et sans
    arobase, qui redevient ambigu dès que la connexion par e-mail est active."""

    def _valide(self, valeur):
        ser = MeUpdateSerializer(data={"username": valeur})
        return ser.validated_data["username"] if ser.is_valid() else None

    def test_minuscules_imposees(self):
        self.assertEqual(self._valide("Jean.Dupont"), "jean.dupont")

    def test_refus_des_caracteres_interdits(self):
        for valeur in ("jean dupont", "jean!", "jean/dupont", "jéan", "jean@rnf.fr"):
            with self.subTest(valeur):
                self.assertIsNone(self._valide(valeur))

    def test_refus_trop_court(self):
        self.assertIsNone(self._valide("ov"))

    def test_formes_acceptees(self):
        for valeur in ("jean.dupont", "j_dupont", "jean-dupont", "rnn41", "abc"):
            with self.subTest(valeur):
                self.assertEqual(self._valide(valeur), valeur)

    def test_resultat_toujours_accepte_par_lapi(self):
        """La normalisation et MeUpdateSerializer doivent appliquer la même règle,
        sinon un compte renommé à l'import serait refusé s'il se renommait lui-même."""
        for brut in ("Paul Lesiak", "OV", "Bast/29/08", "valentin.demets@forestallia.com", "!!"):
            with self.subTest(brut):
                propose = normalize_username(legacy_user_row(brut, first_name="Olivier", last_name="Vannucci"))
                ser = MeUpdateSerializer(data={"username": propose})
                self.assertTrue(ser.is_valid(), ser.errors)
                self.assertEqual(ser.validated_data["username"], propose)

class ConflitDidentifiantTests(TestCase):
    """Le nouvel identifiant est écrit des deux côtés : il doit être libre des deux
    côtés. Deux comptes qui le partageraient casseraient la connexion aux
    applications qui le lisent dans ``utilisateurs.t_roles``."""

    def _appel(self, *, occupant_keycloak=None, occupant_legacy=None, legacy_actif=True):
        from inscriptions.views import _identifiant_deja_pris

        kc = mock.MagicMock()
        kc.find_user_by_username.return_value = occupant_keycloak
        kc.get_user.return_value = {"attributes": {"legacy_id_role": ["42"]}}
        with mock.patch.object(legacy_writer, "is_enabled", return_value=legacy_actif), \
             mock.patch.object(legacy_writer, "find_role_id", return_value=occupant_legacy):
            return _identifiant_deja_pris(kc, "sub-1", "jean.dupont")

    def test_libre_des_deux_cotes(self):
        self.assertEqual(self._appel(), "")

    def test_pris_dans_keycloak(self):
        self.assertIn("déjà utilisé", self._appel(occupant_keycloak="sub-autre"))

    def test_son_propre_identifiant_nest_pas_un_conflit(self):
        self.assertEqual(self._appel(occupant_keycloak="sub-1", occupant_legacy=42), "")

    def test_pris_dans_la_base_historique(self):
        self.assertIn("déjà utilisé", self._appel(occupant_legacy=926))

    def test_sans_identifiant_rien_a_verifier(self):
        from inscriptions.views import _identifiant_deja_pris

        kc = mock.MagicMock()
        self.assertEqual(_identifiant_deja_pris(kc, "sub-1", None), "")
        kc.find_user_by_username.assert_not_called()

class MemorisationTests(TestCase):
    """``/api/me/`` est appelé à chaque chargement de page : l'état de l'identifiant
    ne doit pas coûter un appel Keycloak et une requête SQL à chaque fois."""

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.kc = mock.MagicMock()
        self.kc.get_user.return_value = {
            "username": "paul.lesiak",
            "attributes": {"legacy_id_role": ["42"]},
        }

    def _lire(self):
        with mock.patch.object(legacy_writer, "is_enabled", return_value=True), \
             mock.patch.object(legacy_writer, "get_role_identifiant", return_value="Paul Lesiak"):
            return mirror.legacy_username_state(self.kc, "sub-1")

    def test_second_appel_sert_la_valeur_memorisee(self):
        self.assertEqual(self._lire(), ("Paul Lesiak", True))
        self.assertEqual(self._lire(), ("Paul Lesiak", True))
        self.kc.get_user.assert_called_once()

    def test_oubli_force_une_nouvelle_lecture(self):
        """Après un changement d'identifiant, la réponse doit refléter le nouvel état."""
        self._lire()
        mirror.forget_legacy_username_state("sub-1")
        self._lire()
        self.assertEqual(self.kc.get_user.call_count, 2)

    def test_panne_keycloak_nest_pas_memorisee(self):
        """Mémoriser l'échec masquerait la divergence pendant cinq minutes."""
        self.kc.get_user.side_effect = KeycloakAdminError("get_user_failed:503")
        with mock.patch.object(legacy_writer, "is_enabled", return_value=True):
            self.assertEqual(mirror.legacy_username_state(self.kc, "sub-1"), ("", False))
        self.kc.get_user.side_effect = None
        self.assertEqual(self._lire(), ("Paul Lesiak", True))
