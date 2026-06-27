from django.conf import settings


def demo_mode(request):  # SPEEDPY_DEMO: remove before production
    return {"DEMO_MODE": getattr(settings, "DEMO_MODE", False)}


def site_url(request):
    default_url = f"{request.scheme}://{request.get_host()}"
    return {"SITE_URL": getattr(settings, "SITE_URL", default_url)}


def og_tags(request):
    return {
        "SITE_TITLE": getattr(settings, "TITLE", ""),
        "TAGLINE": getattr(settings, "TAGLINE", ""),
        "LOGO_PATH": getattr(settings, "LOGO_PATH_TEMPLATE", ""),
    }


def teams_enabled(request):
    return {"SPEEDPY_TEAMS_ENABLED": getattr(settings, "SPEEDPY_TEAMS_ENABLED", True)}


def sidebar_team(request):
    """
    Expose the user's default team to every template so the sidebar can link
    its "Dashboard" entry to a team dashboard. Mirrors the redirect target of
    the personal dashboard, keeping the link and the redirect in agreement.
    """
    if not getattr(settings, "SPEEDPY_TEAMS_ENABLED", True):
        return {}
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {}
    from mainapp.models import get_default_team_for_user

    return {"SIDEBAR_TEAM": get_default_team_for_user(user)}


def tours_enabled(request):
    return {"SPEEDPY_TOURS_ENABLED": getattr(settings, "SPEEDPY_TOURS_ENABLED", True)}


def current_year(request):
    from datetime import date
    return {"current_year": date.today().year}


def mfa_backend(request):
    return {"SPEEDPY_MFA_BACKEND": getattr(settings, "SPEEDPY_MFA_BACKEND", "django_otp")}
