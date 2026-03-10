from django.db import models
from django.conf import settings


class TourCompletion(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="tour_completions")
    tour_name = models.CharField(max_length=100)
    completed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("user", "tour_name")
