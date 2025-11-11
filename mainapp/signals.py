from django.dispatch import receiver
from django_structlog import signals
import structlog


@receiver(signals.update_failure_response)
@receiver(signals.bind_extra_request_finished_metadata)
def add_request_id_to_error_response(response, logger, **kwargs):
    context = structlog.contextvars.get_merged_contextvars(logger)
    response['X-Request-ID'] = context["request_id"]