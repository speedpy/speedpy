import json
from django.conf import settings
from mainapp.models import TourCompletion
from mainapp.tours import TOURS


class TourMixin:
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if not getattr(settings, "SPEEDPY_ONBOARDING_ENABLED", True):
            context["tour_steps"] = "[]"
            return context
        if self.request.user.is_authenticated:
            tour_name = self.tour_name
            steps = TOURS.get(tour_name, [])
            already_done = TourCompletion.objects.filter(
                user=self.request.user, tour_name=tour_name
            ).exists()
            context["tour_steps"] = json.dumps(steps) if (steps and not already_done) else "[]"
            context["tour_name"] = tour_name
        return context
