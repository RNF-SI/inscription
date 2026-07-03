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
