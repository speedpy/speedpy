"""Purging signups that never confirmed an email address.

Deleting user accounts on a timer is dangerous, so most of what is worth
testing here is what the purge REFUSES to touch. Each exclusion is a real
account somebody would otherwise lose:

* a person who confirmed and is simply idle;
* a person who ever signed in (their address may look unverified now, but the
  account is established);
* staff and superusers;
* a user created by hand in the admin, who often has no ``EmailAddress`` row at
  all and would match a bare "has no verified address" test;
* anybody still inside the window — which must be longer than allauth's
  confirmation-link lifetime, or the purge races the last valid click.
"""

from unittest import mock

from allauth.account.models import EmailAddress
from django.test import TestCase, override_settings
from django.utils import timezone

from speedpycom.services.account_purge import (
    AccountPurgeCleanupFailed,
    UnconfirmedAccountPurge,
    get_purge,
)
from usermodel.models import User

PURGE_ON = {"SPEEDPY_UNCONFIRMED_ACCOUNT_PURGE_DAYS": 7}


def a_signup(email, days_ago=30, verified=False, with_address=True, **flags):
    user = User.objects.create_user(email=email, password="pass123", **flags)
    User.objects.filter(pk=user.pk).update(
        date_joined=timezone.now() - timezone.timedelta(days=days_ago)
    )
    if with_address:
        EmailAddress.objects.create(
            user=user, email=email, primary=True, verified=verified
        )
    user.refresh_from_db()
    return user


@override_settings(SPEEDPY_UNCONFIRMED_ACCOUNT_PURGE_HOOKS=[], **PURGE_ON)
class SelectionTests(TestCase):
    def matched(self):
        return list(UnconfirmedAccountPurge().queryset())

    def test_an_old_unconfirmed_signup_matches(self):
        user = a_signup("never@example.com")
        self.assertEqual(self.matched(), [user])

    def test_a_confirmed_account_is_never_touched(self):
        a_signup("fine@example.com", verified=True)
        self.assertEqual(self.matched(), [])

    def test_an_account_that_ever_signed_in_is_never_touched(self):
        """Whatever its addresses look like now, somebody got in with it."""
        user = a_signup("been@example.com")
        User.objects.filter(pk=user.pk).update(last_login=timezone.now())

        self.assertEqual(self.matched(), [])

    def test_staff_and_superusers_are_never_touched(self):
        a_signup("staff@example.com", is_staff=True)
        a_signup("root@example.com", is_superuser=True)

        self.assertEqual(self.matched(), [])

    def test_an_account_with_no_email_address_row_is_never_touched(self):
        """A user made by hand in the admin looks like this. It is not a signup,
        so it is none of this purge's business."""
        a_signup("byhand@example.com", with_address=False)

        self.assertEqual(self.matched(), [])

    def test_an_inactive_account_is_left_to_whoever_deactivated_it(self):
        a_signup("off@example.com", is_active=False)
        self.assertEqual(self.matched(), [])

    def test_a_signup_inside_the_window_is_left_alone(self):
        a_signup("fresh@example.com", days_ago=6)
        self.assertEqual(self.matched(), [])

    def test_the_window_is_the_configured_number_of_days(self):
        a_signup("eight@example.com", days_ago=8)

        with override_settings(SPEEDPY_UNCONFIRMED_ACCOUNT_PURGE_DAYS=30):
            self.assertEqual(list(UnconfirmedAccountPurge().queryset()), [])
        self.assertEqual(len(self.matched()), 1)

    def test_a_second_unverified_address_does_not_save_an_account(self):
        user = a_signup("two@example.com")
        EmailAddress.objects.create(
            user=user, email="other@example.com", verified=False
        )

        self.assertEqual(self.matched(), [user])

    def test_one_verified_address_out_of_two_saves_it(self):
        user = a_signup("two@example.com")
        EmailAddress.objects.create(user=user, email="ok@example.com", verified=True)

        self.assertEqual(self.matched(), [])


@override_settings(SPEEDPY_UNCONFIRMED_ACCOUNT_PURGE_HOOKS=[], **PURGE_ON)
class RunTests(TestCase):
    def test_it_deletes_what_it_matched(self):
        user = a_signup("never@example.com")

        report = UnconfirmedAccountPurge().run()

        self.assertEqual(report["purged"], 1)
        self.assertFalse(User.objects.filter(pk=user.pk).exists())

    def test_a_dry_run_deletes_nothing(self):
        user = a_signup("never@example.com")

        report = UnconfirmedAccountPurge().run(dry_run=True)

        self.assertEqual(report["matched"], 1)
        self.assertEqual(report["purged"], 0)
        self.assertTrue(User.objects.filter(pk=user.pk).exists())

    @override_settings(SPEEDPY_UNCONFIRMED_ACCOUNT_PURGE_DAYS=0)
    def test_zero_days_means_off(self):
        """The default. A boilerplate must not delete accounts unasked."""
        user = a_signup("never@example.com")

        report = UnconfirmedAccountPurge().run()

        self.assertFalse(report["enabled"])
        self.assertTrue(User.objects.filter(pk=user.pk).exists())

    @override_settings(
        SPEEDPY_UNCONFIRMED_ACCOUNT_PURGE_HOOKS=[
            "speedpycom.tests.test_account_purge.a_hook_that_fails"
        ]
    )
    def test_a_failing_hook_keeps_the_account_for_the_next_run(self):
        user = a_signup("never@example.com")

        report = UnconfirmedAccountPurge().run()

        self.assertEqual(report["failed"], 1)
        self.assertEqual(report["purged"], 0)
        self.assertTrue(User.objects.filter(pk=user.pk).exists())

    @override_settings(
        SPEEDPY_UNCONFIRMED_ACCOUNT_PURGE_HOOKS=[
            "speedpycom.tests.test_account_purge.a_hook_that_deletes_then_fails"
        ]
    )
    def test_a_failing_hook_rolls_back_what_it_had_already_deleted(self):
        user = a_signup("never@example.com")

        UnconfirmedAccountPurge().run()

        self.assertTrue(EmailAddress.objects.filter(user=user).exists())

    def test_one_failure_does_not_stop_the_rest(self):
        a_signup("one@example.com")
        a_signup("two@example.com")

        with mock.patch.object(
            UnconfirmedAccountPurge,
            "purge_user",
            side_effect=[AccountPurgeCleanupFailed("nope"), True],
        ):
            report = UnconfirmedAccountPurge().run()

        self.assertEqual(report["failed"], 1)
        self.assertEqual(report["purged"], 1)

    def test_the_log_line_carries_no_address(self):
        """It is an audit line about somebody who is gone; the domain is enough."""
        a_signup("private@example.com")

        with self.assertLogs("speedpycom.services.account_purge", "WARNING") as logs:
            UnconfirmedAccountPurge().run()

        self.assertNotIn("private@example.com", "".join(logs.output))
        self.assertIn("example.com", "".join(logs.output))


def a_hook_that_fails(user):
    raise RuntimeError("could not tear down the team")


def a_hook_that_deletes_then_fails(user):
    EmailAddress.objects.filter(user=user).delete()
    raise RuntimeError("could not tear down the team")


class SubclassingTests(TestCase):
    """The supported way to change this: subclass, do not edit."""

    @override_settings(
        SPEEDPY_UNCONFIRMED_ACCOUNT_PURGE_CLASS=(
            "speedpycom.tests.test_account_purge.NeverPurgeAnything"
        ),
        **PURGE_ON,
    )
    def test_the_configured_class_is_used(self):
        a_signup("never@example.com")

        report = get_purge().run()

        self.assertEqual(report["matched"], 0)

    @override_settings(**PURGE_ON)
    def test_ours_is_the_default(self):
        self.assertIsInstance(get_purge(), UnconfirmedAccountPurge)


class NeverPurgeAnything(UnconfirmedAccountPurge):
    def queryset(self):
        return super().queryset().none()


@override_settings(SPEEDPY_UNCONFIRMED_ACCOUNT_PURGE_HOOKS=[], **PURGE_ON)
class TaskAndCommandTests(TestCase):
    def test_the_task_runs_the_purge(self):
        from speedpycom.tasks import purge_unconfirmed_accounts

        user = a_signup("never@example.com")

        purge_unconfirmed_accounts()

        self.assertFalse(User.objects.filter(pk=user.pk).exists())

    @override_settings(SPEEDPY_UNCONFIRMED_ACCOUNT_PURGE_DAYS=0)
    def test_the_task_is_a_no_op_when_off(self):
        from speedpycom.tasks import purge_unconfirmed_accounts

        user = a_signup("never@example.com")

        self.assertEqual(purge_unconfirmed_accounts(), "Purge disabled")
        self.assertTrue(User.objects.filter(pk=user.pk).exists())

    def test_the_command_dry_run_lists_and_deletes_nothing(self):
        from io import StringIO

        from django.core.management import call_command

        user = a_signup("never@example.com")
        out = StringIO()

        call_command("purge_unconfirmed_accounts", "--dry-run", stdout=out)

        self.assertIn("never@example.com", out.getvalue())
        self.assertTrue(User.objects.filter(pk=user.pk).exists())

    def test_the_command_days_flag_overrides_the_setting(self):
        from io import StringIO

        from django.core.management import call_command

        a_signup("never@example.com", days_ago=10)
        out = StringIO()

        call_command("purge_unconfirmed_accounts", "--dry-run", "--days", "60", stdout=out)

        self.assertNotIn("never@example.com", out.getvalue())
