"""Parcours « mot de passe oublié », de bout en bout.

Keycloak sait faire ce parcours, mais il n'écrirait que de son côté : l'usager
garderait son ancien mot de passe sur toutes les applications qui lisent encore la
base historique. La plateforme doit donc le porter elle-même, comme le changement de
mot de passe authentifié.

Trois précautions guident ce code :

* **Pas d'énumération de comptes.** La demande répond toujours la même chose, qu'une
  adresse soit connue ou non. Un attaquant ne doit pas pouvoir distinguer les deux.
* **Le jeton n'est pas stocké.** Seule son empreinte SHA-256 l'est : une fuite de la
  table ne permet pas de réinitialiser des comptes.
* **Usage unique et durée limitée.** Les jetons en attente du même compte sont
  invalidés dès qu'une réinitialisation aboutit.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from inscriptions.keycloak_client import KeycloakAdminClient, KeycloakAdminError
from inscriptions.models import AuditLog, PasswordResetToken
from inscriptions.services import mail as mail_svc
from inscriptions.services import mirror

logger = logging.getLogger(__name__)


class PasswordResetError(Exception):
    """Réinitialisation refusée, avec un motif destiné à l'usager."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _ttl() -> timedelta:
    return timedelta(minutes=int(getattr(settings, "PASSWORD_RESET_TTL_MINUTES", 60)))


def request_reset(email: str) -> None:
    """Crée un jeton et envoie le lien, si et seulement si le compte s'y prête.

    Ne lève jamais et ne renvoie rien : l'appelant répond la même chose dans tous les
    cas. Les motifs de non-envoi — adresse inconnue, compte fédéré, absence de
    correspondance historique — sont journalisés côté serveur.
    """
    cleaned = (email or "").strip().lower()
    if not cleaned:
        return

    kc = KeycloakAdminClient()
    try:
        user_sub = kc.find_user_by_email(cleaned)
    except KeycloakAdminError as exc:
        logger.warning("Réinitialisation : Keycloak injoignable pour %s : %s", cleaned, exc)
        return
    if not user_sub:
        logger.info("Réinitialisation demandée pour une adresse inconnue : %s", cleaned)
        return

    try:
        if kc.is_federated(user_sub):
            logger.info("Réinitialisation refusée, compte fédéré : %s", cleaned)
            return
    except KeycloakAdminError as exc:
        logger.warning("Réinitialisation : lecture du compte impossible : %s", exc)
        return

    # Un compte sans correspondance historique ne pourrait pas être mis à jour des
    # deux côtés : mieux vaut ne pas promettre un lien qui échouerait.
    if mirror.legacy_id_role_for(kc, user_sub) is None:
        logger.info("Réinitialisation : aucun compte historique pour %s", cleaned)
        return

    token = secrets.token_urlsafe(32)
    PasswordResetToken.objects.create(
        token_hash=_hash(token),
        user_sub=user_sub,
        email=cleaned,
        expires_at=timezone.now() + _ttl(),
    )
    mail_svc.send_password_reset_mail(email=cleaned, token=token, ttl=_ttl())
    AuditLog.objects.create(actor_sub=user_sub, action="password_reset_requested", payload={})


def confirm_reset(token: str, nouveau: str) -> None:
    """Applique la réinitialisation, puis consomme le jeton.

    Le jeton remplace la connaissance du mot de passe actuel : c'est lui la preuve.
    L'écriture passe par le miroir, donc base historique d'abord puis Keycloak, et un
    refus de la politique de mot de passe du realm annule l'ensemble — jeton compris,
    que l'usager peut donc réessayer.
    """
    entry = PasswordResetToken.objects.filter(token_hash=_hash(token or "")).first()
    if entry is None or not entry.is_usable():
        raise PasswordResetError(
            "invalid_token",
            "Ce lien n'est plus valide. Demandez-en un nouveau.",
        )

    kc = KeycloakAdminClient()
    with transaction.atomic():
        # Marquer avant d'écrire, dans la même transaction : si l'écriture échoue,
        # l'annulation rend le jeton à nouveau utilisable ; si elle réussit, le jeton
        # est consommé sans fenêtre de rejeu.
        entry.used_at = timezone.now()
        entry.save(update_fields=["used_at"])
        PasswordResetToken.objects.filter(user_sub=entry.user_sub, used_at__isnull=True).update(
            used_at=timezone.now()
        )
        mirror.set_password_without_verification(kc, entry.user_sub, nouveau)
        AuditLog.objects.create(
            actor_sub=entry.user_sub, action="password_reset_completed", payload={}
        )
