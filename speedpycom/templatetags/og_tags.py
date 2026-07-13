from urllib.parse import urlencode

from django import template
from django.urls import reverse

from speedpycom.views import OG_IMAGE_MAX_TITLE_LENGTH, og_image_signature

register = template.Library()


@register.simple_tag(takes_context=True)
def og_image_url(context, title=""):
    """
    Return the URL of the dynamically generated OG image (logo + title
    text). Falls back to the `og_title` context variable, then the
    `page` object's title (e.g. Wagtail). Without any title, returns
    the default site-wide OG image URL.
    """
    url = reverse("default-og-image")
    if not title:
        title = context.get("og_title") or ""
    if not title:
        page = context.get("page")
        title = getattr(page, "title", "") or ""
    title = str(title).strip()[:OG_IMAGE_MAX_TITLE_LENGTH]
    if not title:
        return url
    query = urlencode({"title": title, "sig": og_image_signature(title)})
    return f"{url}?{query}"
