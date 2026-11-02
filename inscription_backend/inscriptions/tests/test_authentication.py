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

    def _decode_with(self, claims_by_call):
        """jwt.decode lève InvalidAudienceError au 1er appel (aud=account), puis renvoie claims."""
        with patch("inscriptions.authentication.jwt.decode") as decode:
            decode.side_effect = [jwt.InvalidAudienceError("aud"), claims_by_call]
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
