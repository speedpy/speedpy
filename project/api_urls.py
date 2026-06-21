from django.urls import path

from usermodel.api import CurrentUserAPIView

app_name = "api"

urlpatterns = [
    path("v1/me/", CurrentUserAPIView.as_view(), name="current_user"),
]
