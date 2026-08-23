"""The flash-message component (templates/components/messages.html).

It had a global in it. The dismissal timer ran
`document.querySelectorAll('.alert')` from outside the `{% if messages %}` block,
so it shipped on every page extending `base.html` and removed every `.alert` on
it ten seconds later — whether or not a flash message existed.

`.alert` is also the design system's STANDING-notice class, so what actually
vanished was the notices that matter most: a suppressed-email warning explaining
why somebody's mail is not arriving, a webhook failure banner, a billing notice.
Ten seconds is exactly long enough for a person to start reading.

So these tests are about a component not reaching outside itself.
"""

import pathlib
import re

from django.conf import settings
from django.contrib.messages import constants as message_levels
from django.template import Context, Template
from django.test import RequestFactory, SimpleTestCase

COMPONENT = (
    pathlib.Path(settings.BASE_DIR) / "templates" / "components" / "messages.html"
)


def source():
    return COMPONENT.read_text()


def render(messages):
    """Render the component the way base.html does."""
    request = RequestFactory().get("/")
    template = Template('{% include "components/messages.html" %}')
    return template.render(Context({"messages": messages, "request": request}))


class FakeMessage:
    def __init__(self, text, level_tag="info"):
        self.message = text
        self.level_tag = level_tag

    def __str__(self):
        return self.message


class ScopeTests(SimpleTestCase):
    """Asserted on the RENDERED output, not the file.

    The first version of these tests grepped the source for the old selector —
    and failed, because the comment at the top of the template quotes it while
    explaining the bug. Which is the point: source-text assertions match prose.
    The rendered page is what actually ships.
    """

    def test_the_shipped_timer_does_not_select_alerts_globally(self):
        """The bug, stated as the thing not to reintroduce."""
        html = render([FakeMessage("Saved.", "success")])
        script = html[html.index("<script>"):]
        self.assertNotIn("document.querySelectorAll('.alert')", script)
        self.assertNotIn('document.querySelectorAll(".alert")', script)

    def test_the_shipped_timer_is_scoped_to_the_flash_container(self):
        html = render([FakeMessage("Saved.", "success")])
        script = html[html.index("<script>"):]
        self.assertIn("[data-flash-messages]", script)
        self.assertIn("flash.querySelectorAll('.alert')", script)

    def test_a_page_with_no_messages_ships_no_timer(self):
        """The clearest form of "does not reach outside itself": with nothing to
        dismiss there is no code on the page at all."""
        html = render([])
        self.assertNotIn("setTimeout", html)
        self.assertNotIn("data-flash-messages", html)

    def test_a_page_with_messages_ships_the_timer(self):
        html = render([FakeMessage("Saved.", "success")])
        self.assertIn("setTimeout", html)
        self.assertIn("data-flash-messages", html)

    def test_the_container_carries_the_hook(self):
        html = render([FakeMessage("Saved.", "success")])
        self.assertIn("data-flash-messages", html)
        # And the message itself still carries .alert, which is its styling.
        self.assertIn("alert-success", html)


class LevelTests(SimpleTestCase):
    """Guarding the OTHER bug this file's comment records: branching on `tags`
    rather than `level_tag`. Django builds tags as "<extra_tags> <level_tag>", so
    `messages.success(request, "x", extra_tags="toast")` yields "toast success"
    and an equality test against "success" misses it."""

    def test_each_level_gets_its_own_style(self):
        for level_tag, expected in (
            ("success", "alert-success"),
            ("error", "alert-error"),
            ("warning", "alert-warning"),
            ("info", "alert-info"),
        ):
            with self.subTest(level=level_tag):
                html = render([FakeMessage("m", level_tag)])
                self.assertIn(expected, html)

    def test_an_unknown_level_falls_back_to_neutral(self):
        self.assertIn("alert-neutral", render([FakeMessage("m", "debug")]))

    def test_danger_is_treated_as_error(self):
        self.assertIn("alert-error", render([FakeMessage("m", "danger")]))
