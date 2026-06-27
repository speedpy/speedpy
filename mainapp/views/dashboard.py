from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect
from django.views.generic import TemplateView

from mainapp.models import get_default_team_for_user
from mainapp.views.mixins import TourMixin


class DashboardView(TourMixin, LoginRequiredMixin, TemplateView):
    template_name = "mainapp/dashboard/main.html"

    def get(self, request, *args, **kwargs):
        # When teams are enabled there is no personal dashboard — send the user
        # to their team's dashboard (the first one we find), or to team
        # creation if they don't belong to a team yet.
        if getattr(settings, "SPEEDPY_TEAMS_ENABLED", True):
            team = get_default_team_for_user(request.user)
            if team:
                return redirect("team_dashboard", team_id=team.pk)
            return redirect("team_create")
        return super().get(request, *args, **kwargs)
