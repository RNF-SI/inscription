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


class ReinitialisationTests(TestCase):
    """Parcours « mot de passe oublié ».

    Trois propriétés à verrouiller : on ne révèle pas quelles adresses existent, le
    jeton n'est pas stocké en clair, et il ne sert qu'une fois.
    """

    def setUp(self):
        from django.core import mail as django_mail

        django_mail.outbox = []
        self.kc = mock.MagicMock()
        self.kc.is_federated.return_value = False
        self.kc.find_user_by_email.return_value = "sub-1"
        self.patch_kc = mock.patch(
            "inscriptions.services.password_reset.KeycloakAdminClient", return_value=self.kc
        )
        self.patch_kc.start()
        self.addCleanup(self.patch_kc.stop)
        self.patch_role = mock.patch(
            "inscriptions.services.password_reset.mirror.legacy_id_role_for", return_value=7
        )
        self.patch_role.start()
        self.addCleanup(self.patch_role.stop)

    def _demande(self, email="jean@example.org"):
        from inscriptions.services import password_reset

        password_reset.request_reset(email)

    def test_adresse_inconnue_ne_cree_rien(self):
        from inscriptions.models import PasswordResetToken
        from django.core import mail as django_mail

        self.kc.find_user_by_email.return_value = None
        self._demande()
        self.assertEqual(PasswordResetToken.objects.count(), 0)
        self.assertEqual(len(django_mail.outbox), 0)

    def test_compte_federe_ne_cree_rien(self):
        from inscriptions.models import PasswordResetToken

        self.kc.is_federated.return_value = True
        self._demande()
        self.assertEqual(PasswordResetToken.objects.count(), 0)

    def test_sans_compte_historique_ne_cree_rien(self):
        from inscriptions.models import PasswordResetToken

        self.patch_role.stop()
        with mock.patch(
            "inscriptions.services.password_reset.mirror.legacy_id_role_for", return_value=None
        ):
            self._demande()
        self.patch_role.start()
        self.assertEqual(PasswordResetToken.objects.count(), 0)

    def test_jeton_cree_et_mail_envoye_sans_jeton_en_clair_en_base(self):
        from django.core import mail as django_mail
        from inscriptions.models import PasswordResetToken

        self._demande()
        entry = PasswordResetToken.objects.get()
        self.assertEqual(len(django_mail.outbox), 1)
        corps = django_mail.outbox[0].body + str(django_mail.outbox[0].alternatives or "")
        # Le jeton figure dans le lien du mail, jamais en clair dans la table.
        self.assertIn("nouveau-mot-de-passe?token=", corps)
        self.assertEqual(len(entry.token_hash), 64)
        self.assertNotIn(entry.token_hash, corps)

    def _jeton_envoye(self):
        from django.core import mail as django_mail
        import re

        corps = django_mail.outbox[0].body + str(django_mail.outbox[0].alternatives or "")
        return re.search(r"token=([A-Za-z0-9_\-]+)", corps).group(1)

    def test_confirmation_nominale_consomme_le_jeton(self):
        from inscriptions.models import PasswordResetToken
        from inscriptions.services import password_reset

        self._demande()
        jeton = self._jeton_envoye()
        with mock.patch.object(password_reset.mirror, "set_password_without_verification") as ecriture:
            password_reset.confirm_reset(jeton, "NouveauMotDePasse1")
        ecriture.assert_called_once()
        self.assertIsNotNone(PasswordResetToken.objects.get().used_at)

    def test_jeton_rejoue_est_refuse(self):
        from inscriptions.services import password_reset

        self._demande()
        jeton = self._jeton_envoye()
        with mock.patch.object(password_reset.mirror, "set_password_without_verification"):
            password_reset.confirm_reset(jeton, "NouveauMotDePasse1")
        with self.assertRaises(password_reset.PasswordResetError) as ctx:
            password_reset.confirm_reset(jeton, "EncoreUnAutre1")
        self.assertEqual(ctx.exception.code, "invalid_token")

    def test_jeton_expire_est_refuse(self):
        from datetime import timedelta

        from django.utils import timezone

        from inscriptions.models import PasswordResetToken
        from inscriptions.services import password_reset

        self._demande()
        jeton = self._jeton_envoye()
        PasswordResetToken.objects.update(expires_at=timezone.now() - timedelta(minutes=1))
        with self.assertRaises(password_reset.PasswordResetError):
            password_reset.confirm_reset(jeton, "NouveauMotDePasse1")

    def test_jeton_inconnu_est_refuse(self):
        from inscriptions.services import password_reset

        with self.assertRaises(password_reset.PasswordResetError):
            password_reset.confirm_reset("jeton-inexistant", "NouveauMotDePasse1")

    def test_echec_decriture_rend_le_jeton_reutilisable(self):
        """Si l'écriture échoue, l'usager doit pouvoir réessayer avec le même lien."""
        from inscriptions.models import PasswordResetToken
        from inscriptions.services import password_reset

        self._demande()
        jeton = self._jeton_envoye()
        with mock.patch.object(
            password_reset.mirror, "set_password_without_verification",
            side_effect=KeycloakAdminError("set_password_failed:400", "trop court"),
        ):
            with self.assertRaises(KeycloakAdminError):
                password_reset.confirm_reset(jeton, "court")
        self.assertIsNone(PasswordResetToken.objects.get().used_at)
