from __future__ import annotations

import logging

from django.conf import settings

from inscriptions.keycloak_client import KeycloakAdminClient, KeycloakAdminError
from inscriptions.models import Notification, Reserve, UserProfile
from inscriptions.services import mail as mail_svc

logger = logging.getLogger(__name__)


def _user_label(profile: UserProfile) -> str:
    full_name = f"{profile.first_name or ''} {profile.last_name or ''}".strip()
    if full_name:
        return f"{full_name} ({profile.email})"
    return profile.email


def _notify_super_admins(title: str, body: str) -> None:
    for admin in UserProfile.objects.filter(is_super_admin=True):
        Notification.objects.create(user=admin, title=title, body=body)


def _referent_group_members(reserve: Reserve) -> list[dict]:
    if not settings.KEYCLOAK_SYNC_ENABLED:
        return []
    root = (getattr(settings, "KEYCLOAK_GROUP_RESERVES", "reserves") or "reserves").strip("/")
    try:
        kc = KeycloakAdminClient()
        group = kc.find_group_by_path(f"/{root}/{reserve.area_code}/referent")
        if not group or not group.get("id"):
            return []
        return kc.list_group_members(group["id"])
    except KeycloakAdminError as exc:
        logger.warning("Impossible de lister les référents de %s: %s", reserve.area_code, exc)
        return []


def _referent_profiles(reserve: Reserve) -> list[UserProfile]:
    subs = [(m.get("id") or "").strip() for m in _referent_group_members(reserve)]
    subs = [s for s in subs if s]
    if not subs:
        return []
    return list(UserProfile.objects.filter(keycloak_sub__in=subs))


def _referent_emails(reserve: Reserve) -> list[str]:
    emails: set[str] = set()
    for member in _referent_group_members(reserve):
        email = (member.get("email") or "").strip().lower()
        if email:
            emails.add(email)
    for profile in _referent_profiles(reserve):
        if (profile.email or "").strip():
            emails.add(profile.email.strip().lower())
    return sorted(emails)


def notify_referent_request_created(applicant: UserProfile, reserve: Reserve) -> None:
    title = f"Demande référent : {reserve.area_code}"
    body = (
        f"{_user_label(applicant)} demande le statut référent "
        f"pour la réserve {reserve.area_name} ({reserve.area_code})."
    )
    _notify_super_admins(title, body)
    mail_svc.send_reserve_referent_request_superadmin_mail(applicant=applicant, reserve=reserve)


def notify_referent_request_decided(
    user: UserProfile,
    reserve: Reserve,
    *,
    approve: bool,
    note: str = "",
) -> None:
    if approve:
        title = f"Référent validé : {reserve.area_name}"
        body = f"Votre demande de statut référent pour {reserve.area_name} a été acceptée."
        mail_svc.send_reserve_referent_approved_user_mail(user=user, reserve=reserve)
    else:
        title = f"Référent refusé : {reserve.area_name}"
        body = f"Votre demande de statut référent pour {reserve.area_name} a été refusée."
        if note.strip():
            body = f"{body} Motif : {note.strip()}"
        mail_svc.send_reserve_referent_rejected_user_mail(user=user, reserve=reserve, note=note)
    Notification.objects.create(user=user, title=title, body=body)


def notify_referents_new_member(member: UserProfile, reserve: Reserve) -> None:
    member_sub = (member.keycloak_sub or "").strip()
    referent_profiles = [
        profile for profile in _referent_profiles(reserve) if profile.keycloak_sub != member_sub
    ]
    referent_emails = _referent_emails(reserve)
    if member_sub:
        referent_emails = [
            email
            for email in referent_emails
            if email.lower() != (member.email or "").strip().lower()
        ]

    if not referent_profiles and not referent_emails:
        return

    title = f"Nouveau membre : {reserve.area_name}"
    body = (
        f"{_user_label(member)} vient de rejoindre la réserve {reserve.area_name} ({reserve.area_code}). "
        "Si cette personne ne devrait pas en faire partie, vous pouvez le signaler depuis l'administration."
    )
    for profile in referent_profiles:
        Notification.objects.create(user=profile, title=title, body=body)

    mail_svc.send_reserve_new_member_referent_mail(
        reserve=reserve,
        member=member,
        recipient_emails=referent_emails,
    )
