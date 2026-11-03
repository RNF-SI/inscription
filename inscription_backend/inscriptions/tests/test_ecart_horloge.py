"""Tolérance d'écart d'horloge à la validation des jetons.

Le 2 novembre 2026, les VM de l'infrastructure ne joignaient aucun serveur de
temps : Keycloak retardait de 6,4 s et le serveur de production de RADIS de
4 min 06 s. PyJWT n'ayant aucune tolérance, l'`iat` de chaque jeton tombait dans
le futur et *tous* les jetons étaient refusés, pour tout le monde, sans que le
message ne désigne jamais l'horloge. Une tolérance de 60 s absorbe la dérive
ordinaire, mais pas ce genre de décrochage, qui doit rester visible.

La suite est hermétique : la paire de clés et les jetons sont fabriqués ici, le
JWKS est bouchonné, aucun appel réseau ne part.
"""

import time
from unittest.mock import MagicMock, patch

import jwt as pyjwt
from django.test import SimpleTestCase, override_settings

from inscriptions.authentication import (
    DEFAULT_KEYCLOAK_LEEWAY,
    KeycloakJWTAuthentication,
    decrire_decalage_horloge,
    get_keycloak_leeway,
    reset_jwks_cache,
)

ISSUER = "https://kc.test/realms/test-realm"


def _paire_de_cles():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    cle = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    privee = cle.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    return privee, cle.public_key()


@override_settings(
    KEYCLOAK_BASE_URL="https://kc.test",
    KEYCLOAK_REALM="test-realm",
    KEYCLOAK_APP_CLIENT_ID="inscription-spa",
)
class EcartHorlogeTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Une seule génération de clé RSA pour toute la classe : c'est le seul
        # calcul coûteux de ce fichier.
        cls.privee, cls.publique = _paire_de_cles()

    def setUp(self):
        reset_jwks_cache()
        self.addCleanup(reset_jwks_cache)
        patcher = patch("inscriptions.authentication._jwks_client")
        jwks = patcher.start()
        self.addCleanup(patcher.stop)
        clef = MagicMock()
        clef.key = self.publique
        jwks.return_value.get_signing_key_from_jwt.return_value = clef

    def _jeton(self, decalage):
        """Jeton tel que l'émettrait un Keycloak en avance de `decalage` secondes."""
        maintenant = int(time.time())
        return pyjwt.encode(
            {
                "iss": ISSUER,
                "sub": "utilisateur-test",
                "azp": "inscription-spa",
                # Keycloak met `account` dans `aud` : le décodage passe par le
                # second appel, celui qui vérifie `azp`. Les deux doivent porter
                # le leeway.
                "aud": "account",
                "iat": maintenant + decalage,
                "exp": maintenant + decalage + 300,
                "preferred_username": "test",
            },
            self.privee,
            algorithm="RS256",
        )

    def _decoder(self, decalage):
        return KeycloakJWTAuthentication()._decode(self._jeton(decalage))

    def test_jeton_fraichement_emis_accepte(self):
        self.assertEqual(self._decoder(0)["sub"], "utilisateur-test")

    def test_derive_ordinaire_absorbee(self):
        """30 s d'avance de Keycloak ne doivent plus bloquer personne."""
        self.assertEqual(self._decoder(30)["sub"], "utilisateur-test")

    def test_decrochage_de_quatre_minutes_refuse(self):
        """Les 4 min 06 s de l'incident restent refusées : le leeway ne remplace pas NTP."""
        with self.assertRaises(pyjwt.ImmatureSignatureError):
            self._decoder(246)

    @override_settings(KEYCLOAK_LEEWAY=300)
    def test_leeway_configurable(self):
        self.assertEqual(self._decoder(246)["sub"], "utilisateur-test")

    def test_jeton_perime_refuse(self):
        """Le leeway prolonge `exp`, il ne le supprime pas."""
        maintenant = int(time.time())
        jeton = pyjwt.encode(
            {
                "iss": ISSUER,
                "sub": "utilisateur-test",
                "azp": "inscription-spa",
                "aud": "account",
                "iat": maintenant - 600,
                "exp": maintenant - 300,
            },
            self.privee,
            algorithm="RS256",
        )
        with self.assertRaises(pyjwt.ExpiredSignatureError):
            KeycloakJWTAuthentication()._decode(jeton)

    def test_le_refus_pour_cause_d_horloge_nomme_l_ecart(self):
        """Ce qui manquait pendant l'incident : un log qui désigne l'horloge."""
        requete = MagicMock()
        requete.headers = {"Authorization": f"Bearer {self._jeton(246)}"}
        with self.assertLogs("inscriptions.authentication", level="WARNING") as logs:
            self.assertIsNone(KeycloakJWTAuthentication().authenticate(requete))
        message = logs.output[0]
        self.assertIn("horloge", message)
        self.assertIn("iat +24", message)
        self.assertIn("exp +5", message)
        self.assertIn("60", message)

    def test_un_jeton_invalide_pour_une_autre_raison_reste_en_info(self):
        """Pas d'alerte horloge pour un jeton simplement illisible."""
        requete = MagicMock()
        requete.headers = {"Authorization": "Bearer pas-un-jwt"}
        with self.assertLogs("inscriptions.authentication", level="INFO") as logs:
            self.assertIsNone(KeycloakJWTAuthentication().authenticate(requete))
        self.assertIn("JWT invalide", logs.output[0])
        self.assertNotIn("horloge", logs.output[0])


class LeewayEtDiagnosticTests(SimpleTestCase):
    def test_defaut_de_soixante_secondes(self):
        """Même réglage que RADIS, qui valide les mêmes jetons."""
        self.assertEqual(DEFAULT_KEYCLOAK_LEEWAY, 60)

    def test_le_defaut_des_settings_suit_celui_du_module(self):
        from django.conf import settings

        self.assertEqual(int(settings.KEYCLOAK_LEEWAY), DEFAULT_KEYCLOAK_LEEWAY)

    def test_valeurs_lues_depuis_les_settings(self):
        cas = [(0, 0), ("120", 120), (-5, 0), ("zero", DEFAULT_KEYCLOAK_LEEWAY), (None, DEFAULT_KEYCLOAK_LEEWAY)]
        for valeur, attendu in cas:
            with self.subTest(valeur=valeur), override_settings(KEYCLOAK_LEEWAY=valeur):
                self.assertEqual(get_keycloak_leeway(), attendu)

    def test_decalage_mesure_et_nomme(self):
        maintenant = int(time.time())
        jeton = pyjwt.encode({"iat": maintenant + 246, "exp": maintenant + 546}, "secret-hmac-de-test-suffisamment-long")
        description = decrire_decalage_horloge(jeton)
        self.assertIn("iat +24", description)
        self.assertIn("exp +5", description)

    def test_decalage_sur_jeton_illisible(self):
        self.assertIsNone(decrire_decalage_horloge("pas-un-jwt"))

    def test_decalage_sans_date_exploitable(self):
        jeton = pyjwt.encode({"sub": "u1"}, "secret-hmac-de-test-suffisamment-long")
        self.assertIsNone(decrire_decalage_horloge(jeton))
