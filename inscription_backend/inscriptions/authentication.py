from __future__ import annotations

import logging
import threading
import time
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


# Tolérance d'écart d'horloge entre Keycloak et ce serveur, en secondes.
#
# Sans elle, PyJWT n'accorde aucune marge : `_validate_iat` lève
# ImmatureSignatureError dès que `iat > now`. Une seule seconde d'avance de
# Keycloak sur Django refuse donc *tous* les jetons, de tout le monde, avec un
# message qui ne désigne jamais l'horloge — c'est ce qui a transformé une dérive
# en panne totale le 2026-11-02 (runbook § 0.1 et § 0.8). La RFC 7519 § 4.1.4
# prévoit justement cette marge, « usually no more than a few minutes ».
#
# 60 s est l'arbitrage délibéré repris de RADIS, qui valide les mêmes jetons
# (`backend/utils/keycloak_auth.py`) : la dérive ordinaire est absorbée, mais pas
# un décrochage de plusieurs minutes — les 4 min 06 s du serveur RADIS ce jour-là
# restent refusées, donc visibles, et font chercher l'horloge. Le leeway n'est pas
# un substitut à NTP : il remplace une falaise par une pente, rien de plus.
#
# Effet de bord accepté : PyJWT applique le même leeway à toutes les dates et ne
# permet pas de régler `iat` et `exp` séparément. Un jeton reste donc accepté 60 s
# après son `exp`, autant de vie effective en plus.
DEFAULT_KEYCLOAK_LEEWAY = 60

# Les deux refus qui dénoncent l'horloge et non le jeton : `iat`/`nbf` dans le
# futur (serveur en retard), `exp` dépassé (serveur en avance, ou jeton périmé).
_ERREURS_HORLOGE = (jwt.ImmatureSignatureError, jwt.ExpiredSignatureError)


def get_keycloak_leeway() -> int:
    """Tolérance d'horloge en secondes, lue dans les settings.

    Une valeur illisible ou négative ne doit pas priver la validation de sa
    tolérance ni faire échouer chaque requête : on retombe sur le défaut.
    """
    try:
        return max(0, int(getattr(settings, "KEYCLOAK_LEEWAY", DEFAULT_KEYCLOAK_LEEWAY)))
    except (TypeError, ValueError):
        return DEFAULT_KEYCLOAK_LEEWAY


def decrire_decalage_horloge(token: str) -> str | None:
    """Écart entre l'horloge locale et les dates du jeton, pour les logs.

    Un serveur en retard voit l'`iat` de chaque jeton dans le futur et les refuse
    tous, quel que soit le compte : « iat +246 s » dans le log dit aussitôt qu'il
    faut regarder l'horloge et non Keycloak. La signature n'est pas vérifiée — on
    ne lit ces dates que pour décrire un refus déjà prononcé.
    """
    try:
        claims = jwt.decode(token, options={"verify_signature": False})
    except Exception:
        return None

    maintenant = int(time.time())
    ecarts = [
        f"{claim} {int(claims[claim]) - maintenant:+d} s"
        for claim in ("iat", "nbf", "exp")
        if isinstance(claims.get(claim), (int, float))
    ]
    return ", ".join(ecarts) or None


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
            self._journaliser_refus(token, exc)
            return None
        if not claims.get("sub"):
            return None
        return KeycloakUser(claims), None

    def _decode(self, token: str) -> dict[str, Any]:
        issuer = f"{settings.KEYCLOAK_BASE_URL}/realms/{settings.KEYCLOAK_REALM}"
        jwks_url = f"{issuer}/protocol/openid-connect/certs"
        signing_key = _jwks_client(jwks_url).get_signing_key_from_jwt(token)
        audience = settings.KEYCLOAK_APP_CLIENT_ID
        leeway = get_keycloak_leeway()
        if audience:
            try:
                return jwt.decode(
                    token,
                    signing_key.key,
                    algorithms=["RS256"],
                    audience=audience,
                    issuer=issuer,
                    leeway=leeway,
                )
            except jwt.InvalidAudienceError:
                pass
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            issuer=issuer,
            leeway=leeway,
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

    @staticmethod
    def _journaliser_refus(token: str, exc: Exception) -> None:
        """Journalise un refus, en nommant l'écart d'horloge quand c'est lui.

        « JWT invalide: The token is not yet valid (iat) » ne distingue pas un
        jeton forgé d'un serveur désynchronisé ; l'écart mesuré, lui, le dit, et
        c'est précisément ce qui manquait pendant l'incident.
        """
        if isinstance(exc, _ERREURS_HORLOGE):
            logger.warning(
                "JWT refusé pour cause d'horloge (%s) — tolérance %s s, écart mesuré : %s. "
                "Vérifier la synchronisation NTP de ce serveur et de Keycloak.",
                exc,
                get_keycloak_leeway(),
                decrire_decalage_horloge(token) or "indéterminé",
            )
            return
        logger.info("JWT invalide: %s", exc)


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
