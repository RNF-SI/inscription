from __future__ import annotations

import logging

from django.conf import settings

from inscriptions.keycloak_client import KeycloakAdminClient, KeycloakAdminError
from inscriptions.models import Notification, Reserve
from inscriptions.roles import list_super_admin_subs
from inscriptions.services import mail as mail_svc
from inscriptions.user_identity import UserInfo, user_label

logger = logging.getLogger(__name__)


def _notify_super_admins(title: str, body: str) -> None:
    for sub in list_super_admin_subs():
        Notification.objects.create(user_sub=sub, title=title, body=body)


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


def _referent_subs(reserve: Reserve) -> list[str]:
    subs = [(m.get("id") or "").strip() for m in _referent_group_members(reserve)]
    return [s for s in subs if s]


def _referent_emails(reserve: Reserve) -> list[str]:
    emails: set[str] = set()
    for member in _referent_group_members(reserve):
        email = (member.get("email") or "").strip().lower()
        if email:
            emails.add(email)
    return sorted(emails)


def _referent_first_names(reserve: Reserve) -> dict[str, str]:
    out: dict[str, str] = {}
    for member in _referent_group_members(reserve):
        email = (member.get("email") or "").strip().lower()
        if not email:
            continue
        first_name = (member.get("firstName") or "").strip() or "référent"
        out[email] = first_name
    return out


def notify_referent_request_created(applicant: UserInfo, reserve: Reserve) -> None:
    title = f"Demande référent : {reserve.area_code}"
    body = (
        f"{user_label(applicant)} demande le statut référent "
        f"pour la réserve {reserve.area_name} ({reserve.area_code})."
    )
    _notify_super_admins(title, body)
    mail_svc.send_reserve_referent_request_superadmin_mail(applicant=applicant, reserve=reserve)


def notify_referent_request_decided(
    user: UserInfo,
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
    Notification.objects.create(user_sub=user.sub, title=title, body=body)


def notify_referents_new_member(member: UserInfo, reserve: Reserve) -> None:
    member_sub = (member.sub or "").strip()
    referent_subs = [sub for sub in _referent_subs(reserve) if sub != member_sub]
    referent_emails = _referent_emails(reserve)
    if member.email:
        referent_emails = [email for email in referent_emails if email != member.email.strip().lower()]

    if not referent_subs and not referent_emails:
        return

    title = f"Nouveau membre : {reserve.area_name}"
    body = (
        f"{user_label(member)} vient de rejoindre la réserve {reserve.area_name} ({reserve.area_code}). "
        "Si cette personne ne devrait pas en faire partie, vous pouvez le signaler depuis l'administration."
    )
    for sub in referent_subs:
        Notification.objects.create(user_sub=sub, title=title, body=body)

    mail_svc.send_reserve_new_member_referent_mail(
        reserve=reserve,
        member=member,
        recipient_emails=referent_emails,
        recipient_first_names=_referent_first_names(reserve),
    )
