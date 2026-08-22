"""Owner-requested team deletion, with an undo window.

A team is the foreign key of every tenant row, so this is the most destructive
thing a customer can do in the product — and until this landed there was no way
to do it at all, which left abandoned teams (and whatever they still serve
publicly) in the database forever.

Three rules are worth stating, because each was a decision:

1. **The delay is configuration, not policy.** ``SPEEDPY_TEAM_DELETION_DELAY_HOURS``
   0 deletes on the click; anything else schedules and stays undoable.
2. **A scheduled team keeps working.** It is not deactivated, because
   ``TeamViewMixin`` resolves ``is_active`` teams only — deactivating would hide
   the undo button behind a 404 from the one person allowed to press it.
3. **A live subscription blocks the deletion**, at every layer, right up to
   ``Team.delete()``. Deleting a team whose card is still charged is the one
   outcome that costs the customer real money.
"""

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from mainapp.models import (
    BillingSubscription,
    Team,
    TeamDeletionBlocked,
    TeamMembership,
    finalize_team_deletion,
    teams_due_for_deletion,
)
from mainapp.tasks.teams import purge_scheduled_team_deletions
from usermodel.models import User


def a_team(slug="acme"):
    return Team.objects.create(name=slug.title(), slug=slug)


def a_member(team, email, role):
    user = User.objects.create_user(email=email, password="pass123")
    TeamMembership.objects.create(team=team, user=user, role=role)
    return user


def a_subscription(team, status):
    return BillingSubscription.objects.create(
        billable_type="team",
        billable_id=str(team.pk),
        provider="paddle",
        provider_subscription_id=f"sub-{status}-{team.slug}",
        status=status,
    )


class DelayTests(TestCase):
    @override_settings(SPEEDPY_TEAM_DELETION_DELAY_HOURS=0)
    def test_zero_hours_deletes_on_the_spot(self):
        team = a_team()
        owner = a_member(team, "owner@example.com", "owner")

        self.assertEqual(team.request_deletion(by_user=owner), "deleted")
        self.assertFalse(Team.objects.filter(pk=team.pk).exists())

    @override_settings(
        SPEEDPY_TEAM_DELETION_DELAY_HOURS=0,
        SPEEDPY_TEAM_DELETION_CLEANUP_HOOKS=[
            "mainapp.tests.test_team_deletion.a_hook_that_records"
        ],
    )
    def test_zero_hours_still_runs_the_cleanup_hooks(self):
        """The first version called delete() directly here, so an immediate
        deletion left every stored object behind."""
        team = a_team()
        owner = a_member(team, "owner@example.com", "owner")
        team_id = str(team.pk)  # delete() clears the pk on the instance
        _RECORD.clear()

        team.request_deletion(by_user=owner)

        self.assertEqual(_RECORD, [team_id])

    @override_settings(SPEEDPY_TEAM_DELETION_DELAY_HOURS=48)
    def test_a_delay_schedules_it_and_leaves_the_team_working(self):
        team = a_team()
        owner = a_member(team, "owner@example.com", "owner")
        before = timezone.now()

        self.assertEqual(team.request_deletion(by_user=owner), "scheduled")

        team.refresh_from_db()
        self.assertTrue(team.is_deletion_scheduled)
        self.assertEqual(team.deletion_requested_by, owner)
        self.assertGreaterEqual(
            team.deletion_scheduled_at, before + timezone.timedelta(hours=48)
        )
        # Rule 2: still active, or the owner cannot reach the undo button.
        self.assertTrue(team.is_active)

    @override_settings(SPEEDPY_TEAM_DELETION_DELAY_HOURS=-5)
    def test_a_negative_setting_is_read_as_zero(self):
        self.assertEqual(Team.deletion_delay_hours(), 0)

    @override_settings(SPEEDPY_TEAM_DELETION_DELAY_HOURS=24)
    def test_a_second_request_does_not_move_the_deadline(self):
        """Otherwise a double-click quietly buys another day."""
        team = a_team()
        owner = a_member(team, "owner@example.com", "owner")
        team.request_deletion(by_user=owner)
        first = Team.objects.get(pk=team.pk).deletion_scheduled_at

        self.assertEqual(team.request_deletion(by_user=owner), "already_scheduled")
        self.assertEqual(Team.objects.get(pk=team.pk).deletion_scheduled_at, first)

    @override_settings(SPEEDPY_TEAM_DELETION_DELAY_HOURS=24)
    def test_undo_clears_every_field(self):
        team = a_team()
        owner = a_member(team, "owner@example.com", "owner")
        team.request_deletion(by_user=owner)

        self.assertTrue(team.cancel_scheduled_deletion(by_user=owner))

        team.refresh_from_db()
        self.assertIsNone(team.deletion_scheduled_at)
        self.assertIsNone(team.deletion_requested_at)
        self.assertIsNone(team.deletion_requested_by)

    def test_undo_is_idempotent(self):
        team = a_team()
        self.assertFalse(team.cancel_scheduled_deletion())


class BillingGuardTests(TestCase):
    """Cancelling is enough; we do not wait for the paid period to end."""

    def setUp(self):
        self.team = a_team()
        self.owner = a_member(self.team, "owner@example.com", "owner")

    def test_an_active_subscription_blocks(self):
        a_subscription(self.team, BillingSubscription.STATUS_ACTIVE)

        with self.assertRaises(TeamDeletionBlocked):
            self.team.request_deletion(by_user=self.owner)

    def test_past_due_blocks_because_the_card_can_still_be_retried(self):
        a_subscription(self.team, BillingSubscription.STATUS_PAST_DUE)
        self.assertIsNotNone(self.team.deletion_blocked_reason())

    def test_paused_blocks_because_it_can_resume(self):
        a_subscription(self.team, BillingSubscription.STATUS_PAUSED)
        self.assertIsNotNone(self.team.deletion_blocked_reason())

    def test_canceled_does_not_block_even_inside_the_paid_period(self):
        sub = a_subscription(self.team, BillingSubscription.STATUS_CANCELED)
        sub.cancellation_effective_at = timezone.now() + timezone.timedelta(days=20)
        sub.save()

        self.assertIsNone(self.team.deletion_blocked_reason())

    def test_expired_does_not_block(self):
        a_subscription(self.team, BillingSubscription.STATUS_EXPIRED)
        self.assertIsNone(self.team.deletion_blocked_reason())

    def test_one_live_row_among_several_is_enough_to_block(self):
        a_subscription(self.team, BillingSubscription.STATUS_EXPIRED)
        a_subscription(self.team, BillingSubscription.STATUS_ACTIVE)

        self.assertIsNotNone(self.team.deletion_blocked_reason())

    @override_settings(SPEEDPY_BILLING_ENABLED=False)
    def test_the_guard_ignores_the_billing_feature_flag(self):
        """The flag says whether we SELL; the provider charges regardless."""
        a_subscription(self.team, BillingSubscription.STATUS_ACTIVE)
        self.assertIsNotNone(self.team.deletion_blocked_reason())

    def test_delete_itself_refuses(self):
        """The backstop: admin, a shell and the purge task all arrive here."""
        a_subscription(self.team, BillingSubscription.STATUS_ACTIVE)

        with self.assertRaises(TeamDeletionBlocked):
            self.team.delete()
        self.assertTrue(Team.objects.filter(pk=self.team.pk).exists())


@override_settings(SPEEDPY_TEAM_DELETION_DELAY_HOURS=24)
class PurgeTaskTests(TestCase):
    def setUp(self):
        self.team = a_team()
        self.owner = a_member(self.team, "owner@example.com", "owner")

    def _schedule_in_the_past(self):
        self.team.request_deletion(by_user=self.owner)
        Team.objects.filter(pk=self.team.pk).update(
            deletion_scheduled_at=timezone.now() - timezone.timedelta(minutes=1)
        )

    def test_a_team_still_inside_its_window_is_left_alone(self):
        self.team.request_deletion(by_user=self.owner)

        self.assertEqual(teams_due_for_deletion().count(), 0)
        purge_scheduled_team_deletions()
        self.assertTrue(Team.objects.filter(pk=self.team.pk).exists())

    def test_a_team_past_its_window_is_deleted(self):
        self._schedule_in_the_past()

        purge_scheduled_team_deletions()

        self.assertFalse(Team.objects.filter(pk=self.team.pk).exists())

    def test_a_subscription_that_appeared_during_the_window_stops_the_purge(self):
        """The re-check is the point: a webhook can revive a subscription while
        the team sits in its undo window."""
        self._schedule_in_the_past()
        a_subscription(self.team, BillingSubscription.STATUS_ACTIVE)

        purge_scheduled_team_deletions()

        team = Team.objects.get(pk=self.team.pk)
        # Kept AND still scheduled, so the owner sees why and the task retries.
        self.assertTrue(team.is_deletion_scheduled)

    def test_a_failing_cleanup_hook_keeps_the_team_and_the_schedule(self):
        """Through the task, because the rollback is the point: the hook may
        already have deleted rows before it failed, and those writes have to go
        back too. Catching the error inside the transaction would commit them
        while reporting that the team was kept for a retry."""
        self._schedule_in_the_past()

        with override_settings(
            SPEEDPY_TEAM_DELETION_CLEANUP_HOOKS=[
                "mainapp.tests.test_team_deletion.a_hook_that_deletes_then_fails"
            ]
        ):
            purge_scheduled_team_deletions()

        team = Team.objects.get(pk=self.team.pk)
        self.assertTrue(team.is_deletion_scheduled)
        # The row the hook deleted before it failed is back.
        self.assertTrue(
            TeamMembership.objects.filter(team=team, user=self.owner).exists()
        )

    def test_the_finalizer_refuses_a_team_that_is_not_due(self):
        """It is called "finalize" — a future caller must not be able to use it
        to skip the undo window."""
        self.team.request_deletion(by_user=self.owner)

        with self.assertRaises(ValueError):
            finalize_team_deletion(Team.objects.get(pk=self.team.pk))

    def test_the_finalizer_refuses_a_team_that_was_never_scheduled(self):
        with self.assertRaises(ValueError):
            finalize_team_deletion(Team.objects.get(pk=self.team.pk))

    def test_cleanup_hooks_run_before_the_rows_go(self):
        self._schedule_in_the_past()
        seen = []

        global _RECORD
        _RECORD = seen
        with override_settings(
            SPEEDPY_TEAM_DELETION_CLEANUP_HOOKS=[
                "mainapp.tests.test_team_deletion.a_hook_that_records"
            ]
        ):
            purge_scheduled_team_deletions()

        self.assertEqual(seen, [str(self.team.pk)])
        self.assertFalse(Team.objects.filter(pk=self.team.pk).exists())

    @override_settings(SPEEDPY_TEAMS_ENABLED=False)
    def test_the_task_no_ops_when_teams_are_disabled(self):
        self._schedule_in_the_past()

        purge_scheduled_team_deletions()

        self.assertTrue(Team.objects.filter(pk=self.team.pk).exists())


_RECORD = []


def a_hook_that_fails(team):
    raise RuntimeError("object storage is unreachable")


def a_hook_that_deletes_then_fails(team):
    """Like a real teardown: it removes some rows, then hits a storage error."""
    from mainapp.models import TeamMembership

    TeamMembership.objects.filter(team=team).delete()
    raise RuntimeError("object storage is unreachable")


def a_hook_that_records(team):
    # Proves the hook sees a team whose rows are still there to look at.
    assert Team.objects.filter(pk=team.pk).exists()
    _RECORD.append(str(team.pk))


@override_settings(SPEEDPY_TEAM_DELETION_DELAY_HOURS=24)
class ViewTests(TestCase):
    def setUp(self):
        self.team = a_team()
        self.owner = a_member(self.team, "owner@example.com", "owner")
        self.admin = a_member(self.team, "admin@example.com", "admin")
        self.member = a_member(self.team, "member@example.com", "member")
        self.url = reverse("team_delete", kwargs={"team_id": self.team.pk})
        self.cancel_url = reverse(
            "team_delete_cancel", kwargs={"team_id": self.team.pk}
        )

    def test_an_owner_can_schedule(self):
        self.client.force_login(self.owner)

        response = self.client.post(self.url)

        self.assertEqual(response.status_code, 302)
        self.assertTrue(Team.objects.get(pk=self.team.pk).is_deletion_scheduled)

    def test_an_admin_may_not(self):
        """Managing a team and ending it are different powers."""
        self.client.force_login(self.admin)

        response = self.client.post(self.url)

        self.assertEqual(response.status_code, 403)
        self.assertFalse(Team.objects.get(pk=self.team.pk).is_deletion_scheduled)

    def test_a_member_may_not(self):
        self.client.force_login(self.member)
        self.assertEqual(self.client.post(self.url).status_code, 403)

    def test_a_stranger_gets_a_404_not_a_403(self):
        """404 rather than 403: whether a team exists is not public."""
        stranger = User.objects.create_user(
            email="nobody@example.com", password="pass123"
        )
        self.client.force_login(stranger)

        self.assertEqual(self.client.post(self.url).status_code, 404)

    def test_get_does_not_delete(self):
        """A link prefetcher must not be able to end a team."""
        self.client.force_login(self.owner)

        self.assertEqual(self.client.get(self.url).status_code, 405)
        self.assertFalse(Team.objects.get(pk=self.team.pk).is_deletion_scheduled)

    def test_a_second_owner_can_undo_the_first_owners_request(self):
        other_owner = a_member(self.team, "owner2@example.com", "owner")
        self.client.force_login(self.owner)
        self.client.post(self.url)

        self.client.force_login(other_owner)
        self.client.post(self.cancel_url)

        self.assertFalse(Team.objects.get(pk=self.team.pk).is_deletion_scheduled)

    def test_a_blocked_deletion_reports_the_reason(self):
        a_subscription(self.team, BillingSubscription.STATUS_ACTIVE)
        self.client.force_login(self.owner)

        response = self.client.post(self.url, follow=True)

        self.assertFalse(Team.objects.get(pk=self.team.pk).is_deletion_scheduled)
        self.assertContains(response, "still has a live subscription")

    @override_settings(SPEEDPY_TEAM_DELETION_DELAY_HOURS=0)
    def test_with_no_delay_the_button_deletes(self):
        self.client.force_login(self.owner)

        self.client.post(self.url)

        self.assertFalse(Team.objects.filter(pk=self.team.pk).exists())


@override_settings(SPEEDPY_TEAM_DELETION_DELAY_HOURS=12)
class SettingsPageTests(TestCase):
    def setUp(self):
        self.team = a_team()
        self.owner = a_member(self.team, "owner@example.com", "owner")
        self.admin = a_member(self.team, "admin@example.com", "admin")
        self.url = reverse("team_settings", kwargs={"team_id": self.team.pk})

    def test_the_copy_names_the_configured_delay(self):
        self.client.force_login(self.owner)

        response = self.client.get(self.url)

        self.assertContains(response, "deleted after")
        self.assertContains(response, "12 hours")

    @override_settings(SPEEDPY_TEAM_DELETION_DELAY_HOURS=1)
    def test_the_copy_is_singular_for_one_hour(self):
        self.client.force_login(self.owner)

        response = self.client.get(self.url)

        self.assertContains(response, "1 hour")
        self.assertNotContains(response, "1 hours")

    @override_settings(SPEEDPY_TEAM_DELETION_DELAY_HOURS=0)
    def test_the_copy_says_immediately_when_there_is_no_delay(self):
        self.client.force_login(self.owner)

        response = self.client.get(self.url)

        self.assertContains(response, "deleted immediately")

    def test_the_undo_block_replaces_the_delete_block(self):
        self.team.request_deletion(by_user=self.owner)
        self.client.force_login(self.owner)

        response = self.client.get(self.url)

        self.assertContains(response, "Undo scheduled deletion")
        self.assertNotContains(response, "Schedule deletion")

    def test_an_admin_sees_no_danger_zone(self):
        self.client.force_login(self.admin)

        response = self.client.get(self.url)

        self.assertNotContains(response, "Delete this team")


@override_settings(
    SPEEDPY_UNCONFIRMED_ACCOUNT_PURGE_DAYS=7,
    SPEEDPY_UNCONFIRMED_ACCOUNT_PURGE_HOOKS=[
        "mainapp.models.teams.delete_sole_member_teams"
    ],
)
class PurgedAccountTeamTests(TestCase):
    """The team side of an unconfirmed-account purge.

    Team has no foreign key to a user — membership is the only link, and that
    cascades — so without this hook every purged signup would leave its
    auto-provisioned team behind for good, with nobody able to reach it.
    """

    def _an_unconfirmed_signup(self, email, days_ago=30):
        from allauth.account.models import EmailAddress

        user = User.objects.create_user(email=email, password="pass123")
        User.objects.filter(pk=user.pk).update(
            date_joined=timezone.now() - timezone.timedelta(days=days_ago)
        )
        EmailAddress.objects.create(user=user, email=email, verified=False)
        return User.objects.get(pk=user.pk)

    def test_the_signups_own_team_goes_with_it(self):
        from speedpycom.services.account_purge import UnconfirmedAccountPurge

        user = self._an_unconfirmed_signup("never@example.com")
        team = a_team("theirs")
        TeamMembership.objects.create(team=team, user=user, role="owner")

        UnconfirmedAccountPurge().run()

        self.assertFalse(Team.objects.filter(pk=team.pk).exists())
        self.assertFalse(User.objects.filter(pk=user.pk).exists())

    def test_a_shared_team_survives_and_keeps_its_other_members(self):
        """It is somebody else's team now. Losing the membership is all that
        should happen to it."""
        from speedpycom.services.account_purge import UnconfirmedAccountPurge

        user = self._an_unconfirmed_signup("never@example.com")
        team = a_team("shared")
        TeamMembership.objects.create(team=team, user=user, role="owner")
        colleague = a_member(team, "real@example.com", "owner")

        UnconfirmedAccountPurge().run()

        self.assertTrue(Team.objects.filter(pk=team.pk).exists())
        self.assertTrue(
            TeamMembership.objects.filter(team=team, user=colleague).exists()
        )

    def test_a_still_billed_team_keeps_the_account_too(self):
        """A paid team is not something to remove on a timer, so the whole
        account is left for a human to look at."""
        from speedpycom.services.account_purge import UnconfirmedAccountPurge

        user = self._an_unconfirmed_signup("never@example.com")
        team = a_team("paid")
        TeamMembership.objects.create(team=team, user=user, role="owner")
        a_subscription(team, BillingSubscription.STATUS_ACTIVE)

        report = UnconfirmedAccountPurge().run()

        self.assertEqual(report["failed"], 1)
        self.assertTrue(Team.objects.filter(pk=team.pk).exists())
        self.assertTrue(User.objects.filter(pk=user.pk).exists())

    def test_the_teams_cleanup_hooks_run(self):
        """It goes through the finalizer, so a project's storage teardown is not
        skipped just because the trigger was an account purge."""
        from speedpycom.services.account_purge import UnconfirmedAccountPurge

        user = self._an_unconfirmed_signup("never@example.com")
        team = a_team("theirs")
        TeamMembership.objects.create(team=team, user=user, role="owner")
        _RECORD.clear()

        with override_settings(
            SPEEDPY_TEAM_DELETION_CLEANUP_HOOKS=[
                "mainapp.tests.test_team_deletion.a_hook_that_records"
            ]
        ):
            UnconfirmedAccountPurge().run()

        self.assertEqual(_RECORD, [str(team.pk)])


@override_settings(SPEEDPY_TEAM_DELETION_DELAY_HOURS=0)
class ImmediateDeletionIsStillDurableTests(TestCase):
    """With no delay the team is still MARKED before it is deleted.

    The mark is what shuts the billing doors and what lets the hourly task
    finish the job if this attempt cannot. Without it, a zero-hour deletion that
    failed part way left no record that anybody had asked for it.
    """

    def setUp(self):
        self.team = a_team()
        self.owner = a_member(self.team, "owner@example.com", "owner")

    def test_a_failed_last_step_leaves_the_team_marked_not_untouched(self):
        with override_settings(
            SPEEDPY_TEAM_DELETION_CLEANUP_HOOKS=[
                "mainapp.tests.test_team_deletion.a_hook_that_fails"
            ]
        ):
            self.assertEqual(
                self.team.request_deletion(by_user=self.owner), "deleting"
            )

        team = Team.objects.get(pk=self.team.pk)
        self.assertTrue(team.is_deletion_scheduled)

    def test_the_hourly_task_then_finishes_it(self):
        with override_settings(
            SPEEDPY_TEAM_DELETION_CLEANUP_HOOKS=[
                "mainapp.tests.test_team_deletion.a_hook_that_fails"
            ]
        ):
            self.team.request_deletion(by_user=self.owner)

        purge_scheduled_team_deletions()  # hook no longer failing

        self.assertFalse(Team.objects.filter(pk=self.team.pk).exists())

    def test_a_happy_path_still_deletes_at_once(self):
        self.assertEqual(self.team.request_deletion(by_user=self.owner), "deleted")
        self.assertFalse(Team.objects.filter(pk=self.team.pk).exists())
