from django.core import mail
from django.test import TestCase, override_settings

from inscriptions.services import email_templates as tpl
from inscriptions.services import mail as mail_svc
from inscriptions.tests.helpers import make_application, make_registration


class EmailTemplateTests(TestCase):
    def test_registration_submitted_user_contains_brand_and_details(self):
        app = make_application(slug="waterwise", nom="Waterwise")
        reg = make_registration(app=app, email="user@example.org", first_name="Jean", last_name="Dupont")
        subject, html, plain = tpl.registration_submitted_user_email(reg)
        self.assertIn("inscription", subject.lower())
        self.assertIn("#0B885D", html)
        self.assertIn("Jean", html)
        self.assertIn("Waterwise", html)
        self.assertIn("user@example.org", plain)

    def test_registration_approved_user_contains_platform_links(self):
        app = make_application(slug="ancrage", nom="Ancrage")
        reg = make_registration(app=app)
        subject, html, _plain = tpl.registration_approved_user_email(reg)
        self.assertIn("validée", subject.lower())
        self.assertIn("mon-compte", html)
        self.assertIn("Ancrage", html)

    def test_app_access_granted_contains_app_url(self):
        app = make_application(slug="geo", nom="GeoNature", url="https://geonature.example.org")
        subject, html, _plain = tpl.app_access_granted_user_email(first_name="Marie", application=app)
        self.assertIn("GeoNature", subject)
        self.assertIn("https://geonature.example.org", html)


@override_settings(SUPERADMIN_NOTIFY_EMAILS=["admin@test.local"])
class MailServiceTests(TestCase):
    def setUp(self):
        mail.outbox = []

    def test_send_html_email_attaches_alternative(self):
        mail_svc.send_html_email(
            ["user@example.org"],
            "Test",
            "<p>HTML</p>",
            "Texte",
            attach_logo=False,
        )
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.to, ["user@example.org"])
        self.assertEqual(len(message.alternatives), 1)
        self.assertIn("HTML", message.alternatives[0][0])

    def test_notify_superadmins_registration(self):
        reg = make_registration()
        mail_svc.notify_superadmins_registration(reg)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("inscription", mail.outbox[0].subject.lower())
