from django.views.generic import TemplateView


class SpeedpyuiPreviewView(TemplateView):
    template_name = "mainapp/speedpyui_preview.html"
