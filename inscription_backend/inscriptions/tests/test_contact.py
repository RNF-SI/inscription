"""Formulaire de contact mutualisé (/api/contact/)."""

from unittest.mock import patch

from django.core import mail
from django.test import override_settings

from inscriptions.tests.helpers import BaseApiTestCase

SUPPORT = "support@reserves-naturelles.org"
SUPPORT_AUTRE = "support-geonature@reserves-naturelles.org"

PAYLOAD = {
    "email": "usager@example.org",
    "name": "Jean Dupont",
    "subject": "Problème de connexion",
    "message": "Je n'arrive pas à me connecter depuis ce matin.",
    "app_name": "Plateformes RNF",
}


@override_settings(CONTACT_ALLOWED_RECIPIENTS=[SUPPORT, SUPPORT_AUTRE])
class ContactApiTests(BaseApiTestCase):
    def setUp(self):
        super().setUp()
        # Le throttle « contact » vit dans le cache, partagé par tout le processus :
        # sans purge, les tests se limitent mutuellement selon leur ordre.
        from django.core.cache import cache

        cache.clear()
        self.addCleanup(cache.clear)

    def post(self, **overrides):
        payload = {**PAYLOAD, **overrides}
        return self.client.post("/api/contact/", payload, format="json")

    def test_sends_message_to_the_first_allowed_recipient_by_default(self):
        response = self.post()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        sent = mail.outbox[0]
        self.assertEqual(sent.to, [SUPPORT])
        self.assertIn("Plateformes RNF", sent.subject)
        self.assertIn("Problème de connexion", sent.subject)

    def test_reply_to_is_the_sender_so_support_answers_the_user(self):
        self.post()
        self.assertEqual(mail.outbox[0].reply_to, ["usager@example.org"])

    def test_message_body_reaches_the_support_mailbox(self):
        self.post()
        self.assertIn("Je n'arrive pas à me connecter", mail.outbox[0].body)

    def test_mail_is_plain_text_without_branding(self):
        """Le destinataire est une boîte Zammad : pas d'habillage HTML ni de logo."""
        self.post()
        sent = mail.outbox[0]
        self.assertEqual(getattr(sent, "alternatives", []), [])
        self.assertEqual(sent.attachments, [])
        self.assertNotIn("<html", sent.body.lower())
        self.assertNotIn("Réserves Naturelles de France", sent.body)

    def test_mail_carries_platform_subject_and_content_only(self):
        self.post()
        body = mail.outbox[0].body
        self.assertIn("Plateforme : Plateformes RNF", body)
        self.assertIn("Jean Dupont <usager@example.org>", body)
        self.assertIn("Je n'arrive pas à me connecter depuis ce matin.", body)
        self.assertEqual(len(body.splitlines()), 4)

    def test_app_can_target_another_allowed_mailbox(self):
        response = self.post(recipient=SUPPORT_AUTRE)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(mail.outbox[0].to, [SUPPORT_AUTRE])

    def test_recipient_matching_is_case_insensitive(self):
        response = self.post(recipient=SUPPORT_AUTRE.upper())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(mail.outbox[0].to, [SUPPORT_AUTRE])

    def test_zammad_customer_header_carries_the_real_sender(self):
        """Zammad rattache le ticket à l'expéditeur SMTP (le domaine RNF) : sans cet
        en-tête, tous les tickets auraient le même client."""
        self.post()
        self.assertEqual(
            mail.outbox[0].extra_headers.get("X-Zammad-Customer-Email"),
            "usager@example.org",
        )

    def test_header_cannot_be_injected_with_a_crafted_email(self):
        """Un e-mail porteur d'un saut de ligne injecterait des en-têtes arbitraires."""
        response = self.post(email="pirate@example.org\nX-Zammad-Ticket-Priority: 3 high")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(mail.outbox, [])

    # --- Garde-fou anti-relais : le cœur du sujet ---------------------------

    def test_refuses_a_recipient_outside_the_allowlist(self):
        """Sans ce refus, la route serait un relais SMTP ouvert."""
        response = self.post(recipient="attaquant@example.com")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(mail.outbox, [])

    def test_refuses_a_recipient_on_a_lookalike_domain(self):
        response = self.post(recipient="support@reserves-naturelles.org.evil.com")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(mail.outbox, [])

    @override_settings(CONTACT_ALLOWED_RECIPIENTS=[])
    def test_route_is_disabled_when_no_recipient_is_configured(self):
        response = self.post()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(mail.outbox, [])

    # --- Validation --------------------------------------------------------

    def test_rejects_invalid_sender_email(self):
        self.assertEqual(self.post(email="pas-un-email").status_code, 400)
        self.assertEqual(mail.outbox, [])

    def test_rejects_empty_subject(self):
        self.assertEqual(self.post(subject="   ").status_code, 400)

    def test_rejects_too_short_message(self):
        self.assertEqual(self.post(message="court").status_code, 400)

    def test_honeypot_field_blocks_bots(self):
        response = self.post(website="http://spam.example")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(mail.outbox, [])

    # --- Accès et pannes ---------------------------------------------------

    def test_endpoint_is_reachable_without_a_session(self):
        """Le lien « Contacter le support » s'affiche aussi pour un visiteur anonyme."""
        self.assertEqual(self.post().status_code, 200)

    def test_returns_502_when_smtp_fails(self):
        with patch(
            "inscriptions.services.contact.send_plain_email",
            side_effect=OSError("smtp down"),
        ):
            response = self.post()
        self.assertEqual(response.status_code, 502)


@override_settings(CONTACT_ALLOWED_RECIPIENTS=[SUPPORT])
class ContactThrottleTests(BaseApiTestCase):
    def setUp(self):
        super().setUp()
        from django.core.cache import cache

        cache.clear()
        self.addCleanup(cache.clear)

    def test_repeated_submissions_are_throttled(self):
        from rest_framework.throttling import SimpleRateThrottle

        # DRF fige THROTTLE_RATES comme attribut de classe à l'import : override_settings
        # sur REST_FRAMEWORK n'atteint pas le throttle, on patche le dict lui-même.
        with patch.dict(SimpleRateThrottle.THROTTLE_RATES, {"contact": "2/hour"}):
            codes = [
                self.client.post("/api/contact/", PAYLOAD, format="json").status_code for _ in range(3)
            ]
        self.assertEqual(codes[:2], [200, 200])
        self.assertEqual(codes[2], 429)

    def test_throttle_is_scoped_to_contact_only(self):
        """La limite ne doit pas s'appliquer aux autres routes publiques."""
        from rest_framework.throttling import SimpleRateThrottle

        with patch.dict(SimpleRateThrottle.THROTTLE_RATES, {"contact": "1/hour"}):
            self.client.post("/api/contact/", PAYLOAD, format="json")
            self.assertEqual(
                self.client.post("/api/contact/", PAYLOAD, format="json").status_code, 429
            )
            self.assertEqual(self.client.get("/api/applications/").status_code, 200)
