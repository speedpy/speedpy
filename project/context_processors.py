from django.conf import settings


def demo_mode(request):
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
    return {"TEAMS_ENABLED": getattr(settings, "TEAMS_ENABLED", True)}
