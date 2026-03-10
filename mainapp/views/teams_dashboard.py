from django.views.generic import TemplateView

from mainapp.views import TeamViewMixin
from mainapp.views.mixins import TourMixin


class TeamDashboardView(TourMixin, TeamViewMixin, TemplateView):
    template_name = "mainapp/teams/dashboard.html"