from unittest.mock import patch

from django.core import mail
from rest_framework import status

from inscriptions.models import (
    AccessRequestItem,
    Notification,
    RegistrationRequest,
    ReserveReferentRequest,
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

        workflows.super_admin_approve(reg, actor.keycloak_sub)

        reg.refresh_from_db()
        self.assertEqual(reg.status, RegistrationRequest.STATUS_PENDING_APPS)
        self.assertTrue(reg.keycloak_user_id.startswith("local-"))
        self.assertTrue(Notification.objects.filter(user_sub=reg.keycloak_user_id).exists())
        self.assertGreaterEqual(len(mail.outbox), 1)

    def test_super_admin_approve_without_items_deletes_registration(self):
        app = make_application()
        reg = make_registration(app=app, with_access_item=False)
        actor = make_profile(is_super_admin=True)
        public_id = str(reg.public_id)

        workflows.super_admin_approve(reg, actor.keycloak_sub)

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
        workflows.super_admin_approve(reg, actor.keycloak_sub)
        reg.refresh_from_db()
        item = reg.items.get()
        public_id = str(reg.public_id)

        with patch("inscriptions.services.workflows.prov.provision_application_access") as provision:
            workflows.app_admin_decide_item(item, True, actor.keycloak_sub)
            provision.assert_called_once()

        self.assertFalse(RegistrationRequest.objects.filter(public_id=public_id).exists())

    def test_app_admin_reject_requires_note(self):
        app = make_application()
        reg = make_registration(app=app)
        actor = make_profile(is_super_admin=True)
        workflows.super_admin_approve(reg, actor.keycloak_sub)
        item = reg.items.get()

        with self.assertRaises(ValueError):
            workflows.app_admin_decide_item(item, False, actor.keycloak_sub, note="")

    def test_super_admin_approve_creates_referent_requests(self):
        reserve = make_reserve(area_code="RNN99")
        app = make_application()
        reg = make_registration(
            app=app,
            reserve_codes=[reserve.area_code],
            champs_addi={"reserves_referent": [{"id": reserve.area_code}]},
        )
        actor = make_profile(is_super_admin=True)

        workflows.super_admin_approve(reg, actor.keycloak_sub)

        reg.refresh_from_db()
        self.assertTrue(
            ReserveReferentRequest.objects.filter(user_sub=reg.keycloak_user_id, reserve=reserve).exists()
        )

    @patch("inscriptions.services.workflows.settings.KEYCLOAK_SYNC_ENABLED", True)
    @patch("inscriptions.services.workflows.prov.provision_user_groups_after_super_approval")
    @patch("inscriptions.services.workflows.KeycloakAdminClient")
    def test_super_admin_approve_stores_fonction_in_keycloak(self, kc_cls, _provision):
        kc = kc_cls.return_value
        kc.create_user.return_value = "kc-user-id"
        reg = make_registration(remarks="Conservateur")
        actor = make_profile(is_super_admin=True)

        workflows.super_admin_approve(reg, actor.keycloak_sub)

        kc.create_user.assert_called_once()
        self.assertEqual(kc.create_user.call_args.kwargs.get("function_value"), "Conservateur")

    def test_create_additional_access_request(self):
        app = make_application(slug="waterwise")
        profile = make_profile()
        from inscriptions.user_identity import UserInfo

        user_info = UserInfo(
            sub=profile.keycloak_sub,
            email=profile.email,
            username=profile.username,
            first_name=profile.first_name,
            last_name=profile.last_name,
        )
        request_id = workflows.create_additional_access_request(
            profile.keycloak_sub, user_info, [app.slug], "Besoin"
        )
        self.assertIsNotNone(request_id)
        self.assertTrue(
            AccessRequestItem.objects.filter(
                user_sub=profile.keycloak_sub,
                application=app,
                status=AccessRequestItem.STATUS_PENDING,
            ).exists()
        )


class ReserveReferentRequestApiTests(BaseApiTestCase):
    def setUp(self):
        super().setUp()
        self.super_admin = make_profile(sub="super-admin-sub", email="super@test.local", is_super_admin=True)
        self.user = make_profile(sub="referent-user-sub", email="referent@test.local")
        self.reserve = make_reserve()

    def test_decide_approve_deletes_request(self):
        req = ReserveReferentRequest.objects.create(user_sub=self.user.keycloak_sub, reserve=self.reserve)
        auth_client(self.client, self.super_admin)
        from inscriptions.user_identity import UserInfo

        user_info = UserInfo(
            sub=self.user.keycloak_sub,
            email=self.user.email,
            username=self.user.username,
            first_name=self.user.first_name,
            last_name=self.user.last_name,
        )
        with patch("inscriptions.views.KeycloakAdminClient") as kc_cls:
            kc = kc_cls.return_value
            kc.ensure_reserve_referent_group.return_value = "group-id"
            with patch("inscriptions.views.fetch_user_info", return_value=user_info):
                response = self.client.post(f"/api/admin/reserve-referent-requests/{req.id}/approve/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(ReserveReferentRequest.objects.filter(pk=req.id).exists())
        self.assertTrue(Notification.objects.filter(user_sub=self.user.keycloak_sub).exists())
        self.assertGreaterEqual(len(mail.outbox), 1)

    def test_decide_reject_deletes_request(self):
        req = ReserveReferentRequest.objects.create(user_sub=self.user.keycloak_sub, reserve=self.reserve)
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
