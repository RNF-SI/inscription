"""Changement de mot de passe par l'utilisateur lui-même.

C'est le seul chemin autorisé tant que les applications RNF lisent leurs comptes dans
la base historique : la console de compte Keycloak n'écrirait que dans Keycloak, et
l'usager garderait son ancien mot de passe partout ailleurs. Ces tests verrouillent
les refus — un mot de passe mal prouvé ne doit jamais aboutir — et l'ordre des deux
écritures.
"""

from contextlib import contextmanager
from unittest import mock

import bcrypt
from django.test import SimpleTestCase, TestCase, override_settings

from inscriptions.keycloak_client import KeycloakAdminError
from inscriptions.serializers import PasswordChangeSerializer
from inscriptions.services import legacy_writer, mirror


@contextmanager
def fake_legacy(results=None):
    """Connexion « legacy » bouchonnée, comme dans test_legacy_writer."""
    appels = []
    resultats = list(results or [])

    class Cursor:
        def execute(self, sql, params=None):
            appels.append((" ".join(sql.split()), list(params or [])))

        def fetchone(self):
            return resultats.pop(0) if resultats else None

        def fetchall(self):
            return resultats.pop(0) if resultats else []

    cursor = Cursor()

    @contextmanager
    def _cursor():
        yield cursor

    connections = mock.MagicMock()
    connections.databases = {"default": {}, "legacy": {}}
    connections.__getitem__.return_value.cursor = _cursor

    with override_settings(LEGACY_WRITE_ENABLED=True):
        with mock.patch.object(legacy_writer, "connections", connections):
            yield appels


class SerializerTests(SimpleTestCase):
    BASE = {
        "current_password": "AncienMotDePasse1",
        "new_password": "NouveauMotDePasse1",
        "new_password_confirmation": "NouveauMotDePasse1",
    }

    def test_cas_nominal(self):
        self.assertTrue(PasswordChangeSerializer(data=self.BASE).is_valid())

    def test_confirmation_differente(self):
        data = dict(self.BASE, new_password_confirmation="AutreChose123")
        ser = PasswordChangeSerializer(data=data)
        self.assertFalse(ser.is_valid())
        self.assertIn("new_password_confirmation", ser.errors)

    def test_nouveau_identique_a_lancien(self):
        data = dict(self.BASE, new_password="AncienMotDePasse1", new_password_confirmation="AncienMotDePasse1")
        ser = PasswordChangeSerializer(data=data)
        self.assertFalse(ser.is_valid())
        self.assertIn("new_password", ser.errors)

    def test_trop_court(self):
        data = dict(self.BASE, new_password="court", new_password_confirmation="court")
        self.assertFalse(PasswordChangeSerializer(data=data).is_valid())


class VerificationDuMotDePasseTests(TestCase):
    def test_hash_valide(self):
        hashe = bcrypt.hashpw(b"MotDePasseActuel1", bcrypt.gensalt()).decode()
        with fake_legacy(results=[(hashe,)]):
            self.assertTrue(legacy_writer.verify_password(7, "MotDePasseActuel1"))

    def test_mauvais_mot_de_passe(self):
        hashe = bcrypt.hashpw(b"MotDePasseActuel1", bcrypt.gensalt()).decode()
        with fake_legacy(results=[(hashe,)]):
            self.assertFalse(legacy_writer.verify_password(7, "PasLeBon"))

    def test_sans_hash_exploitable_on_refuse(self):
        """Un compte sans bcrypt (md5 seul, ou rien) ne peut pas prouver son mot de
        passe : on refuse plutôt que de laisser passer."""
        for valeur in (None, "", "5f4dcc3b5aa765d61d8327deb882cf99"):
            with fake_legacy(results=[(valeur,)]):
                self.assertFalse(legacy_writer.verify_password(7, "peu importe"))


class ChangementTests(TestCase):
    def _kc(self, federated=False):
        kc = mock.MagicMock()
        kc.is_federated.return_value = federated
        return kc

    def test_refus_compte_federe(self):
        kc = self._kc(federated=True)
        with self.assertRaises(mirror.PasswordChangeRefused) as ctx:
            mirror.change_password(kc, "sub-1", "ancien", "nouveau")
        self.assertEqual(ctx.exception.code, "federated")
        kc.set_user_password.assert_not_called()

    def test_refus_sans_compte_historique(self):
        kc = self._kc()
        with mock.patch.object(mirror, "legacy_id_role_for", return_value=None):
            with self.assertRaises(mirror.PasswordChangeRefused) as ctx:
                mirror.change_password(kc, "sub-1", "ancien", "nouveau")
        self.assertEqual(ctx.exception.code, "no_legacy_account")
        kc.set_user_password.assert_not_called()

    def test_refus_mot_de_passe_actuel_faux(self):
        kc = self._kc()
        with mock.patch.object(mirror, "legacy_id_role_for", return_value=7), \
             mock.patch.object(legacy_writer, "verify_password", return_value=False), \
             mock.patch.object(legacy_writer, "set_password") as ecriture:
            with self.assertRaises(mirror.PasswordChangeRefused) as ctx:
                mirror.change_password(kc, "sub-1", "faux", "nouveau")
        self.assertEqual(ctx.exception.code, "wrong_current")
        ecriture.assert_not_called()
        kc.set_user_password.assert_not_called()

    def test_ecrit_des_deux_cotes_historique_dabord(self):
        kc = self._kc()
        ordre = []
        with mock.patch.object(mirror, "legacy_id_role_for", return_value=7), \
             mock.patch.object(legacy_writer, "verify_password", return_value=True), \
             mock.patch.object(legacy_writer, "set_password",
                               side_effect=lambda *a, **k: ordre.append("historique")):
            kc.set_user_password.side_effect = lambda *a, **k: ordre.append("keycloak")
            mirror.change_password(kc, "sub-1", "ancien", "NouveauMotDePasse1")
        self.assertEqual(ordre, ["historique", "keycloak"])

    def test_echec_keycloak_annule_lecriture_historique(self):
        """PostgreSQL sait annuler, l'API Keycloak non : l'ordre garantit qu'un refus
        de la politique de mot de passe ne laisse pas les deux côtés divergents."""
        kc = self._kc()
        kc.set_user_password.side_effect = KeycloakAdminError("set_password_failed:400", "trop court")
        with mock.patch.object(mirror, "legacy_id_role_for", return_value=7), \
             mock.patch.object(legacy_writer, "verify_password", return_value=True), \
             mock.patch.object(legacy_writer, "set_password"):
            with self.assertRaises(KeycloakAdminError):
                mirror.change_password(kc, "sub-1", "ancien", "NouveauMotDePasse1")
