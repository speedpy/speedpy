from django.conf import settings


def demo_mode(request):
    return {"DEMO_MODE": getattr(settings, "DEMO_MODE", False)}


def site_url(request):
    return {"SITE_URL": getattr(settings, "SITE_URL", "http://localhost")}


def og_tags(request):
    return {
        "SITE_TITLE": getattr(settings, "TITLE", ""),
        "TAGLINE": getattr(settings, "TAGLINE", ""),
        "LOGO_PATH": getattr(settings, "LOGO_PATH", ""),
    }
