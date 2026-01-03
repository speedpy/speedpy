from django.views.generic import TemplateView

from mainapp.views import TeamViewMixin


class TeamDashboardView(TeamViewMixin, TemplateView):
    template_name = "mainapp/teams/dashboard.html"