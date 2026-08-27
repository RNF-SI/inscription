from __future__ import annotations

import logging
import threading
from typing import Any, Optional, Tuple

import jwt
from django.conf import settings
from jwt import PyJWKClient
from rest_framework.authentication import BaseAuthentication
from rest_framework.request import Request

logger = logging.getLogger(__name__)

# PyJWKClient garde son cache de clés dans l'instance : la recréer à chaque requête
# forçait un appel HTTPS au JWKS Keycloak par requête authentifiée. On garde une
# instance par URL JWKS (l'URL dépend des settings, qui changent entre les tests).
_jwks_clients: dict[str, PyJWKClient] = {}
_jwks_lock = threading.Lock()


def _jwks_client(jwks_url: str) -> PyJWKClient:
    client = _jwks_clients.get(jwks_url)
    if client is None:
        with _jwks_lock:
            client = _jwks_clients.get(jwks_url)
            if client is None:
                client = PyJWKClient(jwks_url, cache_keys=True)
                _jwks_clients[jwks_url] = client
    return client


def reset_jwks_cache() -> None:
    """Vide le cache des clés de signature (changement de realm, tests)."""
    with _jwks_lock:
        _jwks_clients.clear()


class KeycloakUser:
    is_authenticated = True

    def __init__(self, claims: dict[str, Any]) -> None:
        self.claims = claims
        self.sub = (claims.get("sub") or "").strip()

    @property
    def groups(self) -> list[str]:
        raw = self.claims.get("groups") or []
        if not isinstance(raw, list):
            return []
        return [g.strip() for g in raw if isinstance(g, str) and g.strip()]


class KeycloakJWTAuthentication(BaseAuthentication):
    keyword = "Bearer"

    def authenticate(self, request: Request) -> Optional[Tuple[KeycloakUser, None]]:
        auth = request.headers.get("Authorization")
        if not auth or not auth.startswith(self.keyword + " "):
            return None
        token = auth[len(self.keyword) + 1 :].strip()
        if not token:
            return None
        try:
            claims = self._decode(token)
        except Exception as exc:
            logger.info("JWT invalide: %s", exc)
            return None
        if not claims.get("sub"):
            return None
        return KeycloakUser(claims), None

    def _decode(self, token: str) -> dict[str, Any]:
        issuer = f"{settings.KEYCLOAK_BASE_URL}/realms/{settings.KEYCLOAK_REALM}"
        jwks_url = f"{issuer}/protocol/openid-connect/certs"
        signing_key = _jwks_client(jwks_url).get_signing_key_from_jwt(token)
        audience = settings.KEYCLOAK_APP_CLIENT_ID
        if audience:
            try:
                return jwt.decode(
                    token,
                    signing_key.key,
                    algorithms=["RS256"],
                    audience=audience,
                    issuer=issuer,
                )
            except jwt.InvalidAudienceError:
                pass
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            issuer=issuer,
            options={"verify_aud": False},
        )
        # Keycloak met souvent `account` dans `aud` et le client émetteur dans `azp`.
        # Sans ce contrôle, tout token du realm (y compris émis pour un autre client)
        # serait accepté par l'API.
        if audience:
            azp = (claims.get("azp") or "").strip()
            if azp != audience:
                raise jwt.InvalidAudienceError(
                    f"Token émis pour le client {azp or '(azp absent)'}, attendu {audience}"
                )
        return claims


def get_current_sub(request: Request) -> str | None:
    user = getattr(request, "user", None)
    if isinstance(user, KeycloakUser):
        return user.sub or None
    return None


def require_keycloak_user(request: Request) -> KeycloakUser | None:
    user = getattr(request, "user", None)
    if isinstance(user, KeycloakUser) and user.sub:
        return user
    return None
