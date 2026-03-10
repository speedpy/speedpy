import json

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_POST

from mainapp.models import UserTourCompletion


@login_required
@require_POST
def mark_tour_complete(request):
    try:
        data = json.loads(request.body)
        tour_name = data.get("tour_name", "")
    except (json.JSONDecodeError, AttributeError):
        return JsonResponse({"ok": False, "error": "Invalid JSON"}, status=400)

    if not tour_name:
        return JsonResponse({"ok": False, "error": "tour_name required"}, status=400)

    UserTourCompletion.objects.get_or_create(user=request.user, tour_name=tour_name)
    return JsonResponse({"ok": True})
