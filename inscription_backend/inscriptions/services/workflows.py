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
    ApplicationAdmin,
    AuditLog,
    Notification,
    RegistrationRequest,
    UserProfile,
    UserReserveLink,
)
from inscriptions.services import mail as mail_svc
from inscriptions.services import provisioning as prov

logger = logging.getLogger(__name__)


def _log(actor_sub: str, action: str, payload: dict) -> None:
    AuditLog.objects.create(actor_sub=actor_sub or "", action=action, payload=payload)


def _notify_user(profile: UserProfile, title: str, body: str) -> None:
    Notification.objects.create(user=profile, title=title, body=body)


def _notify_app_admins(application: Application, title: str, body: str) -> None:
    admins = ApplicationAdmin.objects.filter(application=application).select_related("user")
    for a in admins:
        _notify_user(a.user, title, body)


def _cleanup_completed_registration(registration: RegistrationRequest, actor_sub: str = "") -> None:
    public_id = str(registration.public_id)
    email = registration.email
    registration.delete()
    _log(actor_sub, "registration_request_deleted", {"registration": public_id, "email": email})


def on_registration_created(registration: RegistrationRequest) -> None:
    mail_svc.notify_superadmins(
        subject="Nouvelle demande d'inscription",
        body=f"Demande {registration.public_id} — {registration.email} — {registration.first_name} {registration.last_name}",
    )
    _log("", "registration_created", {"public_id": str(registration.public_id), "email": registration.email})


@transaction.atomic
def super_admin_approve(registration: RegistrationRequest, actor: UserProfile, actor_sub: str) -> None:
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
                temporary_password=True,
            )
        except KeycloakAdminError as exc:
            logger.exception("Keycloak create_user: %s", exc)
            raise
    else:
        keycloak_user_id = f"local-{registration.public_id}"

    profile, _ = UserProfile.objects.get_or_create(
        keycloak_sub=keycloak_user_id,
        defaults={
            "email": registration.email,
            "username": registration.username,
            "first_name": registration.first_name,
            "last_name": registration.last_name,
            "organisme": registration.organisme,
        },
    )
    profile.email = registration.email
    profile.username = registration.username
    profile.first_name = registration.first_name
    profile.last_name = registration.last_name
    profile.organisme = registration.organisme
    profile.save()

    registration.keycloak_user_id = keycloak_user_id
    registration.created_profile = profile
    registration.status = RegistrationRequest.STATUS_PENDING_APPS
    registration.save(update_fields=["keycloak_user_id", "created_profile", "status", "updated_at"])

    if settings.KEYCLOAK_SYNC_ENABLED:
        try:
            prov.provision_user_groups_after_super_approval(kc, keycloak_user_id, registration)
        except KeycloakAdminError:
            logger.exception("Provisioning org/reserve groups failed")

    for code in registration.reserve_codes or []:
        from inscriptions.models import Reserve

        r = Reserve.objects.filter(area_code=code).first()
        if r:
            UserReserveLink.objects.get_or_create(user=profile, reserve=r)

    for item in registration.items.select_related("application"):
        _notify_app_admins(
            item.application,
            title="Nouvelle demande d'accès",
            body=f"{registration.first_name} {registration.last_name} ({registration.email}) demande l'accès à {item.application.nom}.",
        )

    mail_svc.send_user_mail(
        registration.email,
        "Votre demande a été acceptée (étape 1)",
        "Un administrateur a validé votre inscription. Les gestionnaires des applications vont traiter vos accès.",
    )
    _notify_user(profile, "Inscription validée", "Vos demandes d'accès aux applications sont en cours de traitement.")
    _log(actor_sub, "super_admin_approve", {"registration": str(registration.public_id)})

    # Si aucune application ne nécessite de validation, la demande temporaire est déjà terminée.
    if not registration.items.filter(origin=AccessRequestItem.ORIGIN_REGISTRATION).exists():
        _cleanup_completed_registration(registration, actor_sub=actor_sub)


@transaction.atomic
def super_admin_reject(registration: RegistrationRequest, actor_sub: str, note: str = "") -> None:
    registration.status = RegistrationRequest.STATUS_SUPER_REJECTED
    registration.save(update_fields=["status", "updated_at"])
    mail_svc.send_user_mail(
        registration.email,
        "Demande d'inscription",
        "Votre demande n'a pas été retenue à ce stade.",
    )
    _log(actor_sub, "super_admin_reject", {"registration": str(registration.public_id), "note": note})


def _finalize_registration_if_done(registration: RegistrationRequest) -> None:
    items = list(registration.items.filter(origin=AccessRequestItem.ORIGIN_REGISTRATION))
    if not items:
        return
    if any(i.status == AccessRequestItem.STATUS_PENDING for i in items):
        return
    registration.status = RegistrationRequest.STATUS_COMPLETED
    registration.save(update_fields=["status", "updated_at"])
    if registration.created_profile:
        _notify_user(
            registration.created_profile,
            "Traitement terminé",
            "Toutes vos demandes d'accès aux applications ont reçu une réponse.",
        )
    _cleanup_completed_registration(registration)


@transaction.atomic
def app_admin_decide_item(
    item: AccessRequestItem,
    approve: bool,
    actor: UserProfile,
    actor_sub: str,
    note: str = "",
) -> None:
    if item.origin != AccessRequestItem.ORIGIN_REGISTRATION:
        raise ValueError("invalid_item_origin")
    registration = item.registration
    if not registration or registration.status != RegistrationRequest.STATUS_PENDING_APPS:
        raise ValueError("invalid_registration_state")
    if item.status != AccessRequestItem.STATUS_PENDING:
        raise ValueError("item_already_decided")

    item.status = AccessRequestItem.STATUS_APPROVED if approve else AccessRequestItem.STATUS_REJECTED
    item.decided_at = timezone.now()
    item.decided_by = actor
    item.decision_note = note
    item.save(update_fields=["status", "decided_at", "decided_by", "decision_note"])

    profile = registration.created_profile
    if not profile:
        raise ValueError("missing_profile")

    if approve:
        kc = KeycloakAdminClient()
        try:
            prov.provision_application_access(kc, registration.keycloak_user_id, item.application)
        except KeycloakAdminError as exc:
            logger.exception("provision app group failed")
            raise ValueError("Échec du provisioning Keycloak pour cette application.") from exc
        mail_svc.send_user_mail(
            profile.email,
            f"Accès à {item.application.nom}",
            "Votre accès a été accordé.",
        )
        _notify_user(profile, f"Accès : {item.application.nom}", "Votre demande a été acceptée.")
    else:
        mail_svc.send_user_mail(
            profile.email,
            f"Accès à {item.application.nom}",
            "Votre demande d'accès n'a pas été acceptée.",
        )
        _notify_user(profile, f"Accès : {item.application.nom}", "Votre demande a été refusée.")

    _log(actor_sub, "app_admin_decide", {"item_id": item.pk, "approve": approve})
    _finalize_registration_if_done(registration)


@transaction.atomic
def create_additional_access_request(profile: UserProfile, slugs: Iterable[str], remarks: str) -> uuid.UUID:
    request_public_id = uuid.uuid4()
    justification = (remarks or "").strip()
    created_count = 0
    for slug in slugs:
        app = Application.objects.filter(slug=slug).first()
        if not app:
            continue
        if not app.requires_access_request:
            continue
        already_pending = AccessRequestItem.objects.filter(
            user=profile,
            registration__isnull=True,
            origin=AccessRequestItem.ORIGIN_ADDITIONAL,
            application=app,
            status=AccessRequestItem.STATUS_PENDING,
        ).exists()
        if already_pending:
            continue
        AccessRequestItem.objects.create(
            user=profile,
            application=app,
            origin=AccessRequestItem.ORIGIN_ADDITIONAL,
            request_public_id=request_public_id,
            request_justification=justification,
        )
        created_count += 1
        _notify_app_admins(
            app,
            "Demande d'accès supplémentaire",
            f"{profile.first_name} {profile.last_name} ({profile.email}) demande l'accès à {app.nom}.",
        )
    if created_count == 0:
        raise ValueError("no_new_access_request")
    _notify_user(profile, "Demande envoyée", "Vos demandes d'accès ont été transmises aux gestionnaires.")
    _log(profile.keycloak_sub, "additional_access_request", {"public_id": str(request_public_id)})
    return request_public_id


@transaction.atomic
def app_admin_decide_additional_item(
    item: AccessRequestItem,
    approve: bool,
    actor: UserProfile,
    actor_sub: str,
    note: str = "",
) -> None:
    if item.origin != AccessRequestItem.ORIGIN_ADDITIONAL:
        raise ValueError("invalid_item_origin")
    if item.status != AccessRequestItem.STATUS_PENDING:
        raise ValueError("item_already_decided")
    item.status = AccessRequestItem.STATUS_APPROVED if approve else AccessRequestItem.STATUS_REJECTED
    item.decided_at = timezone.now()
    item.decided_by = actor
    item.decision_note = note
    item.save(update_fields=["status", "decided_at", "decided_by", "decision_note"])

    profile = item.user
    if not profile:
        raise ValueError("missing_profile")
    if approve:
        kc = KeycloakAdminClient()
        try:
            prov.provision_application_access(kc, profile.keycloak_sub, item.application)
        except KeycloakAdminError as exc:
            logger.exception("provision additional app failed")
            raise ValueError("Échec du provisioning Keycloak pour cette application.") from exc
        _notify_user(profile, f"Accès : {item.application.nom}", "Votre demande a été acceptée.")
    else:
        _notify_user(profile, f"Accès : {item.application.nom}", "Votre demande a été refusée.")

    _log(actor_sub, "app_admin_decide_additional", {"item_id": item.pk, "approve": approve})
