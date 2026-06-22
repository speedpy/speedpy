# Signal handlers for mainapp.
#
# X-Request-ID was previously added to failure responses here via
# django_structlog signals.  This is now handled by
# speedpycom.api.middleware.RequestIDMiddleware for ALL responses.
