from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import TemplateView

from mainapp.views.mixins import TourMixin


class DashboardView(TourMixin, LoginRequiredMixin, TemplateView):
    template_name = "mainapp/dashboard/main.html"
