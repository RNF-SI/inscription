"""Formulaire de contact mutualisé entre les applications RNF (sous-module home-rnf).

Chaque application déclare dans sa configuration front l'URL de cette route et
l'adresse support visée (boîte Zammad). Le backend n'accepte que les adresses
présentes dans CONTACT_ALLOWED_RECIPIENTS : sans ce garde-fou, la route serait
un relais SMTP ouvert utilisable pour envoyer du courrier depuis le domaine RNF.
"""

from __future__ import annotations

import logging

from django.conf import settings

from inscriptions.services import email_templates as tpl
from inscriptions.services.mail import send_html_email

logger = logging.getLogger(__name__)


class ContactError(Exception):
    """Erreur fonctionnelle du formulaire de contact (code exploitable par la vue)."""

    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(detail)


def allowed_recipients() -> list[str]:
    return list(getattr(settings, "CONTACT_ALLOWED_RECIPIENTS", []) or [])


def is_enabled() -> bool:
    return bool(allowed_recipients())


def resolve_recipient(requested: str = "") -> str:
    """Adresse de destination effective : celle demandée si elle est autorisée,
    sinon la première de la liste blanche quand le client n'en impose aucune."""
    allowed = allowed_recipients()
    if not allowed:
        raise ContactError("contact_disabled", "Le formulaire de contact n'est pas configuré.")
    requested = (requested or "").strip().lower()
    if not requested:
        return allowed[0]
    if requested not in allowed:
        logger.warning("Destinataire de contact refusé: %s", requested)
        raise ContactError("recipient_not_allowed", "Destinataire non autorisé.")
    return requested


def send_contact_message(
    *,
    app_name: str,
    sender_email: str,
    sender_name: str = "",
    subject: str,
    message: str,
    recipient: str = "",
    context_rows: list[tuple[str, str]] | None = None,
) -> str:
    """Envoie le message au support. Renvoie l'adresse réellement utilisée."""
    to = resolve_recipient(recipient)
    mail_subject, html_body, text_body = tpl.contact_message_email(
        app_name=app_name,
        sender_name=sender_name,
        sender_email=sender_email,
        subject=subject,
        message=message,
        context_rows=context_rows,
    )
    try:
        send_html_email(
            [to],
            mail_subject,
            html_body,
            text_body,
            # Zammad crée le ticket depuis l'expéditeur SMTP (le domaine RNF) :
            # le Reply-To garantit que la réponse du support part vers l'usager.
            reply_to=sender_email,
            raise_on_error=True,
        )
    except Exception as exc:  # SMTP indisponible, refus du relais…
        raise ContactError("mail_send_failed", "L'envoi du message a échoué.") from exc
    return to
