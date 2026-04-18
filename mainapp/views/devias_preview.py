from django.views.generic import TemplateView


class DeviasPreviewView(TemplateView):
    template_name = "mainapp/devias_preview.html"
