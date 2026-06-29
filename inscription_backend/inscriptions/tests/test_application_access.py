from unittest.mock import MagicMock, patch

from inscriptions.services import application_access as svc
from inscriptions.tests.helpers import BaseApiTestCase, make_application


class ApplicationAccessServiceTests(BaseApiTestCase):
    def setUp(self):
        super().setUp()
        self.managed_app = make_application(slug="ancrage", nom="Ancrage")
        self.auto_app = make_application(slug="socle", nom="SOCLE", requires_access_request=False)
        self.out_of_si_app = make_application(slug="naturadapt", nom="Natur'Adapt", managed_by_si=False)

    def test_si_managed_excludes_out_of_si(self):
        slugs = set(svc.si_managed_applications().values_list("slug", flat=True))
        self.assertIn(self.managed_app.slug, slugs)
        self.assertNotIn(self.out_of_si_app.slug, slugs)

    def test_auto_granted_not_editable(self):
        self.assertFalse(svc.is_application_access_editable(self.auto_app))

    def test_managed_with_request_is_editable(self):
        self.assertTrue(svc.is_application_access_editable(self.managed_app))

    def test_user_has_application_access_from_group(self):
        paths = {f"/applications/{self.managed_app.slug}", "applications/other"}
        self.assertTrue(svc.user_has_application_access(paths, self.managed_app))

    def test_build_rows_marks_auto_granted(self):
        rows = svc.build_user_application_access_rows(
            [self.auto_app, self.managed_app],
            group_paths=set(),
            pending_app_ids=set(),
        )
        by_slug = {r["application"].slug: r for r in rows}
        self.assertTrue(by_slug[self.auto_app.slug]["auto_granted"])
        self.assertTrue(by_slug[self.auto_app.slug]["has_access"])
        self.assertTrue(by_slug[self.managed_app.slug]["editable"])

    def test_apply_changes_provisions_when_missing(self):
        kc = MagicMock()
        desired = {self.managed_app.slug: True}
        with patch("inscriptions.services.application_access.prov.provision_application_access") as provision:
            svc.apply_application_access_changes(kc, "user-sub", set(), desired)
            provision.assert_called_once_with(kc, "user-sub", self.managed_app)

    def test_apply_changes_skips_out_of_si(self):
        kc = MagicMock()
        desired = {self.out_of_si_app.slug: True}
        with patch("inscriptions.services.application_access.prov.provision_application_access") as provision:
            svc.apply_application_access_changes(kc, "user-sub", set(), desired)
            provision.assert_not_called()
