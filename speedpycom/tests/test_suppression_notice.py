"""The in-app notice that we stopped emailing an address .

The gap: when we suppress an address we stop sending to it, and the only channel
we would normally use to say so is email — to the address we just stopped using.
Without this page a real customer whose mailbox filled up or whose domain
expired simply goes silent, with no password resets and no explanation.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from allauth.account.models import EmailAddress

from speedpycom.models import SuppressedEmail
from speedpycom.services import email_events
from speedpycom.templatetags.suppression import suppressed_addresses_for

User = get_user_model()


class SuppressionNoticeTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="owner@example.com", password="Passw0rd!x"
        )
        EmailAddress.objects.create(
            user=self.user, email="owner@example.com", verified=True, primary=True
        )
        self.client.force_login(self.user)
        self.url = reverse("account_email")

    def test_no_notice_when_nothing_is_suppressed(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "We stopped sending email to")

    def test_a_hard_bounce_shows_the_notice(self):
        email_events.suppress("owner@example.com", SuppressedEmail.Reason.HARD_BOUNCE)
        response = self.client.get(self.url)
        self.assertContains(response, "We stopped sending email to")
        self.assertContains(response, "owner@example.com")
        self.assertContains(response, "messages kept failing")
        # The consequence most likely to strand somebody must be spelled out.
        self.assertContains(response, "password reset")

    def test_a_complaint_shows_different_wording(self):
        """"Reported as spam" and "kept failing" are different situations, and
        telling somebody their mailbox is broken when they hit the spam button
        would be wrong."""
        email_events.suppress("owner@example.com", SuppressedEmail.Reason.COMPLAINT)
        response = self.client.get(self.url)
        self.assertContains(response, "reported our email as spam")
        self.assertNotContains(response, "messages kept failing")

    def test_a_secondary_address_is_covered(self):
        """A person can have a working primary and a dead old address."""
        EmailAddress.objects.create(
            user=self.user, email="old@example.com", verified=True
        )
        email_events.suppress("old@example.com", SuppressedEmail.Reason.HARD_BOUNCE)
        response = self.client.get(self.url)
        self.assertContains(response, "old@example.com")

    def test_a_released_address_shows_no_notice(self):
        email_events.suppress("owner@example.com", SuppressedEmail.Reason.HARD_BOUNCE)
        email_events.release("owner@example.com")
        response = self.client.get(self.url)
        self.assertNotContains(response, "We stopped sending email to")

    def test_somebody_elses_suppressed_address_is_not_shown(self):
        """The page must not become a way to probe whether an arbitrary address
        has bounced."""
        email_events.suppress("stranger@example.com", SuppressedEmail.Reason.HARD_BOUNCE)
        response = self.client.get(self.url)
        self.assertNotContains(response, "stranger@example.com")

    def test_case_differences_still_match(self):
        """Suppression rows are stored lowercase; an EmailAddress may not be."""
        EmailAddress.objects.create(
            user=self.user, email="Mixed@Example.COM", verified=True
        )
        email_events.suppress("mixed@example.com", SuppressedEmail.Reason.HARD_BOUNCE)
        rows = suppressed_addresses_for(self.user)
        self.assertIn("mixed@example.com", [r.email for r in rows["rows"]])


class NoticePersistenceTests(TestCase):
    """The notice must not be swept away by the flash-message timer.

    `templates/components/messages.html` runs querySelectorAll('.alert') on a
    10-second timer and removes every match anywhere on the page — a boilerplate
    bug (loose end 9). This is a standing condition, not a flash message, so it
    must survive. Styling copies alert-error without the class that gets swept.
    """

    def test_the_notice_does_not_carry_the_swept_class(self):
        user = User.objects.create_user(email="p@example.com", password="Passw0rd!x")
        EmailAddress.objects.create(
            user=user, email="p@example.com", verified=True, primary=True
        )
        self.client.force_login(user)
        email_events.suppress("p@example.com", SuppressedEmail.Reason.HARD_BOUNCE)

        body = self.client.get(reverse("account_email")).content.decode()
        start = body.index("We stopped sending email to")
        # Walk back to the opening tag of the notice and check its classes.
        block = body[max(0, start - 400):start]
        self.assertNotIn('class="alert ', block)
        self.assertIn("alert-error", block)  # still looks like an error

    def test_the_sweeping_script_is_still_there(self):
        """If the boilerplate bug is ever fixed, this test fails and the note in
        the template can be simplified. It is a reminder, not a requirement."""
        script = open("templates/components/messages.html").read()
        self.assertIn("querySelectorAll('.alert')", script)


class TemplateTagTests(TestCase):
    def test_anonymous_users_get_an_empty_list(self):
        from django.contrib.auth.models import AnonymousUser

        self.assertEqual(suppressed_addresses_for(AnonymousUser())["rows"], [])

    def test_a_user_with_no_addresses_costs_no_second_query(self):
        user = User.objects.create_user(email="none@example.com", password="x")
        with self.assertNumQueries(1):
            self.assertEqual(suppressed_addresses_for(user)["rows"], [])


class LockedOutTests(TestCase):
    """The difference between an annoyance and being locked out.

    One working address left: nothing urgent. None: the person cannot receive a
    password reset and needs to act while still signed in. Showing that advice
    in the first case is noise, and noise is what stops people reading warnings.
    """

    def setUp(self):
        self.user = User.objects.create_user(
            email="a@example.com", password="Passw0rd!x"
        )
        EmailAddress.objects.create(
            user=self.user, email="a@example.com", verified=True, primary=True
        )
        self.client.force_login(self.user)

    def test_no_lockout_banner_while_one_address_still_works(self):
        EmailAddress.objects.create(user=self.user, email="b@example.com", verified=True)
        email_events.suppress("b@example.com", SuppressedEmail.Reason.HARD_BOUNCE)
        response = self.client.get(reverse("account_email"))
        self.assertContains(response, "We stopped sending email to")
        self.assertNotContains(response, "You have no working email address")

    def test_the_lockout_banner_appears_when_every_address_is_blocked(self):
        email_events.suppress("a@example.com", SuppressedEmail.Reason.HARD_BOUNCE)
        response = self.client.get(reverse("account_email"))
        self.assertContains(response, "You have no working email address")
        self.assertContains(response, "while you are still signed in")

    def test_every_class_used_exists_in_the_compiled_stylesheet(self):
        """Tailwind only compiles classes it saw at build time.

        The first version of this notice used `bg-error/10` and
        `border-error/30`, which are not in the stylesheet — so it rendered as a
        transparent background with a grey border, and a warning that does not
        look like a warning is worse than no warning. Caught only by reading the
        computed style in a browser, which is why this test exists.
        """
        import re

        template = open(
            "templates/account/snippets/_suppression_warning.html"
        ).read()
        stylesheet = open("static/mainapp/styles.css").read()

        used = set()
        for attr in re.findall(r'class="([^"]+)"', template):
            used.update(attr.split())

        missing = [c for c in sorted(used) if f".{c}" not in stylesheet]
        self.assertEqual(
            missing,
            [],
            f"classes not in the compiled stylesheet: {missing}",
        )
