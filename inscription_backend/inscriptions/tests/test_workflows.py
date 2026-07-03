from unittest.mock import patch

from django.core import mail
from rest_framework import status

from inscriptions.models import (
    AccessRequestItem,
    Notification,
    RegistrationRequest,
    ReserveReferentRequest,
    UserProfile,
    UserReserveLink,
)
from inscriptions.services import workflows
from inscriptions.tests.helpers import (
    BaseApiTestCase,
    auth_client,
    make_application,
    make_profile,
    make_registration,
    make_reserve,
)


class WorkflowTests(BaseApiTestCase):
    def test_super_admin_approve_creates_profile_and_pending_apps(self):
        app = make_application(slug="waterwise")
        reg = make_registration(app=app)
        actor = make_profile(is_super_admin=True)

        workflows.super_admin_approve(reg, actor, actor.keycloak_sub)

        reg.refresh_from_db()
        self.assertEqual(reg.status, RegistrationRequest.STATUS_PENDING_APPS)
        self.assertIsNotNone(reg.created_profile)
        self.assertTrue(reg.keycloak_user_id.startswith("local-"))
        self.assertTrue(Notification.objects.filter(user=reg.created_profile).exists())
        self.assertGreaterEqual(len(mail.outbox), 1)

    def test_super_admin_approve_without_items_deletes_registration(self):
        app = make_application()
        reg = make_registration(app=app, with_access_item=False)
        actor = make_profile(is_super_admin=True)
        public_id = str(reg.public_id)

        workflows.super_admin_approve(reg, actor, actor.keycloak_sub)

        self.assertFalse(RegistrationRequest.objects.filter(public_id=public_id).exists())

    def test_super_admin_reject_updates_status(self):
        reg = make_registration()
        workflows.super_admin_reject(reg, "actor-sub", note="Non éligible")
        reg.refresh_from_db()
        self.assertEqual(reg.status, RegistrationRequest.STATUS_SUPER_REJECTED)

    def test_app_admin_approve_provisions_and_finalizes(self):
        app = make_application(slug="waterwise")
        reg = make_registration(app=app)
        actor = make_profile(is_super_admin=True)
        workflows.super_admin_approve(reg, actor, actor.keycloak_sub)
        reg.refresh_from_db()
        item = reg.items.get()
        public_id = str(reg.public_id)

        with patch("inscriptions.services.workflows.prov.provision_application_access") as provision:
            workflows.app_admin_decide_item(item, True, actor, actor.keycloak_sub)
            provision.assert_called_once()

        self.assertFalse(RegistrationRequest.objects.filter(public_id=public_id).exists())

    def test_app_admin_reject_requires_note(self):
        app = make_application()
        reg = make_registration(app=app)
        actor = make_profile(is_super_admin=True)
        workflows.super_admin_approve(reg, actor, actor.keycloak_sub)
        item = reg.items.get()

        with self.assertRaises(ValueError):
            workflows.app_admin_decide_item(item, False, actor, actor.keycloak_sub, note="")

    def test_super_admin_approve_creates_reserve_links_and_referent_requests(self):
        reserve = make_reserve(area_code="RNN99")
        app = make_application()
        reg = make_registration(
            app=app,
            reserve_codes=[reserve.area_code],
            champs_addi={"reserves_referent": [{"id": reserve.area_code}]},
        )
        actor = make_profile(is_super_admin=True)

        workflows.super_admin_approve(reg, actor, actor.keycloak_sub)

        profile = UserProfile.objects.get(email=reg.email)
        self.assertTrue(UserReserveLink.objects.filter(user=profile, reserve=reserve).exists())
        self.assertTrue(ReserveReferentRequest.objects.filter(user=profile, reserve=reserve).exists())

    def test_create_additional_access_request(self):
        app = make_application(slug="waterwise")
        profile = make_profile()
        request_id = workflows.create_additional_access_request(profile, [app.slug], "Besoin")
        self.assertIsNotNone(request_id)
        self.assertTrue(
            profile.access_requests.filter(application=app, status=AccessRequestItem.STATUS_PENDING).exists()
        )


class ReserveReferentRequestApiTests(BaseApiTestCase):
    def setUp(self):
        super().setUp()
        self.super_admin = make_profile(sub="super-admin-sub", email="super@test.local", is_super_admin=True)
        self.user = make_profile(sub="referent-user-sub", email="referent@test.local")
        self.reserve = make_reserve()

    def test_decide_approve_deletes_request(self):
        req = ReserveReferentRequest.objects.create(user=self.user, reserve=self.reserve)
        auth_client(self.client, self.super_admin)
        with patch("inscriptions.views.KeycloakAdminClient") as kc_cls:
            kc = kc_cls.return_value
            kc.ensure_reserve_referent_group.return_value = "group-id"
            response = self.client.post(f"/api/admin/reserve-referent-requests/{req.id}/approve/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(ReserveReferentRequest.objects.filter(pk=req.id).exists())
        self.assertTrue(Notification.objects.filter(user=self.user).exists())
        self.assertGreaterEqual(len(mail.outbox), 1)

    def test_decide_reject_deletes_request(self):
        req = ReserveReferentRequest.objects.create(user=self.user, reserve=self.reserve)
        auth_client(self.client, self.super_admin)
        response = self.client.post(
            f"/api/admin/reserve-referent-requests/{req.id}/reject/",
            {"note": "Non éligible"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(ReserveReferentRequest.objects.filter(pk=req.id).exists())


class AdminRegistrationApiTests(BaseApiTestCase):
    def setUp(self):
        super().setUp()
        self.super_admin = make_profile(sub="super-admin-sub", email="super@test.local", is_super_admin=True)
        self.regular_user = make_profile(sub="user-sub", email="user@test.local")

    def test_super_admin_lists_registrations(self):
        make_registration()
        auth_client(self.client, self.super_admin)
        response = self.client.get("/api/admin/registration-requests/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.json()), 1)

    def test_regular_user_forbidden_on_admin_list(self):
        auth_client(self.client, self.regular_user)
        response = self.client.get("/api/admin/registration-requests/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_super_approve_endpoint(self):
        reg = make_registration()
        auth_client(self.client, self.super_admin)
        response = self.client.post(f"/api/admin/registration-requests/{reg.public_id}/super-approve/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_super_reject_endpoint(self):
        reg = make_registration()
        auth_client(self.client, self.super_admin)
        response = self.client.post(
            f"/api/admin/registration-requests/{reg.public_id}/super-reject/",
            {"note": "Refus test"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        reg.refresh_from_db()
        self.assertEqual(reg.status, RegistrationRequest.STATUS_SUPER_REJECTED)
