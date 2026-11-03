"""Le rapport du --dry-run doit dire ce qui va réellement se passer.

Sans la recherche dans Keycloak, un import rejoué annonçait 945 créations et
0 rattachement là où la vraie exécution ne crée rien : l'inverse de la réalité
sur le chiffre qu'on lit en premier.
"""

from io import StringIO
from unittest.mock import MagicMock, patch

from django.core.management import call_command
from django.test import TestCase, override_settings

from inscriptions.models import Application
from inscriptions.services.legacy_user_migration import LegacyUserRow

CHEMIN = "inscriptions.management.commands.migrate_legacy_users_to_keycloak"


def _compte(id_role: int, username: str) -> LegacyUserRow:
    return LegacyUserRow(
        id_role=id_role,
        username=username,
        email=f"{username}@example.org",
        first_name="Jean",
        last_name="Dupont",
        fonction="",
        id_organisme=None,
        uuid_role=f"0000-{id_role}",
        password_bcrypt="$2b$12$abcdefghijklmnopqrstuv",
        app_member_slugs={"ancrage"},
    )


@override_settings(KEYCLOAK_SYNC_ENABLED=True, KEYCLOAK_REALM="si-rnf")
class DryRunTests(TestCase):
    def setUp(self):
        Application.objects.create(slug="ancrage", nom="Ancrage", legacy_group_id_role=64)
        self.comptes = [_compte(10, "alice"), _compte(11, "bob")]

        self.patches = [
            patch(f"{CHEMIN}.KeycloakAdminClient", return_value=MagicMock()),
            patch(f"{CHEMIN}.load_legacy_applications", return_value=[]),
            patch(f"{CHEMIN}.build_legacy_application_slug_map", return_value={}),
            patch(f"{CHEMIN}.load_legacy_users", return_value=self.comptes),
            patch(
                f"{CHEMIN}.prepare_migration_groups",
                return_value={"organismes_synced": 0, "organisme_groups": 0, "reserve_groups": 0},
            ),
        ]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)

    def test_a_blanc_les_comptes_existants_sont_comptes_comme_rattaches(self):
        sortie = StringIO()
        with patch(f"{CHEMIN}.find_existing_keycloak_user") as cherche, patch(
            f"{CHEMIN}.link_existing_keycloak_user"
        ) as rattache:
            cherche.side_effect = lambda kc, user: (f"kc-{user.id_role}", "legacy_id_role")
            call_command("migrate_legacy_users_to_keycloak", "--limit", "0", "--force",
                         "--dry-run", stdout=sortie)

        texte = sortie.getvalue()
        self.assertIn("0 créé(s), 2 rattaché(s)", texte)
        self.assertIn("RATTACHERAIT par legacy_id_role", texte)
        self.assertEqual(cherche.call_count, 2, "la recherche doit avoir lieu même à blanc")
        rattache.assert_not_called()

    def test_a_blanc_rien_n_est_ecrit(self):
        """La recherche est une lecture ; le rattachement et la création n'ont pas lieu."""
        with patch(f"{CHEMIN}.find_existing_keycloak_user", return_value=("kc-1", "e-mail")), patch(
            f"{CHEMIN}.link_existing_keycloak_user"
        ) as rattache, patch(f"{CHEMIN}.migrate_legacy_user_to_keycloak") as cree:
            call_command("migrate_legacy_users_to_keycloak", "--limit", "0", "--force",
                         "--dry-run", stdout=StringIO())

        rattache.assert_not_called()
        cree.assert_not_called()

    def test_un_compte_absent_reste_compte_comme_creation(self):
        sortie = StringIO()
        with patch(f"{CHEMIN}.find_existing_keycloak_user", return_value=None):
            call_command("migrate_legacy_users_to_keycloak", "--limit", "0", "--force",
                         "--dry-run", stdout=sortie)

        self.assertIn("2 créé(s), 0 rattaché(s)", sortie.getvalue())
