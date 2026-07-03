from unittest.mock import patch

from rest_framework import status

from inscriptions.models import Notification
from inscriptions.tests.helpers import (
    BaseApiTestCase,
    auth_client,
    make_app_admin,
    make_application,
    make_profile,
)


class MeApiTests(BaseApiTestCase):
    def setUp(self):
        super().setUp()
        self.regular_user = make_profile(sub="user-sub", email="user@test.local")

    def test_me_requires_auth(self):
        response = self.client.get("/api/me/")
        self.assertIn(response.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))

    def test_me_returns_profile(self):
        auth_client(self.client, self.regular_user)
        response = self.client.get("/api/me/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["profile"]["email"], self.regular_user.email)
        self.assertIn("applications", data)

    def test_me_flags_reserve_referent_from_token_groups(self):
        from inscriptions.tests.helpers import make_reserve

        reserve = make_reserve(area_code="RNN42", area_name="Réserve test")
        auth_client(
            self.client,
            self.regular_user,
            groups=[f"reserves/{reserve.area_code}/referent", f"reserves/{reserve.area_code}"],
        )
        response = self.client.get("/api/me/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertTrue(data["is_reserve_referent"])
        self.assertTrue(any(r["area_code"] == reserve.area_code and r["referent"] for r in data["reserves"]))

    def test_me_flags_reserve_referent_from_keycloak_when_token_has_no_groups(self):
        from inscriptions.tests.helpers import make_reserve

        reserve = make_reserve(area_code="RNN43", area_name="Réserve KC")
        auth_client(self.client, self.regular_user, groups=[])
        with self.settings(KEYCLOAK_SYNC_ENABLED=True):
            with patch("inscriptions.views.KeycloakAdminClient") as kc_cls:
                kc = kc_cls.return_value
                kc.get_user_groups.return_value = [
                    {"path": f"/reserves/{reserve.area_code}/referent"},
                    {"path": f"/reserves/{reserve.area_code}"},
                ]
                response = self.client.get("/api/me/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertTrue(data["is_reserve_referent"])

    def test_me_patch_accepts_fonction(self):
        auth_client(self.client, self.regular_user)
        with patch("inscriptions.views.KeycloakAdminClient.update_user_profile"):
            response = self.client.patch("/api/me/", {"fonction": "Référent"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_notifications_list(self):
        Notification.objects.create(user=self.regular_user, title="Test", body="Corps")
        auth_client(self.client, self.regular_user)
        response = self.client.get("/api/notifications/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.json()), 1)

    def test_mark_notification_read(self):
        notif = Notification.objects.create(user=self.regular_user, title="Test", body="Corps")
        auth_client(self.client, self.regular_user)
        response = self.client.patch(f"/api/notifications/{notif.pk}/mark-read/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        notif.refresh_from_db()
        self.assertTrue(notif.read)


class AppAdminApiTests(BaseApiTestCase):
    def test_pending_items_for_app_admin(self):
        app = make_application(slug="waterwise")
        admin_profile = make_profile(email="admin-app@test.local")
        make_app_admin(admin_profile, app)
        auth_client(self.client, admin_profile)

        response = self.client.get("/api/admin/pending-items/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsInstance(response.json(), list)

    def test_my_validation_applications(self):
        app = make_application(slug="waterwise")
        admin_profile = make_profile(email="admin-app@test.local")
        make_app_admin(admin_profile, app)
        auth_client(self.client, admin_profile)

        response = self.client.get("/api/admin/my-validation-applications/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        slugs = {row["slug"] for row in response.json()}
        self.assertIn(app.slug, slugs)
