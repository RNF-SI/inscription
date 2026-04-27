from __future__ import annotations

import logging
from typing import Any, Optional, Tuple

import jwt
from django.conf import settings
from jwt import PyJWKClient
from rest_framework.authentication import BaseAuthentication
from rest_framework.request import Request

from inscriptions.models import UserProfile

logger = logging.getLogger(__name__)


class KeycloakUser:
    is_authenticated = True

    def __init__(self, claims: dict[str, Any], profile: UserProfile | None) -> None:
        self.claims = claims
        self.profile = profile
        self.pk = profile.pk if profile else None

    @property
    def id(self):
        return self.pk


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
        sub = claims.get("sub")
        if not sub:
            return None
        email = claims.get("email") or ""
        profile = UserProfile.objects.filter(keycloak_sub=sub).first()
        if not profile:
            profile = UserProfile.objects.create(
                keycloak_sub=sub,
                email=email or f"{sub}@keycloak.local",
                username=claims.get("preferred_username") or "",
                first_name=claims.get("given_name") or "",
                last_name=claims.get("family_name") or "",
            )
        return KeycloakUser(claims, profile), None

    def _decode(self, token: str) -> dict[str, Any]:
        issuer = f"{settings.KEYCLOAK_BASE_URL}/realms/{settings.KEYCLOAK_REALM}"
        jwks_url = f"{issuer}/protocol/openid-connect/certs"
        jwks_client = PyJWKClient(jwks_url, cache_keys=True)
        signing_key = jwks_client.get_signing_key_from_jwt(token)
        decode_kwargs: dict[str, Any] = {
            "algorithms": ["RS256"],
            "issuer": issuer,
            "options": {"verify_aud": False},
        }
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
        return jwt.decode(token, signing_key.key, **decode_kwargs)


def get_current_sub(request: Request) -> str | None:
    user = getattr(request, "user", None)
    if isinstance(user, KeycloakUser):
        return user.claims.get("sub")
    return None


def require_profile(request: Request) -> UserProfile | None:
    user = getattr(request, "user", None)
    if isinstance(user, KeycloakUser) and user.profile:
        return user.profile
    return None
