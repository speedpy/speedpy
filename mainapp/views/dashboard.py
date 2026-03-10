from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import TemplateView
from mainapp.views.tour_mixin import TourMixin


class DashboardView(TourMixin, LoginRequiredMixin, TemplateView):
    template_name = "mainapp/dashboard/main.html"
    tour_name = "dashboard"
