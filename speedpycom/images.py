"""Normalize uploaded images: downscale + convert to a web-native format.

Reused for any small display image (team logos, user avatars). Two problems:

- iPhone/Mac photos are HEIC/HEIF. With pillow-heif registered (see settings)
  they validate and store, but Firefox and Chrome do NOT render HEIF in an
  ``<img>`` — so the image would upload yet never display.
- These images render at a few dozen pixels, so storing a full-resolution
  upload is wasteful and slow.

``prepare_image`` decodes the upload, downscales it to fit ``max_edge`` on the
long edge (aspect preserved, never upscaled), and re-encodes it — PNG when it has
transparency (logos/avatars often do), JPEG otherwise (which also converts HEIC).
"""

import os
from io import BytesIO

from django.core.files.base import ContentFile

# Formats every current browser renders in <img>. Anything else (HEIF/HEIC,
# TIFF, BMP, …) is converted.
WEB_SAFE_FORMATS = {"JPEG", "PNG", "GIF", "WEBP"}


def _has_alpha(image):
    return image.mode in ("RGBA", "LA", "PA") or (
        image.mode == "P" and "transparency" in image.info
    )


def prepare_image(file, max_edge):
    """Return a small, web-native ``ContentFile`` for an uploaded image.

    ``file`` is a Django ``UploadedFile``/``FieldFile`` already validated as an
    image. Returns a ``ContentFile`` (named ``.png`` if the source has an alpha
    channel, else ``.jpg``) suitable for assigning to an ImageField. On any error
    it returns the original bytes unchanged, so it never blocks a save on its own.
    """
    from PIL import Image

    original_name = os.path.basename(getattr(file, "name", "") or "image")
    base = os.path.splitext(original_name)[0] or "image"
    try:
        file.seek(0)
        image = Image.open(file)
        image.load()

        if _has_alpha(image):
            image = image.convert("RGBA")
            fmt, ext, params = "PNG", "png", {"optimize": True}
        else:
            image = image.convert("RGB")
            fmt, ext, params = "JPEG", "jpg", {"quality": 85, "optimize": True}

        image.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)

        buffer = BytesIO()
        image.save(buffer, format=fmt, **params)
        return ContentFile(buffer.getvalue(), name=f"{base}.{ext}")
    except Exception:
        # Never break a save on a processing error: fall back to the original.
        try:
            file.seek(0)
            return ContentFile(file.read(), name=original_name)
        except Exception:
            file.seek(0)
            return file
