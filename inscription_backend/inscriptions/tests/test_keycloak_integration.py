"""
Tests d'intégration Keycloak — realm dédié dans .env (ex. inscription-test).

  # .env local : KEYCLOAK_REALM=inscription-test + secrets du realm de test
  export KEYCLOAK_TEST_INTEGRATION=1
  DJANGO_SETTINGS_MODULE=config.settings python manage.py test inscriptions.tests.test_keycloak_integration
"""

import uuid
from unittest import skipUnless, SkipTest

from django.conf import settings
from django.test import TestCase

from inscriptions.keycloak_client import KeycloakAdminClient, KeycloakAdminError
from inscriptions.tests.helpers import keycloak_integration_enabled

_FORBIDDEN_REALMS = {"rnf", "si-rnf", "master", "production", "prod"}


def _safe_realm() -> bool:
    if not keycloak_integration_enabled():
        return False
    realm = (settings.KEYCLOAK_REALM or "").strip().lower()
    if realm in _FORBIDDEN_REALMS:
        return False
    return bool(realm)


@skipUnless(_safe_realm(), "KEYCLOAK_TEST_INTEGRATION=1 et KEYCLOAK_REALM hors prod requis")
class KeycloakIntegrationTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        kc = KeycloakAdminClient()
        try:
            kc.list_top_groups()
        except KeycloakAdminError as exc:
            if "403" in str(exc):
                raise SkipTest(
                    "inscription-admin : compte de service sans rôles realm-management "
                    "(view-groups, manage-groups, view-users, manage-users). "
                    "Keycloak → Clients → inscription-admin → Service account roles."
                ) from exc
            raise

    def setUp(self):
        self.kc = KeycloakAdminClient()

    def test_ensure_application_group(self):
        slug = f"test-app-{uuid.uuid4().hex[:8]}"
        group_id = self.kc.ensure_application_group(slug)
        self.assertTrue(group_id)
        group_id_2 = self.kc.ensure_application_group(slug)
        self.assertEqual(group_id_2, group_id)

    def test_create_user_and_join_application_group(self):
        slug = f"test-app-{uuid.uuid4().hex[:8]}"
        group_id = self.kc.ensure_application_group(slug)
        username = f"testuser-{uuid.uuid4().hex[:8]}"
        email = f"{username}@test.local"

        user_id = self.kc.create_user(
            username=username,
            email=email,
            first_name="Test",
            last_name="Integration",
            password="TestPass123!",
            temporary_password=False,
            require_verify_email=False,
        )
        self.kc.user_join_group(user_id, group_id)
        groups = self.kc.get_user_groups(user_id)
        paths = {g.get("path", "") for g in groups}
        self.assertTrue(any(slug in p for p in paths), msg=f"paths={paths}")
