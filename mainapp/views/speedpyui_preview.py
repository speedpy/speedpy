from django.views.generic.edit import FormView
from django.views.generic import TemplateView

from mainapp.forms import SpeedpyuiFormViewExampleForm


class SpeedpyuiPreviewView(TemplateView):
    template_name = "mainapp/speedpyui_preview.html"


class SpeedpyuiFormViewExampleView(FormView):
    form_class = SpeedpyuiFormViewExampleForm
    template_name = "mainapp/speedpyui_form_view.html"

    def form_valid(self, form):
        return self.render_to_response(
            self.get_context_data(
                form=self.form_class(),
                submitted=True,
                cleaned_data=form.cleaned_data,
            )
        )
