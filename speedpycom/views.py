import hashlib
import io

from django.conf import settings
from django.core.cache import cache
from django.core.signing import Signer
from django.http import HttpResponse
from django.utils.crypto import constant_time_compare
from django.views.decorators.http import require_GET

from speedpycom.og_utils import create_og_image

OG_IMAGE_SALT = "og-image"
OG_IMAGE_MAX_TITLE_LENGTH = 300
OG_IMAGE_CACHE_SECONDS = 60 * 60 * 24 * 7  # 7 days
OG_FONT_PATH = str(settings.BASE_DIR / "static" / "fonts" / "Inter-SemiBold.ttf")


def og_image_signature(title: str) -> str:
    return Signer(salt=OG_IMAGE_SALT).signature(title)


@require_GET
def default_og_image(request):
    """
    Generate an Open Graph image (logo + title) as PNG.

    Accepts an optional signed `title` query param (see the `og_image_url`
    template tag). A missing or badly signed title falls back to the
    default site-wide text (TITLE + TAGLINE from settings), so outsiders
    can't render arbitrary text.
    """
    title = request.GET.get("title", "")[:OG_IMAGE_MAX_TITLE_LENGTH]
    signature = request.GET.get("sig", "")
    if not title or not constant_time_compare(
        signature, og_image_signature(title)
    ):
        site_title = getattr(settings, "TITLE", "SpeedPy")
        tagline = getattr(settings, "TAGLINE", "")
        title = f"{site_title}\n{tagline}" if tagline else site_title

    cache_key = f"og-image:{hashlib.md5(title.encode()).hexdigest()}"
    png_bytes = cache.get(cache_key)
    if png_bytes is None:
        og_img = create_og_image(
            text=title,
            font=OG_FONT_PATH,
            size=(1200, 630),
            logo_image=str(settings.BASE_DIR / settings.LOGO_PATH),
            font_size=64,
        )
        img_io = io.BytesIO()
        og_img.save(img_io, format="PNG", optimize=True)
        png_bytes = img_io.getvalue()
        cache.set(cache_key, png_bytes, OG_IMAGE_CACHE_SECONDS)

    response = HttpResponse(png_bytes, content_type="image/png")
    response["Cache-Control"] = f"public, max-age={OG_IMAGE_CACHE_SECONDS}"
    return response
