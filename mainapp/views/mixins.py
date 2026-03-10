import json

from django.conf import settings

from mainapp.models import UserTourCompletion
from mainapp.tours import TOURS


class TourMixin:
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if not getattr(settings, "SPEEDPY_TOURS_ENABLED", True):
            context["tour_steps"] = "[]"
            context["tour_name"] = ""
            return context

        url_name = self.request.resolver_match.url_name
        steps = TOURS.get(url_name, [])

        if steps and self.request.user.is_authenticated:
            already_done = UserTourCompletion.objects.filter(
                user=self.request.user, tour_name=url_name
            ).exists()
            if already_done:
                steps = []

        context["tour_steps"] = json.dumps(steps)
        context["tour_name"] = url_name if steps else ""
        return context
