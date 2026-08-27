from __future__ import annotations

import logging
import uuid
from typing import Iterable

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from inscriptions.crypto_util import decrypt_text
from inscriptions.keycloak_client import KeycloakAdminClient, KeycloakAdminError
from inscriptions.models import (
    AccessRequestItem,
    Application,
    AuditLog,
    RegistrationRequest,
    ReserveReferentRequest,
    Reserve,
)
from inscriptions.roles import list_application_admin_subs, list_application_admins, list_super_admin_subs
from inscriptions.services import mail as mail_svc
from inscriptions.services import provisioning as prov
from inscriptions.services import reserve_notifications as reserve_notify
from inscriptions.services import notifications as notify_svc
from inscriptions.services.user_organisme import enrich_user_organisme
from inscriptions.user_identity import UserInfo, fetch_user_info, user_label

logger = logging.getLogger(__name__)


def _log(actor_sub: str, action: str, payload: dict) -> None:
    AuditLog.objects.create(actor_sub=actor_sub or "", action=action, payload=payload)


def _notify_user_sub(user_sub: str, title: str, body: str, *, admin_tab: str = "") -> None:
    notify_svc.notify_user(user_sub, title, body, admin_tab=admin_tab)


def _notify_app_admins(application: Application, title: str, body: str) -> None:
    for sub in list_application_admin_subs(application):
        _notify_user_sub(sub, title, body, admin_tab=notify_svc.ADMIN_TAB_REQUESTS)


def _notify_super_admins(title: str, body: str, *, admin_tab: str = notify_svc.ADMIN_TAB_REQUESTS) -> None:
    for sub in list_super_admin_subs():
        _notify_user_sub(sub, title, body, admin_tab=admin_tab)


def _cleanup_completed_registration(registration: RegistrationRequest, actor_sub: str = "") -> None:
    public_id = str(registration.public_id)
    email = registration.email
    registration.delete()
    _log(actor_sub, "registration_request_deleted", {"registration": public_id, "email": email})


def _registration_user_info(registration: RegistrationRequest) -> UserInfo:
    sub = (registration.keycloak_user_id or "").strip()
    if sub and settings.KEYCLOAK_SYNC_ENABLED and not sub.startswith("local-"):
        info = fetch_user_info(sub)
        if info:
            if not info.organisme and registration.organisme:
                return UserInfo(
                    sub=info.sub,
                    email=info.email or registration.email,
                    username=info.username or registration.username,
                    first_name=info.first_name or registration.first_name,
                    last_name=info.last_name or registration.last_name,
                    fonction=info.fonction or (registration.remarks or "").strip(),
                    organisme=registration.organisme.nom_organisme,
                )
            return info
    org_name = registration.organisme.nom_organisme if registration.organisme else ""
    return UserInfo(
        sub=sub or f"local-{registration.public_id}",
        email=registration.email,
        username=registration.username,
        first_name=registration.first_name,
        last_name=registration.last_name,
        fonction=(registration.remarks or "").strip(),
        organisme=org_name,
    )


def on_registration_created(registration: RegistrationRequest) -> None:
    mail_svc.send_registration_submitted_user_mail(registration)
    mail_svc.notify_superadmins_registration(registration)
    _notify_super_admins(
        title="Nouvelle demande d'inscription",
        body=(
            f"{user_label(UserInfo(sub='', email=registration.email, username=registration.username, first_name=registration.first_name, last_name=registration.last_name, organisme=registration.organisme.nom_organisme if registration.organisme else ''))} "
            "a soumis une demande d'inscription."
        ),
    )
    _log("", "registration_created", {"public_id": str(registration.public_id), "email": registration.email})


@transaction.atomic
def super_admin_approve(registration: RegistrationRequest, actor_sub: str) -> None:
    if registration.status != RegistrationRequest.STATUS_PENDING_SUPER:
        raise ValueError("invalid_status")
    kc = KeycloakAdminClient()
    plain_password = decrypt_text(registration.password_cipher)
    keycloak_user_id = ""
    if settings.KEYCLOAK_SYNC_ENABLED:
        try:
            keycloak_user_id = kc.create_user(
                username=registration.username,
                email=registration.email,
                first_name=registration.first_name,
                last_name=registration.last_name,
                password=plain_password,
                temporary_password=False,
                require_verify_email=True,
                function_value=(registration.remarks or "").strip(),
            )
            try:
                kc.send_verify_email(keycloak_user_id, client_id=settings.KEYCLOAK_APP_CLIENT_ID)
            except KeycloakAdminError as exc:
                logger.warning("Keycloak send_verify_email failed for %s: %s", keycloak_user_id, exc)
        except KeycloakAdminError as exc:
            logger.exception("Keycloak create_user: %s", exc)
            raise
    else:
        keycloak_user_id = f"local-{registration.public_id}"

    registration.keycloak_user_id = keycloak_user_id
    registration.status = RegistrationRequest.STATUS_PENDING_APPS
    registration.save(update_fields=["keycloak_user_id", "status", "updated_at"])

    if settings.KEYCLOAK_SYNC_ENABLED:
        try:
            prov.provision_user_groups_after_super_approval(kc, keycloak_user_id, registration)
        except KeycloakAdminError:
            logger.exception("Provisioning org/reserve groups failed")

    user_info = _registration_user_info(registration)

    for code in registration.reserve_codes or []:
        r = Reserve.objects.filter(area_code=code).first()
        if r and settings.KEYCLOAK_SYNC_ENABLED:
            reserve_notify.notify_referents_new_member(user_info, r)

    requested_referent_codes: list[str] = []
    champs_addi = registration.champs_addi or {}
    raw_referent = champs_addi.get("reserves_referent")
    if isinstance(raw_referent, list):
        for item in raw_referent:
            code = ""
            if isinstance(item, dict):
                code = str(item.get("id") or "").strip()
            elif isinstance(item, str):
                code = item.strip()
            if code:
                requested_referent_codes.append(code)
    allowed_codes = set(str(c).strip() for c in (registration.reserve_codes or []) if str(c).strip())
    for code in requested_referent_codes:
        if code not in allowed_codes:
            continue
        reserve = Reserve.objects.filter(area_code=code).first()
        if not reserve:
            continue
        _referent_req, created = ReserveReferentRequest.objects.get_or_create(
            user_sub=keycloak_user_id,
            reserve=reserve,
            status=ReserveReferentRequest.STATUS_PENDING,
        )
        if created:
            reserve_notify.notify_referent_request_created(user_info, reserve)

    for item in registration.items.select_related("application"):
        justification = (item.request_justification or "").strip()
        justification_text = justification if justification else "Aucune justification fournie."
        _notify_app_admins(
            item.application,
            title="Nouvelle demande d'accès",
            body=(
                f"{user_label(user_info)} demande l'accès à {item.application.nom}. "
                f"Justification: {justification_text}"
            ),
        )
        mail_svc.send_app_access_request_admin_mail(
            admins=list_application_admins(item.application),
            applicant=user_info,
            application=item.application,
            justification=justification_text,
        )

    mail_svc.send_registration_approved_user_mail(registration)
    _notify_user_sub(
        keycloak_user_id,
        "Inscription validée",
        "Vos demandes d'accès aux applications sont en cours de traitement.",
    )
    _log(actor_sub, "super_admin_approve", {"registration": str(registration.public_id)})

    if not registration.items.filter(origin=AccessRequestItem.ORIGIN_REGISTRATION).exists():
        _cleanup_completed_registration(registration, actor_sub=actor_sub)


@transaction.atomic
def super_admin_reject(registration: RegistrationRequest, actor_sub: str, note: str = "") -> None:
    registration.status = RegistrationRequest.STATUS_SUPER_REJECTED
    registration.save(update_fields=["status", "updated_at"])
    mail_svc.send_registration_rejected_user_mail(registration, note=note)
    _log(actor_sub, "super_admin_reject", {"registration": str(registration.public_id), "note": note})


def _finalize_registration_if_done(registration: RegistrationRequest) -> None:
    items = list(registration.items.filter(origin=AccessRequestItem.ORIGIN_REGISTRATION))
    if not items:
        return
    if any(i.status == AccessRequestItem.STATUS_PENDING for i in items):
        return
    # Pas de save(STATUS_COMPLETED) : la ligne est supprimée juste après, l'écriture
    # ne serait jamais observable. La trace de clôture est dans AuditLog.
    _cleanup_completed_registration(registration)


@transaction.atomic
def app_admin_decide_item(
    item: AccessRequestItem,
    approve: bool,
    actor_sub: str,
    note: str = "",
) -> None:
    note = (note or "").strip()
    if item.origin != AccessRequestItem.ORIGIN_REGISTRATION:
        raise ValueError("invalid_item_origin")
    registration = item.registration
    if not registration or registration.status != RegistrationRequest.STATUS_PENDING_APPS:
        raise ValueError("invalid_registration_state")
    if item.status != AccessRequestItem.STATUS_PENDING:
        raise ValueError("item_already_decided")
    if not approve and not note:
        raise ValueError("missing_rejection_note")

    item.status = AccessRequestItem.STATUS_APPROVED if approve else AccessRequestItem.STATUS_REJECTED
    item.decided_at = timezone.now()
    item.decided_by_sub = actor_sub
    item.decision_note = note
    item.save(update_fields=["status", "decided_at", "decided_by_sub", "decision_note"])

    user_info = _registration_user_info(registration)
    user_sub = (registration.keycloak_user_id or user_info.sub).strip()
    if not user_sub:
        raise ValueError("missing_user_sub")

    if approve:
        kc = KeycloakAdminClient()
        try:
            prov.provision_application_access(kc, user_sub, item.application)
        except KeycloakAdminError as exc:
            logger.exception("provision app group failed")
            raise ValueError("Échec du provisioning Keycloak pour cette application.") from exc
        mail_svc.send_app_access_granted_user_mail(user=user_info, application=item.application)
        _notify_user_sub(user_sub, f"Accès : {item.application.nom}", "Votre demande a été acceptée.")
    else:
        mail_svc.send_app_access_rejected_user_mail(user=user_info, application=item.application, note=note)
        _notify_user_sub(
            user_sub,
            f"Accès : {item.application.nom}",
            f"Votre demande a été refusée. Motif: {note}",
        )

    _log(actor_sub, "app_admin_decide", {"item_id": item.pk, "approve": approve})
    _finalize_registration_if_done(registration)


@transaction.atomic
def create_additional_access_request(user_sub: str, user_info: UserInfo, slugs: Iterable[str], remarks: str) -> uuid.UUID:
    request_public_id = uuid.uuid4()
    justification = (remarks or "").strip()
    created_count = 0
    created_apps: list[Application] = []
    sub = (user_sub or user_info.sub).strip()
    user_info = enrich_user_organisme(user_info)
    for slug in slugs:
        app = Application.objects.filter(slug=slug).first()
        if not app:
            continue
        if not app.requires_access_request:
            continue
        already_pending = AccessRequestItem.objects.filter(
            user_sub=sub,
            registration__isnull=True,
            origin=AccessRequestItem.ORIGIN_ADDITIONAL,
            application=app,
            status=AccessRequestItem.STATUS_PENDING,
        ).exists()
        if already_pending:
            continue
        AccessRequestItem.objects.create(
            user_sub=sub,
            application=app,
            origin=AccessRequestItem.ORIGIN_ADDITIONAL,
            request_public_id=request_public_id,
            request_justification=justification,
        )
        created_count += 1
        created_apps.append(app)
        justification_text = justification or "Aucune justification fournie."
        _notify_app_admins(
            app,
            "Demande d'accès supplémentaire",
            (
                f"{user_label(user_info)} demande l'accès à {app.nom}. "
                f"Justification: {justification_text}"
            ),
        )
        mail_svc.send_app_access_request_admin_mail(
            admins=list_application_admins(app),
            applicant=user_info,
            application=app,
            justification=justification_text,
        )
    if created_count == 0:
        raise ValueError("no_new_access_request")
    for app in created_apps:
        _notify_user_sub(
            sub,
            f"Demande envoyée : {app.nom}",
            f"Votre demande d'accès pour {app.nom} a été transmise aux gestionnaires.",
        )
    _log(sub, "additional_access_request", {"public_id": str(request_public_id)})
    return request_public_id


@transaction.atomic
def app_admin_decide_additional_item(
    item: AccessRequestItem,
    approve: bool,
    actor_sub: str,
    note: str = "",
) -> None:
    note = (note or "").strip()
    if item.origin != AccessRequestItem.ORIGIN_ADDITIONAL:
        raise ValueError("invalid_item_origin")
    if item.status != AccessRequestItem.STATUS_PENDING:
        raise ValueError("item_already_decided")
    if not approve and not note:
        raise ValueError("missing_rejection_note")
    item.status = AccessRequestItem.STATUS_APPROVED if approve else AccessRequestItem.STATUS_REJECTED
    item.decided_at = timezone.now()
    item.decided_by_sub = actor_sub
    item.decision_note = note
    item.save(update_fields=["status", "decided_at", "decided_by_sub", "decision_note"])

    sub = (item.user_sub or "").strip()
    if not sub:
        raise ValueError("missing_user_sub")
    user_info = fetch_user_info(sub) or UserInfo(sub=sub, email="", username=sub, first_name="", last_name="")

    if approve:
        kc = KeycloakAdminClient()
        try:
            prov.provision_application_access(kc, sub, item.application)
        except KeycloakAdminError as exc:
            logger.exception("provision additional app failed")
            raise ValueError("Échec du provisioning Keycloak pour cette application.") from exc
        mail_svc.send_app_access_granted_user_mail(user=user_info, application=item.application)
        _notify_user_sub(sub, f"Accès : {item.application.nom}", "Votre demande a été acceptée.")
    else:
        mail_svc.send_app_access_rejected_user_mail(user=user_info, application=item.application, note=note)
        _notify_user_sub(
            sub,
            f"Accès : {item.application.nom}",
            f"Votre demande a été refusée. Motif: {note}",
        )

    _log(actor_sub, "app_admin_decide_additional", {"item_id": item.pk, "approve": approve})
