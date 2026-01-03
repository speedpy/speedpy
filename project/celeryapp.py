import os
import logging, logging.config
import structlog
from celery import Celery
from celery.schedules import crontab
from kombu import Queue
from .settings import BASE_DIR
import environ
from celery.signals import setup_logging
from django_structlog.celery.steps import DjangoStructLogInitStep

env = environ.Env()
environ.Env.read_env(os.path.join(BASE_DIR, ".env"))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "project.settings")

app = Celery("project")
app.steps["worker"].add(DjangoStructLogInitStep)
app.autodiscover_tasks()
app.conf.broker_url = env("REDIS_URL", default=None)
app.conf.accept_content = ["application/json"]
app.conf.task_serializer = "json"
app.conf.result_serializer = "json"
app.conf.result_backend = env("REDIS_URL", default=None)
app.conf.task_default_queue = "default"
# https://docs.celeryq.dev/en/stable/userguide/configuration.html#task-soft-time-limit
# Task soft time limit in seconds.
# app.conf.task_soft_time_limit = 10
# https://docs.celeryq.dev/en/stable/userguide/configuration.html#task-time-limit
# Task hard time limit in seconds.
# The worker processing the task will be killed and replaced with a new one when this is exceeded.
# app.conf.task_time_limit = 600
app.conf.task_create_missing_queues = True
app.conf.task_queues = (Queue("default"),)
app.conf.broker_pool_limit = 1
app.conf.broker_connection_timeout = 30
# worker_prefetch_multiplier: appropriate for long running tasks, default is 4
app.conf.worker_prefetch_multiplier = 1
app.conf.redbeat_redis_url = env("REDIS_URL", default=None)
# https://docs.celeryq.dev/en/stable/userguide/periodic-tasks.html#beat-entries
"""
Example of entries:

Run on 00:01, first day of month

    "example-celery-task": {
        "task": "example_celery_task",
        'schedule': crontab(
            minute=1,
            hour=0,
            day_of_month=1
         ),
         'schedule': 60 * 10 # run every 10 minutes
        "options": {
            "ignore_result": True,
            "queue": "default",
        },
    }
Run every 10 minutes
    "example-celery-task": {
        "task": "example_celery_task",
        'schedule': 60 * 10 # run every 10 minutes
        "options": {
            "ignore_result": True,
            "queue": "default",
        },
    }
"""
app.conf.beat_schedule = {
    "expire-team-memberships": {
        "task": "expire_team_memberships",
        "schedule": crontab(hour=2, minute=0),  # Run daily at 2:00 AM
        "options": {
            "ignore_result": True,
            "queue": "default",
        },
    },
    "expire-team-invitations": {
        "task": "expire_team_memberships_invitations",
        "schedule": crontab(hour=2, minute=30),  # Run daily at 2:30 AM
        "options": {
            "ignore_result": True,
            "queue": "default",
        },
    },
}

@setup_logging.connect
def receiver_setup_logging(
    loglevel, logfile, format, colorize, **kwargs
):  # pragma: no cover
    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "json_formatter": {
                    "()": structlog.stdlib.ProcessorFormatter,
                    "processor": structlog.processors.JSONRenderer(),
                },
                "plain_console": {
                    "()": structlog.stdlib.ProcessorFormatter,
                    "processor": structlog.dev.ConsoleRenderer(),
                },
                "key_value": {
                    "()": structlog.stdlib.ProcessorFormatter,
                    "processor": structlog.processors.KeyValueRenderer(
                        key_order=["timestamp", "level", "event", "logger"]
                    ),
                },
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "plain_console",
                }
            },
            "loggers": {"": {"handlers": ["console"], "level": "DEBUG"}},
        }
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.filter_by_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
