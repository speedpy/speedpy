from django.conf import settings


def demo_mode(request):
    return {
        'DEMO_MODE': getattr(settings, 'DEMO_MODE', False)
    }
