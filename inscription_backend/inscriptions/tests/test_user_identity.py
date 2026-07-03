from django.test import TestCase

from inscriptions.services import email_templates as tpl
from inscriptions.user_identity import UserInfo, user_label
from inscriptions.tests.helpers import make_application, make_profile, make_registration


class UserLabelTests(TestCase):
    def test_user_label_includes_organisme(self):
        info = UserInfo(
            sub="sub-1",
            email="zacharie.moulin@gmail.com",
            username="zach",
            first_name="Zac",
            last_name="Mou",
            organisme="Réserves Naturelles de France",
        )
        self.assertEqual(
            user_label(info),
            "Zac Mou (zacharie.moulin@gmail.com - Réserves Naturelles de France)",
        )

    def test_app_access_request_admin_email_uses_organisme(self):
        app = make_application(slug="geonature", nom="GeoNature Saisie")
        applicant = UserInfo(
            sub="sub-1",
            email="zacharie.moulin@gmail.com",
            username="zach",
            first_name="Zac",
            last_name="Mou",
            organisme="Réserves Naturelles de France",
        )
        _subject, html, plain = tpl.app_access_request_admin_email(
            applicant=applicant,
            application=app,
            justification="Besoin métier",
        )
        self.assertIn("zacharie.moulin@gmail.com - Réserves Naturelles de France", html)
        self.assertIn("GeoNature Saisie", plain)

    def test_registration_admin_email_uses_organisme(self):
        profile = make_profile(first_name="Jean", last_name="Dupont", email="jean@test.local")
        reg = make_registration(
            email=profile.email,
            first_name=profile.first_name,
            last_name=profile.last_name,
        )
        _subject, html, _plain = tpl.registration_submitted_admin_email(reg)
        self.assertIn(reg.email, html)
