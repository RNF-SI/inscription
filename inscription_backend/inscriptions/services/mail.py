from __future__ import annotations

import logging
from email.mime.image import MIMEImage

from django.conf import settings
from django.core.mail import EmailMultiAlternatives

from inscriptions.models import Application, RegistrationRequest, Reserve, UserProfile
from inscriptions.services import email_templates as tpl

logger = logging.getLogger(__name__)


def _attach_logo(message: EmailMultiAlternatives) -> None:
    if not tpl.LOGO_PATH.is_file():
        logger.warning("Logo e-mail introuvable: %s", tpl.LOGO_PATH)
        return
    logo = MIMEImage(tpl.LOGO_PATH.read_bytes(), _subtype="png")
    logo.add_header("Content-ID", f"<{tpl.LOGO_CID}>")
    logo.add_header("Content-Disposition", "inline", filename="embleme.png")
    message.attach(logo)


def send_html_email(
    recipients: list[str],
    subject: str,
    html_body: str,
    text_body: str,
    *,
    attach_logo: bool = True,
) -> None:
    cleaned = [email.strip() for email in recipients if (email or "").strip()]
    if not cleaned:
        return
    message = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=cleaned,
    )
    message.attach_alternative(html_body, "text/html")
    if attach_logo:
        _attach_logo(message)
    try:
        message.send(fail_silently=False)
    except Exception:
        logger.exception("Échec d'envoi e-mail à %s", ", ".join(cleaned))


def notify_superadmins_registration(registration: RegistrationRequest) -> None:
    recipients = settings.SUPERADMIN_NOTIFY_EMAILS
    if not recipients:
        return
    subject, html_body, text_body = tpl.registration_submitted_admin_email(registration)
    send_html_email(recipients, subject, html_body, text_body)


def send_registration_submitted_user_mail(registration: RegistrationRequest) -> None:
    subject, html_body, text_body = tpl.registration_submitted_user_email(registration)
    send_html_email([registration.email], subject, html_body, text_body)


def send_registration_approved_user_mail(registration: RegistrationRequest) -> None:
    subject, html_body, text_body = tpl.registration_approved_user_email(registration)
    send_html_email([registration.email], subject, html_body, text_body)


def send_registration_rejected_user_mail(registration: RegistrationRequest, note: str = "") -> None:
    subject, html_body, text_body = tpl.registration_rejected_user_email(registration, note=note)
    send_html_email([registration.email], subject, html_body, text_body)


def send_app_access_request_admin_mail(
    *,
    admins: list[UserProfile],
    applicant_name: str,
    applicant_email: str,
    application: Application,
    justification: str,
) -> None:
    recipients = sorted({admin.email for admin in admins if (admin.email or "").strip()})
    if not recipients:
        return
    subject, html_body, text_body = tpl.app_access_request_admin_email(
        applicant_name=applicant_name,
        applicant_email=applicant_email,
        application=application,
        justification=justification,
    )
    send_html_email(recipients, subject, html_body, text_body)


def send_app_access_granted_user_mail(*, profile: UserProfile, application: Application) -> None:
    subject, html_body, text_body = tpl.app_access_granted_user_email(
        first_name=profile.first_name or profile.username or "utilisateur",
        application=application,
    )
    send_html_email([profile.email], subject, html_body, text_body)


def send_app_access_rejected_user_mail(*, profile: UserProfile, application: Application, note: str) -> None:
    subject, html_body, text_body = tpl.app_access_rejected_user_email(
        first_name=profile.first_name or profile.username or "utilisateur",
        application=application,
        note=note,
    )
    send_html_email([profile.email], subject, html_body, text_body)


def send_reserve_referent_request_superadmin_mail(*, applicant: UserProfile, reserve: Reserve) -> None:
    recipients = list(settings.SUPERADMIN_NOTIFY_EMAILS or [])
    subject, html_body, text_body = tpl.reserve_referent_request_superadmin_email(
        applicant=applicant,
        reserve=reserve,
    )
    if recipients:
        send_html_email(recipients, subject, html_body, text_body)


def send_reserve_referent_approved_user_mail(*, user: UserProfile, reserve: Reserve) -> None:
    if not (user.email or "").strip():
        return
    subject, html_body, text_body = tpl.reserve_referent_approved_user_email(user=user, reserve=reserve)
    send_html_email([user.email], subject, html_body, text_body)


def send_reserve_referent_rejected_user_mail(*, user: UserProfile, reserve: Reserve, note: str) -> None:
    if not (user.email or "").strip():
        return
    subject, html_body, text_body = tpl.reserve_referent_rejected_user_email(user=user, reserve=reserve, note=note)
    send_html_email([user.email], subject, html_body, text_body)


def send_reserve_new_member_referent_mail(
    *,
    reserve: Reserve,
    member: UserProfile,
    recipient_emails: list[str],
) -> None:
    if not recipient_emails:
        return
    for email in recipient_emails:
        profile = UserProfile.objects.filter(email__iexact=email).first()
        first_name = profile.first_name if profile and profile.first_name else "référent"
        subject, html_body, text_body = tpl.reserve_new_member_referent_email(
            reserve=reserve,
            member=member,
            referent_first_name=first_name,
        )
        send_html_email([email], subject, html_body, text_body)
