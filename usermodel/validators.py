import re

from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

# Matches URL schemes (http://, https://, ftp://, ...), the scheme-less
# "www." prefix, and dangerous pseudo-schemes (javascript:, data:, mailto:).
# These have no place in a person's name and, if rendered into an outgoing
# email, turn it into a phishing vector.
_URL_RE = re.compile(
    r"(?i)(?:\b[a-z][a-z0-9+.\-]*://|www\.|javascript:|data:|mailto:)"
)


def validate_no_url(value):
    """Reject values that contain URLs or link-like schemes."""
    if value and _URL_RE.search(value):
        raise ValidationError(
            _("Links and URLs are not allowed here."),
            code="contains_url",
        )
