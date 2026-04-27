from __future__ import annotations

from django.conf import settings
from django.core.mail import send_mail


def notify_superadmins(subject: str, body: str) -> None:
    recipients = settings.SUPERADMIN_NOTIFY_EMAILS
    if not recipients:
        return
    send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, recipients, fail_silently=True)


def send_user_mail(to_email: str, subject: str, body: str) -> None:
    send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [to_email], fail_silently=True)
