from __future__ import annotations

import io
import os
import uuid
from dataclasses import dataclass, field
from typing import Any

from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from PIL import Image
from rest_framework import status
from rest_framework.test import APIClient, APIRequestFactory

from inscriptions.authentication import KeycloakUser
from inscriptions.crypto_util import encrypt_text
from inscriptions.models import (
    AccessRequestItem,
    Application,
    Notification,
    Organisme,
    RegistrationRequest,
    Reserve,
    ReserveReferentRequest,
)
from inscriptions.permissions import IsKeycloakAuthenticated, IsSuperAdmin, is_app_admin
from inscriptions.roles import application_admin_group_paths, super_admin_group_paths
from inscriptions.serializers import AdminApplicationWriteSerializer, SignupSerializer
from inscriptions.services import application_access as app_access_svc
from inscriptions.services import workflows
from inscriptions.services.application_images import (
    ApplicationImageError,
    application_image_path,
    remove_application_image,
    save_application_image,
)


@dataclass
class TestUser:
    keycloak_sub: str
    email: str
    username: str = ""
    first_name: str = "Test"
    last_name: str = "User"
    groups: list[str] = field(default_factory=list)

    @property
    def sub(self) -> str:
        return self.keycloak_sub


def make_profile(
    *,
    sub: str | None = None,
    email: str = "user@test.local",
    is_super_admin: bool = False,
    **extra,
) -> TestUser:
    sub = sub or f"sub-{uuid.uuid4()}"
    groups: list[str] = list(extra.pop("groups", []) or [])
    if is_super_admin:
        groups.extend(sorted(super_admin_group_paths()))
    user = TestUser(
        keycloak_sub=sub,
        email=email,
        username=extra.pop("username", email.split("@")[0]),
        first_name=extra.pop("first_name", "Test"),
        last_name=extra.pop("last_name", "User"),
        groups=sorted(set(groups)),
    )
    return user


def make_keycloak_user(profile: TestUser, *, groups: list[str] | None = None, **claims: Any) -> KeycloakUser:
    payload = {
        "sub": profile.keycloak_sub,
        "email": profile.email,
        "preferred_username": profile.username,
        "given_name": profile.first_name,
        "family_name": profile.last_name,
        "groups": groups if groups is not None else profile.groups,
    }
    payload.update(claims)
    return KeycloakUser(payload)


def auth_client(
    client: APIClient,
    profile: TestUser,
    *,
    groups: list[str] | None = None,
    **claims: Any,
) -> APIClient:
    client.force_authenticate(user=make_keycloak_user(profile, groups=groups, **claims))
    return client


def make_application(**overrides) -> Application:
    slug = overrides.pop("slug", f"app-{uuid.uuid4().hex[:8]}")
    defaults = {
        "slug": slug,
        "nom": overrides.pop("nom", slug.replace("-", " ").title()),
        "url": "https://example.org",
        "image": "",
        "description": "Test app",
        "managed_by_si": True,
        "requires_access_request": True,
    }
    defaults.update(overrides)
    return Application.objects.create(**defaults)


def make_reserve(**overrides) -> Reserve:
    code = overrides.pop("area_code", f"RNN{100 + Reserve.objects.count()}")
    defaults = {
        "area_code": code,
        "area_name": overrides.pop("area_name", f"Réserve {code}"),
        "id_type": overrides.pop("id_type", "5"),
    }
    defaults.update(overrides)
    return Reserve.objects.create(**defaults)


def make_registration(
    *,
    app: Application | None = None,
    with_access_item: bool = True,
    **overrides,
) -> RegistrationRequest:
    app = app or make_application()
    defaults = {
        "email": overrides.pop("email", f"reg-{uuid.uuid4().hex[:6]}@test.local"),
        "username": overrides.pop("username", f"user{uuid.uuid4().hex[:6]}"),
        "password_cipher": encrypt_text(overrides.pop("password", "secretpass1")),
        "first_name": "Jean",
        "last_name": "Dupont",
        "status": RegistrationRequest.STATUS_PENDING_SUPER,
        "reserve_codes": [],
        "champs_addi": {},
    }
    defaults.update(overrides)
    registration = RegistrationRequest.objects.create(**defaults)
    if with_access_item:
        AccessRequestItem.objects.create(
            registration=registration,
            application=app,
            origin=AccessRequestItem.ORIGIN_REGISTRATION,
            status=AccessRequestItem.STATUS_PENDING,
            request_justification="Besoin métier",
        )
    return registration


def make_app_admin(profile: TestUser, app: Application) -> TestUser:
    for path in application_admin_group_paths(app.slug):
        if path not in profile.groups:
            profile.groups.append(path)
    profile.groups = sorted(set(profile.groups))
    return profile


def signup_payload(**overrides) -> dict:
    data = {
        "nom_role": "Dupont",
        "prenom_role": "Jean",
        "identifiant": overrides.pop("identifiant", f"user{uuid.uuid4().hex[:6]}"),
        "email": overrides.pop("email", f"signup-{uuid.uuid4().hex[:6]}@test.local"),
        "password": "secretpass1",
        "password_confirmation": "secretpass1",
        "remarques": "Fonction test",
        "id_organisme": None,
        "organisme": "Org libre",
        "champs_addi": {"reserves": []},
        "applications": [],
    }
    data.update(overrides)
    return data


def make_test_image_upload(name: str = "test.png", size=(120, 60), color="red") -> SimpleUploadedFile:
    buf = io.BytesIO()
    Image.new("RGB", size, color=color).save(buf, format="PNG")
    buf.seek(0)
    return SimpleUploadedFile(name, buf.read(), content_type="image/png")


def keycloak_integration_enabled() -> bool:
    return os.environ.get("KEYCLOAK_TEST_INTEGRATION") == "1"


class BaseApiTestCase(TestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        mail.outbox = []
