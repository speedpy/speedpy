from crispy_forms.helper import FormHelper
from crispy_forms.layout import Div, Field, Layout
from crispy_tailwind.layout import Submit
from django import forms

from demoapp.models import Product


class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = (
            "name",
            "sku",
            "category",
            "status",
            "price",
            "inventory",
            "description",
        )
        widgets = {
            "description": forms.Textarea(attrs={"rows": 6}),
        }

    def __init__(self, *args, **kwargs):
        submit_label = kwargs.pop("submit_label", "Create product")
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_tag = False
        self.helper.layout = Layout(
            Div(
                Div(Field("name", placeholder="API Usage Pack"), css_class="sm:col-span-2"),
                Div(Field("sku", placeholder="SP-API-001"), css_class="sm:col-span-1"),
                Div(Field("category"), css_class="sm:col-span-1"),
                Div(Field("status"), css_class="sm:col-span-1"),
                Div(Field("price", placeholder="49.00"), css_class="sm:col-span-1"),
                Div(Field("inventory", placeholder="25"), css_class="sm:col-span-1"),
                Div(Field("description", placeholder="Short product notes for the team."), css_class="sm:col-span-2"),
                css_class="grid grid-cols-1 gap-x-6 gap-y-2 sm:grid-cols-2",
            ),
            Submit("submit", submit_label, css_class="btn btn-contained btn-primary"),
        )
