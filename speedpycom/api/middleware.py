"""API middleware for rate-limit response headers."""


class RateLimitHeadersMiddleware:
    """
    Read rate-limit metadata attached by SpeedPy throttle classes and emit
    standard ``X-RateLimit-*`` headers on every API response.

    Must be placed **after** DRF processes the request (i.e. in the response
    phase).  Since DRF views run inside Django's middleware stack, any
    middleware position works — the headers are set in the response phase.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        headers = getattr(request, "_rate_limit_headers", None)
        if headers:
            # Use the most restrictive bucket (lowest remaining).
            best = min(headers, key=lambda h: h["remaining"])
            response["X-RateLimit-Limit"] = best["limit"]
            response["X-RateLimit-Remaining"] = best["remaining"]
            response["X-RateLimit-Reset"] = best["reset"]
        return response
