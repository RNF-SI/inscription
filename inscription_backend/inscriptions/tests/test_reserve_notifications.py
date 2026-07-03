from unittest.mock import patch

from django.core import mail
from django.test import TestCase, override_settings

from inscriptions.models import Notification
from inscriptions.services import email_templates as tpl
from inscriptions.services import reserve_notifications as reserve_notify
from inscriptions.tests.helpers import make_profile, make_reserve
from inscriptions.user_identity import UserInfo


def _info(profile) -> UserInfo:
    return UserInfo(
        sub=profile.keycloak_sub,
        email=profile.email,
        username=profile.username,
        first_name=profile.first_name,
        last_name=profile.last_name,
    )


class ReserveEmailTemplateTests(TestCase):
    def test_referent_request_superadmin_email(self):
        applicant = _info(make_profile(first_name="Jean", last_name="Dupont", email="jean@test.local"))
        reserve = make_reserve(area_code="RNN01", area_name="Réserve test")
        subject, html, _plain = tpl.reserve_referent_request_superadmin_email(applicant=applicant, reserve=reserve)
        self.assertIn("référent", subject.lower())
        self.assertIn("RNN01", html)
        self.assertIn("/admin", html)

    def test_new_member_referent_email(self):
        member = _info(make_profile(first_name="Marie", last_name="Martin", email="marie@test.local"))
        reserve = make_reserve(area_code="RNN02", area_name="Réserve deux")
        subject, html, _plain = tpl.reserve_new_member_referent_email(
            reserve=reserve,
            member=member,
            referent_first_name="Paul",
        )
        self.assertIn("membre", subject.lower())
        self.assertIn("marie@test.local", html)
        self.assertIn("/admin", html)


@override_settings(SUPERADMIN_NOTIFY_EMAILS=["admin@test.local"], KEYCLOAK_SYNC_ENABLED=False)
class ReserveNotificationServiceTests(TestCase):
    def setUp(self):
        mail.outbox = []

    @patch("inscriptions.services.reserve_notifications.list_super_admin_subs")
    def test_notify_referent_request_created_notifies_super_admins(self, list_super):
        list_super.return_value = ["super-sub"]
        applicant = _info(make_profile(sub="user-sub", email="user@test.local", first_name="Alice"))
        reserve = make_reserve()
        reserve_notify.notify_referent_request_created(applicant, reserve)
        self.assertTrue(Notification.objects.filter(user_sub="super-sub", title__icontains="référent").exists())
        self.assertEqual(len(mail.outbox), 1)

    @patch("inscriptions.services.reserve_notifications._referent_group_members")
    def test_notify_referents_new_member(self, members_mock):
        referent_sub = "ref-sub"
        member = _info(make_profile(sub="member-sub", email="member@test.local", first_name="Bob"))
        reserve = make_reserve()
        members_mock.return_value = [
            {"id": referent_sub, "email": "referent@test.local", "firstName": "Rémi"},
        ]
        reserve_notify.notify_referents_new_member(member, reserve)
        self.assertTrue(Notification.objects.filter(user_sub=referent_sub).exists())
        self.assertEqual(len(mail.outbox), 1)
