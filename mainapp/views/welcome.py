from django.views.generic import TemplateView

from mainapp.subscription_plans import get_public_plans


class WelcomeToSpeedPyView(TemplateView):
    template_name = "mainapp/welcome.html"


class PricingView(TemplateView):
    template_name = "mainapp/pricing.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["plans"] = get_public_plans()
        return context
