import io
from django.conf import settings
from django.http import HttpResponse
from django.views.decorators.cache import cache_page
from django.views.decorators.http import require_GET
from speedpycom.og_utils import create_og_image


@require_GET
# @cache_page(60 * 60 * 24 * 7)  # Cache for 7 days
def default_og_image(request):
    """
    Generate and return a dynamic Open Graph image as PNG.
    Uses site title, tagline, and logo from settings.
    """
    # Get configuration from settings
    title = getattr(settings, "TITLE", "SpeedPy")
    tagline = getattr(settings, "TAGLINE", "")
    logo_path = getattr(settings, "LOGO_PATH", settings.LOGO_PATH)
    # Combine title and tagline with explicit newline
    text = f"{title}\n{tagline}" if tagline else title

    # Generate OG image using the same pattern as OGMixin
    og_img = create_og_image(
        text=text,
        font="inter",
        size=(1200, 630),
        logo_image=logo_path,
        font_size=64,
    )

    # Convert PIL image to file-like object
    img_io = io.BytesIO()
    og_img.save(img_io, format="PNG", optimize=True)
    img_io.seek(0)

    # Return as PNG response
    response = HttpResponse(img_io.getvalue(), content_type="image/png")
    response["Cache-Control"] = "public, max-age=604800"  # 7 days

    return response
