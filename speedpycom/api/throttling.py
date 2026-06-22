"""
Rate-limit throttle subclasses that emit standard rate-limit headers.

Headers added to every throttled API response:

    X-RateLimit-Limit      – requests allowed in the current window
    X-RateLimit-Remaining  – requests remaining in the current window
    X-RateLimit-Reset      – seconds until the window resets

DRF already sends ``Retry-After`` on 429 responses.
"""

import math

from rest_framework.throttling import AnonRateThrottle, UserRateThrottle


class _RateLimitHeadersMixin:
    """Inject X-RateLimit-* headers after throttle check."""

    def allow_request(self, request, view):
        allowed = super().allow_request(request, view)

        # self.history is only set when the throttle actually ran (rate is not
        # None and get_cache_key returned a key).  Skip header injection when
        # this throttle did not apply (e.g. AnonRateThrottle on an
        # authenticated request).
        if not hasattr(self, "history"):
            return allowed

        # DRF wraps the Django HttpRequest; the middleware sees the original,
        # not the DRF wrapper, so attach metadata to the underlying request.
        django_request = getattr(request, "_request", request)
        if not hasattr(django_request, "_rate_limit_headers"):
            django_request._rate_limit_headers = []

        remaining = max(self.num_requests - len(self.history), 0) if allowed else 0
        if not allowed:
            reset = math.ceil(self.wait() or 0)
        elif self.history:
            reset = math.ceil(self.duration - (self.now - self.history[-1]))
        else:
            reset = self.duration

        django_request._rate_limit_headers.append(
            {
                "limit": self.num_requests,
                "remaining": remaining,
                "reset": reset,
            }
        )
        return allowed


class SpeedPyAnonRateThrottle(_RateLimitHeadersMixin, AnonRateThrottle):
    pass


class SpeedPyUserRateThrottle(_RateLimitHeadersMixin, UserRateThrottle):
    pass
