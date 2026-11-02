from unittest.mock import patch

from inscriptions.permissions import is_app_admin
from inscriptions.roles import application_admin_group_paths, is_super_admin, super_admin_group_paths
from inscriptions.tests.helpers import (
    BaseApiTestCase,
    make_application,
    make_app_admin,
    make_keycloak_user,
    make_profile,
)
from rest_framework.test import APIRequestFactory


class PermissionsTests(BaseApiTestCase):
    def setUp(self):
        super().setUp()
        self.factory = APIRequestFactory()

    def test_is_keycloak_authenticated(self):
        profile = make_profile()
        request = self.factory.get("/")
        request.user = make_keycloak_user(profile)
        from inscriptions.permissions import IsKeycloakAuthenticated

        self.assertTrue(IsKeycloakAuthenticated().has_permission(request, None))

    def test_is_keycloak_authenticated_rejects_anonymous(self):
        request = self.factory.get("/")
        request.user = None
        from inscriptions.permissions import IsKeycloakAuthenticated

        self.assertFalse(IsKeycloakAuthenticated().has_permission(request, None))

    def test_is_super_admin(self):
        profile = make_profile(is_super_admin=True)
        request = self.factory.get("/")
        request.user = make_keycloak_user(profile)
        from inscriptions.permissions import IsSuperAdmin

        self.assertTrue(IsSuperAdmin().has_permission(request, None))

    def test_is_super_admin_rejects_regular_user(self):
        profile = make_profile()
        request = self.factory.get("/")
        request.user = make_keycloak_user(profile)
        from inscriptions.permissions import IsSuperAdmin

        self.assertFalse(IsSuperAdmin().has_permission(request, None))

    def test_is_app_admin_super_admin(self):
        app = make_application()
        profile = make_profile(is_super_admin=True)
        self.assertTrue(is_app_admin(profile.groups, app))

    def test_is_app_admin_assigned(self):
        app = make_application()
        profile = make_profile()
        make_app_admin(profile, app)
        self.assertTrue(is_app_admin(profile.groups, app))

    def test_is_app_admin_denied(self):
        app = make_application()
        profile = make_profile()
        self.assertFalse(is_app_admin(profile.groups, app))

    def test_super_admin_group_paths(self):
        self.assertTrue(is_super_admin(list(super_admin_group_paths())))

    def test_application_admin_group_paths(self):
        app = make_application(slug="waterwise")
        paths = list(application_admin_group_paths(app.slug))
        self.assertTrue(is_app_admin(paths, app))


class DefaultPermissionTests(BaseApiTestCase):
    """DEFAULT_PERMISSION_CLASSES est fail-safe : une vue sans permission_classes
    explicite exige un JWT. Les vues réellement publiques doivent le déclarer."""

    def test_default_permission_class_requires_authentication(self):
        from rest_framework.settings import api_settings

        from inscriptions.permissions import IsKeycloakAuthenticated

        self.assertEqual(api_settings.DEFAULT_PERMISSION_CLASSES, [IsKeycloakAuthenticated])

    def test_anonymous_is_rejected_on_authenticated_endpoints(self):
        for url in ("/api/me/", "/api/notifications/", "/api/admin/registration-requests/"):
            with self.subTest(url=url):
                self.assertIn(self.client.get(url).status_code, (401, 403))

    def test_public_endpoints_stay_reachable_anonymously(self):
        from inscriptions.models import Organisme
        from inscriptions.tests.helpers import make_application, make_reserve

        org = Organisme.objects.create(id_organisme=1, nom_organisme="Org test")
        make_reserve(area_code="RNN99", area_name="Réserve test", id_type="5")
        make_application()
        for url in (
            "/api/auth/keycloak-config/",
            "/api/organismes/",
            f"/api/organisme/{org.pk}/",
            "/api/reserves/",
            "/api/applications/",
        ):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200, url)


class TokenEndpointResilienceTests(BaseApiTestCase):
    """Keycloak injoignable sur le chemin de connexion : 503 explicite, pas une 500."""

    def test_token_exchange_returns_503_when_keycloak_is_down(self):
        import requests

        with patch("inscriptions.views.requests.post", side_effect=requests.ConnectionError("down")):
            response = self.client.post(
                "/api/auth/token/",
                {"code": "c", "redirect_uri": "https://front/auth/callback"},
                format="json",
            )
        self.assertEqual(response.status_code, 503)

    def test_refresh_returns_503_when_keycloak_is_down(self):
        import requests

        with patch("inscriptions.views.requests.post", side_effect=requests.ConnectionError("down")):
            response = self.client.post("/api/auth/refresh/", {"refresh_token": "r"}, format="json")
        self.assertEqual(response.status_code, 503)
