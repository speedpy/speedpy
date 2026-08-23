"""The crispy Tailwind pack in templates/tailwind/ (AGENTS.md § Forms).

These render real forms through `{% crispy %}` and assert on the HTML, because
the failure mode here is silence: a partial that never gets included drops its
content without an error anywhere. That is exactly how checkboxes lost their
help text and their errors — the input kept advertising
`aria-describedby="<id>_helptext"` while the element it named was never emitted.

It matters more than it sounds. A checkbox's help text is where a form explains
what ticking it will DO, which for this codebase includes privacy disclosures
("this sends your text to a third-party AI"). Dropping it silently is worse than
a broken layout: the customer consents to something they were never shown.
"""

from crispy_forms.helper import FormHelper
from crispy_forms.layout import Div, Field, Layout
from django import forms
from django.template import Context, Template
from django.test import SimpleTestCase

RENDER = Template("{% load crispy_forms_tags %}{% crispy form %}")


class DemoForm(forms.Form):
    agree = forms.BooleanField(
        required=False,
        label="Send my text to the robot",
        help_text="It goes to a third party. This is the part nobody sees.",
    )
    must_agree = forms.BooleanField(required=True, label="Required box")
    plain = forms.CharField(
        required=False, label="Name", help_text="Help for a text input."
    )

    def __init__(self, *args, wrapper=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_tag = False
        if wrapper:
            # How this project's own forms lay checkboxes out.
            self.helper.layout = Layout(
                Div(Field("agree"), css_class="flex items-center"),
                Field("must_agree"),
                Field("plain"),
            )


def render(**kwargs):
    return RENDER.render(Context({"form": DemoForm(**kwargs)}))


class CheckboxHelpTextTests(SimpleTestCase):
    def test_a_checkbox_renders_its_help_text(self):
        self.assertIn("This is the part nobody sees.", render())

    def test_it_renders_inside_a_layout_wrapper_too(self):
        """The regression was invisible because every real call site wraps the
        field in a Div, so a test that only rendered a bare form would have
        passed either way."""
        self.assertIn("This is the part nobody sees.", render(wrapper=True))

    def test_the_advertised_helptext_id_actually_exists(self):
        """`aria-describedby` naming a missing element makes a screen reader
        announce nothing where it promised a description."""
        html = render()
        self.assertIn('aria-describedby="id_agree_helptext"', html)
        self.assertIn('id="id_agree_helptext"', html)

    def test_a_text_input_still_renders_its_help_text(self):
        self.assertIn("Help for a text input.", render())

    def test_the_label_stays_next_to_its_box(self):
        """The help text goes BELOW the row. Beside the label it pushes the
        label away from the checkbox it belongs to."""
        html = render()
        row = html.index("checkbox")
        label = html.index("Send my text to the robot")
        helptext = html.index("This is the part nobody sees.")
        self.assertLess(row, label)
        self.assertLess(label, helptext)


class CheckboxErrorTests(SimpleTestCase):
    def test_a_checkbox_shows_its_validation_error(self):
        """Without this a failed required checkbox looks like a form that just
        refuses to submit, with nothing on screen to say why."""
        form = DemoForm(data={})
        form.is_valid()
        html = RENDER.render(Context({"form": form}))
        self.assertIn("input-error-text", html)
        self.assertIn("This field is required.", html)
