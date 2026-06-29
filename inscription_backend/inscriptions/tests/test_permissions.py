from inscriptions.models import ApplicationAdmin
from inscriptions.permissions import IsKeycloakAuthenticated, IsSuperAdmin, is_app_admin
from inscriptions.tests.helpers import (
    BaseApiTestCase,
    make_app_admin,
    make_application,
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
        self.assertTrue(IsKeycloakAuthenticated().has_permission(request, None))

    def test_is_keycloak_authenticated_rejects_anonymous(self):
        request = self.factory.get("/")
        request.user = None
        self.assertFalse(IsKeycloakAuthenticated().has_permission(request, None))

    def test_is_super_admin(self):
        profile = make_profile(is_super_admin=True)
        request = self.factory.get("/")
        request.user = make_keycloak_user(profile)
        self.assertTrue(IsSuperAdmin().has_permission(request, None))

    def test_is_super_admin_rejects_regular_user(self):
        profile = make_profile(is_super_admin=False)
        request = self.factory.get("/")
        request.user = make_keycloak_user(profile)
        self.assertFalse(IsSuperAdmin().has_permission(request, None))

    def test_is_app_admin_super_admin(self):
        app = make_application()
        profile = make_profile(is_super_admin=True)
        self.assertTrue(is_app_admin(profile, app))

    def test_is_app_admin_assigned(self):
        app = make_application()
        profile = make_profile()
        make_app_admin(profile, app)
        self.assertTrue(is_app_admin(profile, app))

    def test_is_app_admin_denied(self):
        app = make_application()
        profile = make_profile()
        self.assertFalse(is_app_admin(profile, app))
        self.assertEqual(ApplicationAdmin.objects.count(), 0)
