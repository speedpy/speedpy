import json
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from mainapp.models import TourCompletion


@login_required
@require_POST
def mark_tour_complete(request):
    try:
        data = json.loads(request.body)
        tour_name = data.get("tour_name", "")
    except (json.JSONDecodeError, AttributeError):
        tour_name = request.POST.get("tour_name", "")
    if tour_name:
        TourCompletion.objects.get_or_create(user=request.user, tour_name=tour_name)
    return JsonResponse({"ok": True})
