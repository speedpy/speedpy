from django.db import models


class UserTourCompletion(models.Model):
    user = models.ForeignKey('usermodel.User', on_delete=models.CASCADE)
    tour_name = models.CharField(max_length=100)
    completed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("user", "tour_name")
