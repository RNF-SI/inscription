"""Validation du JWT Keycloak : contrôle du client émetteur et cache JWKS."""

from unittest.mock import MagicMock, patch

import jwt
from django.test import SimpleTestCase, override_settings

from inscriptions.authentication import (
    KeycloakJWTAuthentication,
    _jwks_client,
    reset_jwks_cache,
)

ISSUER = "https://kc.test/realms/test-realm"


def _signing_key():
    key = MagicMock()
    key.key = "clef-de-signature"
    return key


@override_settings(
    KEYCLOAK_BASE_URL="https://kc.test",
    KEYCLOAK_REALM="test-realm",
    KEYCLOAK_APP_CLIENT_ID="inscription-spa",
)
class DecodeAudienceTests(SimpleTestCase):
    def setUp(self):
        reset_jwks_cache()
        self.addCleanup(reset_jwks_cache)
        patcher = patch("inscriptions.authentication._jwks_client")
        self.jwks = patcher.start()
        self.addCleanup(patcher.stop)
        self.jwks.return_value.get_signing_key_from_jwt.return_value = _signing_key()

    def _decode_with(self, claims_by_call, premiere_erreur=None):
        """jwt.decode échoue au 1er appel (audience refusée), puis renvoie claims."""
        with patch("inscriptions.authentication.jwt.decode") as decode:
            decode.side_effect = [
                premiere_erreur or jwt.InvalidAudienceError("aud"),
                claims_by_call,
            ]
            return KeycloakJWTAuthentication()._decode("jeton")

    def test_accepts_token_whose_azp_matches_the_spa_client(self):
        claims = self._decode_with({"sub": "u1", "azp": "inscription-spa", "aud": "account"})
        self.assertEqual(claims["sub"], "u1")

    def test_rejects_token_issued_for_another_client_of_the_realm(self):
        with self.assertRaises(jwt.InvalidAudienceError):
            self._decode_with({"sub": "u1", "azp": "un-autre-client", "aud": "account"})

    def test_rejects_token_without_azp(self):
        with self.assertRaises(jwt.InvalidAudienceError):
            self._decode_with({"sub": "u1", "aud": "account"})

    def test_accepte_un_jeton_sans_aucune_audience(self):
        """Keycloak n'émet pas d'``aud`` quand le compte n'a aucun rôle sur un autre
        client — le cas des comptes créés par ``partialImport``, qui ne reçoivent pas
        ``default-roles-<realm>``.

        Constaté à la bascule du 2026-11-03 : les 943 comptes repris étaient refusés
        en 403 sur /api/me/ avec « Token is missing the "aud" claim », tandis que les
        comptes d'annuaire passaient. PyJWT lève alors ``MissingRequiredClaimError``,
        qui n'est pas une sous-classe d'``InvalidAudienceError`` : le repli sur ``azp``
        n'était jamais atteint.
        """
        claims = self._decode_with(
            {"sub": "u1", "azp": "inscription-spa"},
            premiere_erreur=jwt.MissingRequiredClaimError("aud"),
        )
        self.assertEqual(claims["sub"], "u1")

    def test_un_jeton_sans_aud_reste_refuse_si_azp_ne_correspond_pas(self):
        """Le repli ne doit pas ouvrir l'API aux jetons des autres clients du realm."""
        with self.assertRaises(jwt.InvalidAudienceError):
            self._decode_with(
                {"sub": "u1", "azp": "un-autre-client"},
                premiere_erreur=jwt.MissingRequiredClaimError("aud"),
            )

    def test_une_autre_revendication_manquante_reste_une_erreur(self):
        """Seule l'absence d'``aud`` autorise le repli : tout autre manque remonte."""
        with self.assertRaises(jwt.MissingRequiredClaimError):
            self._decode_with(
                {"sub": "u1", "azp": "inscription-spa"},
                premiere_erreur=jwt.MissingRequiredClaimError("iss"),
            )

    def test_authenticate_returns_none_when_client_mismatches(self):
        """Le refus doit se traduire par un 401, pas par une 500."""
        request = MagicMock()
        request.headers = {"Authorization": "Bearer jeton"}
        with patch("inscriptions.authentication.jwt.decode") as decode:
            decode.side_effect = [
                jwt.InvalidAudienceError("aud"),
                {"sub": "u1", "azp": "un-autre-client"},
            ]
            self.assertIsNone(KeycloakJWTAuthentication().authenticate(request))


class JwksCacheTests(SimpleTestCase):
    def test_jwks_client_is_reused_across_requests(self):
        reset_jwks_cache()
        self.addCleanup(reset_jwks_cache)
        with patch("inscriptions.authentication.PyJWKClient") as cls:
            first = _jwks_client("https://kc.test/certs")
            second = _jwks_client("https://kc.test/certs")
        self.assertIs(first, second)
        # Une seule construction = un seul téléchargement du JWKS, pas un par requête.
        cls.assert_called_once()

    def test_distinct_realms_get_distinct_clients(self):
        reset_jwks_cache()
        self.addCleanup(reset_jwks_cache)
        with patch("inscriptions.authentication.PyJWKClient") as cls:
            cls.side_effect = lambda url, **kw: MagicMock(name=url)
            a = _jwks_client("https://kc.test/realms/a/certs")
            b = _jwks_client("https://kc.test/realms/b/certs")
            again = _jwks_client("https://kc.test/realms/a/certs")
        self.assertIsNot(a, b)
        self.assertIs(a, again)
