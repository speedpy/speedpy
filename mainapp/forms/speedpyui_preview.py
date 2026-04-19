from crispy_forms.helper import FormHelper
from crispy_forms.layout import Field, Layout
from crispy_tailwind.layout import Submit
from django import forms


class SpeedpyuiFormViewExampleForm(forms.Form):
    full_name = forms.CharField(
        label="Full name",
        max_length=120,
        help_text="A standard CharField rendered by crispy forms.",
        widget=forms.TextInput(attrs={"placeholder": "Jane Founder"}),
    )
    company_size = forms.ChoiceField(
        label="Company size",
        choices=(
            ("", "Choose a size"),
            ("solo", "Just me"),
            ("small", "2-10 people"),
            ("growth", "11-50 people"),
            ("scale", "51+ people"),
        ),
    )
    launch_plan = forms.ChoiceField(
        label="Launch plan",
        choices=(
            ("soon", "Launch this month"),
            ("quarter", "Launch this quarter"),
            ("exploring", "Still exploring"),
        ),
        widget=forms.RadioSelect,
    )
    notes = forms.CharField(
        label="Project notes",
        help_text="Textarea widgets pick up the same token-driven styling.",
        widget=forms.Textarea(
            attrs={
                "rows": 5,
                "placeholder": "Tell us what you are building...",
            }
        ),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_tag = False
        self.helper.layout = Layout(
            Field("full_name"),
            Field("company_size"),
            Field("launch_plan"),
            Field("notes"),
            Submit("submit", "Preview submit", css_class="btn btn-contained btn-primary"),
        )
