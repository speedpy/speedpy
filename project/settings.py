from datetime import timedelta
from pathlib import Path
import environ
import os
import sys
import structlog
from django.core.exceptions import ImproperlyConfigured
from django.urls import reverse_lazy

from project.email_providers import resolve_email_backend
from project.media import normalize_media_url

env = environ.Env(
    # set casting, default value
    DEBUG=(bool, False)
)

BASE_DIR = Path(__file__).resolve().parent.parent
# Take environment variables from .env file
environ.Env.read_env(os.path.join(BASE_DIR, ".env"))

SECRET_KEY = env("SECRET_KEY", default="change_me")
SALT_KEY = env("SALT_KEY", default="changeme")
DEBUG = env("DEBUG", default=False)

ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["*"])

ADMIN_URL = env.str("ADMIN_URL", default="admin/") or "admin/"
# Application definition

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "django_extensions",
    "crispy_forms",
    "crispy_tailwind",
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    "allauth.socialaccount.providers.github",
    "allauth.socialaccount.providers.google",
    "allauth.socialaccount.providers.gitlab",
    "debug_toolbar",
    "post_office",
    "anymail",
    "usermodel.apps.UsermodelConfig",
    "speedpycom",
    "mainapp.apps.MainappConfig",
    "django_recaptcha",
    "demoapp",  # SPEEDPY_DEMO: demo Product CRUD app — remove before production
    "rest_framework",
    "drf_spectacular",
    "rest_framework_simplejwt",
    "rest_framework_simplejwt.token_blacklist",
    "oauth2_provider",
    "corsheaders",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # Host isolation for the hosted MCP plane. Above WhiteNoise so a static file
    # on the MCP host is refused too. Removes itself unless MCP_ENABLED.
    "speedpycom.api.mcp_host.MCPHostMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "debug_toolbar.middleware.DebugToolbarMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    # django_otp.middleware.OTPMiddleware inserted conditionally below
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "allauth.account.middleware.AccountMiddleware",
    "django_structlog.middlewares.RequestMiddleware",
    "speedpycom.api.middleware.RequestIDMiddleware",
    "speedpycom.api.middleware.RateLimitHeadersMiddleware",
    "speedpycom.api.middleware.ApiAccessLogMiddleware",
]
DJANGO_STRUCTLOG_CELERY_ENABLED = True
DJANGO_STRUCTLOG_COMMAND_LOGGING_ENABLED = True
ROOT_URLCONF = "project.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [
            BASE_DIR / "templates",
        ],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "project.context_processors.demo_mode",  # SPEEDPY_DEMO
                "project.context_processors.site_url",
                "project.context_processors.og_tags",
                "project.context_processors.teams_enabled",
                "project.context_processors.sidebar_team",
                "project.context_processors.tours_enabled",
                "project.context_processors.current_year",
                "project.context_processors.mfa_backend",
                "project.context_processors.billing",
            ],
        },
    },
]

WSGI_APPLICATION = "project.wsgi.application"

# Database
# https://docs.djangoproject.com/en/4.0/ref/settings/#databases

DATABASES = {
    # read os.environ['DATABASE_URL'] and raises
    # ImproperlyConfigured exception if not found
    #
    # The db() method is an alias for db_url().
    "default": env.db(default="sqlite:///db.sqlite3"),
}

if DATABASES["default"]["ENGINE"] == "django.db.backends.postgresql":
    DATABASES["default"]["ATOMIC_REQUESTS"] = True
    DATABASES["default"]["CONN_MAX_AGE"] = env.int("CONN_MAX_AGE", default=60)
    CI_COLLATION = "und-x-icu"
elif DATABASES["default"]["ENGINE"] == "django.db.backends.sqlite3":
    CI_COLLATION = "NOCASE"
elif DATABASES["default"]["ENGINE"] == "django.db.backends.mysql":
    CI_COLLATION = "utf8mb4_unicode_ci"
else:
    raise NotImplementedError("Unknown database engine")
CACHES = {
    # Read os.environ['CACHE_URL'] and raises
    # ImproperlyConfigured exception if not found.
    #
    # The cache() method is an alias for cache_url().
    "default": env.cache(default="dummycache://"),
}
# Password validation
# https://docs.djangoproject.com/en/4.0/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]
AUTH_USER_MODEL = "usermodel.User"
AUTHENTICATION_BACKENDS = [
    # Needed to login by username in Django admin, regardless of `allauth`
    "django.contrib.auth.backends.ModelBackend",
    # `allauth` specific authentication methods, such as login by email
    "allauth.account.auth_backends.AuthenticationBackend",
]

ACCOUNT_FORMS = {
    "signup": "usermodel.forms.UsermodelSignupForm",
    "login": "usermodel.forms.UsermodelLoginForm",
    "reset_password": "usermodel.forms.UsermodelResetPasswordForm",
    "reset_password_from_key": "usermodel.forms.UsermodelResetPasswordKeyForm",
    "change_password": "usermodel.forms.UsermodelChangePasswordForm",
    "add_email": "usermodel.forms.UsermodelAddEmailForm",
}
ACCOUNT_LOGIN_METHODS = {"email"}
ACCOUNT_SIGNUP_FIELDS = ["email*", "password1*"]
ACCOUNT_USER_MODEL_USERNAME_FIELD = None
ACCOUNT_EMAIL_VERIFICATION = "mandatory"
ACCOUNT_EMAIL_UNKNOWN_ACCOUNTS = False
ACCOUNT_ADAPTER = "usermodel.adapters.CustomAccountAdapter"
SOCIALACCOUNT_ADAPTER = "usermodel.adapters.CustomSocialAccountAdapter"
LOGIN_REDIRECT_URL = reverse_lazy("dashboard")

# Root log level. DEBUG in development, INFO in production — a production root
# at DEBUG makes third-party libraries dump request bodies (see the logger pins
# below). Override deliberately with LOG_LEVEL when debugging.
LOG_LEVEL = env.str("LOG_LEVEL", default="DEBUG" if DEBUG else "INFO").upper()

LOGGING = {
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
        "console": {"class": "logging.StreamHandler", "formatter": "plain_console"}
    },
    "loggers": {
        "": {"handlers": ["console"], "level": LOG_LEVEL},
        # Pinned to WARNING independently of the root level, and deliberately
        # NOT just lowered along with it. At DEBUG these libraries log every
        # HTTP request body they send. For any project that sends mail through
        # an AWS/boto-backed ESP that means password-reset tokens (as decodable
        # base64 MIME), whole message bodies, and SigV4 Authorization headers
        # written to the container log. Pinning here means the leak cannot come
        # back the next time somebody raises the root level to debug something
        # unrelated, which is exactly when nobody would notice.
        "botocore": {"handlers": ["console"], "level": "WARNING", "propagate": False},
        "boto3": {"handlers": ["console"], "level": "WARNING", "propagate": False},
        "s3transfer": {"handlers": ["console"], "level": "WARNING", "propagate": False},
        "urllib3": {"handlers": ["console"], "level": "WARNING", "propagate": False},
    },
}

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

logger = structlog.get_logger()

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# Internationalization
# https://docs.djangoproject.com/en/4.0/topics/i18n/

LANGUAGE_CODE = "en-us"

TIME_ZONE = "UTC"

USE_I18N = True

USE_TZ = True

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

STATIC_URL = env.str("STATIC_URL", default="/static/")
STATIC_ROOT = env.str("STATIC_ROOT", default=BASE_DIR / "staticfiles")

# Appliku volumes export <PREFIX>_ROOT and <PREFIX>_URL from the volume's
# environment-variable prefix, so the default `media` volume (prefix MEDIA) sets
# MEDIA_ROOT and MEDIA_URL directly. Read exactly those names: the URL used to be
# read from MEDIA_PATH, which the platform never sets, so a volume with a
# non-default web path was silently ignored.
MEDIA_ROOT = env("MEDIA_ROOT", default=BASE_DIR / "media")
MEDIA_URL = normalize_media_url(env.str("MEDIA_URL", default=""))
# Local-disk home for private uploads (project.media.private_storage). Deliberately
# OUTSIDE MEDIA_ROOT: everything under MEDIA_ROOT is served by the web server, so a
# "private" subdirectory in there would be publicly fetchable.
PRIVATE_MEDIA_ROOT = env("PRIVATE_MEDIA_ROOT", default=BASE_DIR / "private-media")

# ---- Object storage: local disk by default, S3-compatible when you need it ----
# Flip USE_S3=True and set the S3_* variables to move media off the local disk to
# any S3-compatible provider (AWS S3, DigitalOcean Spaces, Cloudflare R2, Wasabi,
# Backblaze B2, MinIO). The provider is chosen purely by S3_ENDPOINT_URL — nothing
# here is vendor-specific. Requires the optional dependency: uv sync --extra s3
# See STORAGE_SETUP.md, and speedpycom/storages.py for the two backends.
USE_S3 = env.bool("USE_S3", default=False)
S3_ACCESS_KEY_ID = env.str("S3_ACCESS_KEY_ID", default="")
S3_SECRET_ACCESS_KEY = env.str("S3_SECRET_ACCESS_KEY", default="")
S3_BUCKET_NAME = env.str("S3_BUCKET_NAME", default="")
S3_REGION_NAME = env.str("S3_REGION_NAME", default="")
# Empty = AWS S3. Otherwise the provider's endpoint, e.g.
# https://fra1.digitaloceanspaces.com or https://<account>.r2.cloudflarestorage.com
S3_ENDPOINT_URL = env.str("S3_ENDPOINT_URL", default="")
# Optional CDN/custom domain in front of the bucket; public URLs use it when set.
S3_CDN_BASE = env.str("S3_CDN_BASE", default="")
# ACLs are NOT portable. Empty (the default) works everywhere. Set "public-read"
# on DigitalOcean Spaces. Leave empty on AWS buckets with ACLs disabled (the
# default since April 2023) and on Cloudflare R2, which has no ACLs — grant public
# read with a bucket policy or a public bucket instead.
S3_DEFAULT_ACL = env.str("S3_DEFAULT_ACL", default="")
S3_SEND_PRIVATE_ACL = env.bool("S3_SEND_PRIVATE_ACL", default=True)
S3_SIGNED_URL_EXPIRE = env.int("S3_SIGNED_URL_EXPIRE", default=600)
# "path" for MinIO and some self-hosted gateways; empty lets boto3 decide.
S3_ADDRESSING_STYLE = env.str("S3_ADDRESSING_STYLE", default="")

if USE_S3:
    # Fail loudly at boot rather than on the first upload.
    _missing = [
        name
        for name, value in (
            ("S3_ACCESS_KEY_ID", S3_ACCESS_KEY_ID),
            ("S3_SECRET_ACCESS_KEY", S3_SECRET_ACCESS_KEY),
            ("S3_BUCKET_NAME", S3_BUCKET_NAME),
        )
        if not value
    ]
    if _missing:
        raise ImproperlyConfigured(
            "USE_S3=True requires " + ", ".join(_missing)
        )

# Static files stay on WhiteNoise in both modes: atomic deploys, no collectstatic
# round-trip to object storage, and no CDN invalidation step on every release.
STORAGES = {
    "default": {
        "BACKEND": "speedpycom.storages.PublicMediaStorage"
        if USE_S3
        else "django.core.files.storage.FileSystemStorage"
    },
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
WHITENOISE_USE_FINDERS = True
WHITENOISE_AUTOREFRESH = DEBUG

# Accept HEIC/HEIF image uploads (the default format of iPhone/Mac photos).
# Pillow has no native HEIF support, so a .heic upload is otherwise rejected by
# ImageField as "not a valid image". Register pillow-heif's opener once at
# startup. Guarded so a missing/broken wheel degrades to "no HEIC" rather than
# breaking boot. See speedpycom/images.py, which converts non-web-native uploads.
try:
    import pillow_heif

    pillow_heif.register_heif_opener()
except Exception:  # pragma: no cover - HEIC support is best-effort
    pass
STATICFILES_DIRS = [
    BASE_DIR / "static",
    ("floating-core", BASE_DIR / "node_modules" / "@floating-ui" / "core" / "dist"),
    ("floating-ui", BASE_DIR / "node_modules" / "@floating-ui" / "dom" / "dist"),
]
CRISPY_TEMPLATE_PACK = "tailwind"
CRISPY_ALLOWED_TEMPLATE_PACKS = "tailwind"

REST_FRAMEWORK = {
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "speedpycom.api.authentication.PersonalAccessTokenAuthentication",
        "oauth2_provider.contrib.rest_framework.OAuth2Authentication",
        "rest_framework_simplejwt.authentication.JWTAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
    "DEFAULT_PARSER_CLASSES": [
        "rest_framework.parsers.JSONParser",
        "rest_framework.parsers.FormParser",
        "rest_framework.parsers.MultiPartParser",
    ],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 50,
    "DEFAULT_THROTTLE_CLASSES": [
        "speedpycom.api.throttling.SpeedPyAnonRateThrottle",
        "speedpycom.api.throttling.SpeedPyUserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": "100/hour",
        "user": "1000/hour",
    },
}

if DEBUG:
    REST_FRAMEWORK["DEFAULT_RENDERER_CLASSES"].append(
        "rest_framework.renderers.BrowsableAPIRenderer"
    )

API_DOCS_PUBLIC = env.bool("API_DOCS_PUBLIC", default=DEBUG)

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=15),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "AUTH_HEADER_TYPES": ("Bearer",),
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
}

OAUTH2_PROVIDER = {
    "SCOPES": {
        "read:profile": "Read your profile",
        "write:profile": "Update your profile",
        "read:teams": "Read your teams and members",
        "write:teams": "Create invitations and manage teams",
        "read:products": "Read products",  # SPEEDPY_DEMO: demo scope — remove with Product API
        "read:webhooks": "List and inspect webhook endpoints and deliveries",
        "write:webhooks": "Create, update, and delete webhook endpoints",
        "read:jobs": "Poll job status",
        "write:jobs": "Start background jobs",
        "admin": "Administrative access",
    },
    "DEFAULT_SCOPES": ["read:profile"],
    "ACCESS_TOKEN_EXPIRE_SECONDS": 3600,
    "REFRESH_TOKEN_EXPIRE_SECONDS": 86400 * 30,
    "ROTATE_REFRESH_TOKEN": True,
    "PKCE_REQUIRED": True,
    "ALLOWED_REDIRECT_URI_SCHEMES": ["https", "http"],
    "REQUEST_APPROVAL_PROMPT": "auto",
    "OAUTH2_VALIDATOR_CLASS": "oauth2_provider.oauth2_validators.OAuth2Validator",
}

# Declared explicitly (to its default value) so models outside oauth2_provider
# may hold a ForeignKey to the swappable Application model: Django's migration
# autodetector resolves such a dependency through this setting. Webhook
# endpoints created through OAuth carry an `application` FK for the lifecycle
# fail-closed check (mainapp/webhooks/lifecycle.py).
OAUTH2_PROVIDER_APPLICATION_MODEL = "oauth2_provider.Application"

DCR_ENABLED = env.bool("DCR_ENABLED", default=DEBUG)

# --- Hosted MCP (inert until MCP_ENABLED) ---
# The remote MCP endpoint is served on its own host and is the OAuth `resource`
# (RFC 8707) of every connector URL. Everything here is inert until a project
# sets MCP_ENABLED=True and MCP_BASE_URL — the host-isolation middleware removes
# itself, the deploy checks return nothing, and no MCP route is mounted. See
# agents_docs/working_with_hosted_mcp.md for the full recipe.
MCP_ENABLED = env.bool("MCP_ENABLED", default=False)
# Bare HTTPS origin of the MCP host (no path, query, or fragment), e.g.
# https://mcp.example.com. A deploy check enforces the shape when MCP_ENABLED.
MCP_BASE_URL = env("MCP_BASE_URL", default="").rstrip("/")
# Path prefixes the MCP host is allowed to serve; everything else 404s there.
# Extend it for a store domain-verification file (e.g.
# "/.well-known/openai-apps-challenge"). Empty and "/" entries are ignored so a
# misconfiguration cannot re-expose the whole app on the MCP host.
MCP_HOST_ALLOWED_PREFIXES = env.list(
    "MCP_HOST_ALLOWED_PREFIXES",
    default=["/mcp", "/.well-known/oauth-protected-resource", "/health/"],
)
# CIMD client_id URLs allowed to connect one-click as a public PKCE client (the
# two directory clients). Consulted only when MCP is enabled AND CIMD is on (see
# the OAuth hardening block near the end of this file). Empty disables the
# downgrade entirely. See speedpycom/api/oauth_validator.py.
MCP_CIMD_PUBLIC_DOWNGRADE_CLIENT_IDS = env.list(
    "MCP_CIMD_PUBLIC_DOWNGRADE_CLIENT_IDS",
    default=[
        "https://chatgpt.com/connectors/oauth/client_metadata.json",
        "https://claude.ai/.well-known/oauth-client-metadata.json",
    ],
)
# Dotted paths to the MCP transport and RFC 9728 metadata views mounted when
# MCP_ENABLED. Point them at your ToolCatalogue-configured subclasses (see
# agents_docs/working_with_hosted_mcp.md). The defaults are a working
# single-tenant, deny-all connector (authenticates, offers no tools). A
# tenancy-aware connector also adds its scoped routes in project/urls.py.
MCP_ENDPOINT_VIEW = env("MCP_ENDPOINT_VIEW", default="speedpycom.api.mcp.MCPEndpointView")
MCP_METADATA_VIEW = env(
    "MCP_METADATA_VIEW", default="speedpycom.api.mcp_metadata.MCPProtectedResourceMetadataView"
)

# --- CORS ---
CORS_ALLOWED_ORIGINS = env.list("CORS_ALLOWED_ORIGINS", default=[])
CORS_ALLOW_ALL_ORIGINS = env.bool("CORS_ALLOW_ALL_ORIGINS", default=DEBUG)
CORS_ALLOW_CREDENTIALS = env.bool("CORS_ALLOW_CREDENTIALS", default=False)
CORS_URLS_REGEX = r"^/api/"

if CORS_ALLOW_ALL_ORIGINS and not DEBUG:
    raise ImproperlyConfigured(
        "CORS_ALLOW_ALL_ORIGINS=True is not allowed when DEBUG=False. "
        "Set explicit CORS_ALLOWED_ORIGINS instead."
    )

SPECTACULAR_SETTINGS = {
    "TITLE": "SpeedPy API",
    "DESCRIPTION": "HTTP API for SpeedPy.",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
    "SCHEMA_PATH_PREFIX": r"/api/v[0-9]",
    "TAGS": [
        {"name": "auth", "description": "JWT token lifecycle — obtain, refresh, and revoke access tokens."},
        {"name": "user", "description": "Authenticated user profile — read and update the current user."},
        {"name": "teams", "description": "Team management — list teams, members, and create invitations."},
        {"name": "products", "description": "Product catalog (demo) — read-only product listing."},  # SPEEDPY_DEMO
        {"name": "webhooks", "description": "Webhook management — CRUD endpoints, deliveries, rotate secrets, test and retry."},
        {"name": "jobs", "description": "Async jobs — start background tasks and poll for status (202 + status URL pattern)."},
        {"name": "integration", "description": "Integration discovery — machine-readable manifest for agents and automation clients."},
        {"name": "oauth2", "description": "OAuth2 — Dynamic Client Registration (RFC 7591)."},
    ],
    "SECURITY": [
        {"sessionAuth": []},
        {"bearerAuth": []},
        {"jwtAuth": []},
        {"oauth2": ["read:profile"]},
    ],
    "APPEND_COMPONENTS": {
        "securitySchemes": {
            "sessionAuth": {
                "type": "apiKey",
                "in": "cookie",
                "name": "sessionid",
            },
            "bearerAuth": {
                "type": "http",
                "scheme": "bearer",
                "description": "Personal access token. Create at /accounts/tokens/.",
            },
            "jwtAuth": {
                "type": "http",
                "scheme": "bearer",
                "bearerFormat": "JWT",
                "description": "JWT access token from /api/auth/token/.",
            },
            "oauth2": {
                "type": "oauth2",
                "flows": {
                    "authorizationCode": {
                        "authorizationUrl": "/o/authorize/",
                        "tokenUrl": "/o/token/",
                        "scopes": {
                            "read:profile": "Read your profile",
                            "write:profile": "Update your profile",
                            "read:teams": "Read your teams and members",
                            "write:teams": "Create invitations and manage teams",
                            "read:products": "Read products",  # SPEEDPY_DEMO
                            "read:webhooks": "List and inspect webhook endpoints and deliveries",
                            "write:webhooks": "Create, update, and delete webhook endpoints",
                            "read:jobs": "Poll job status",
                            "write:jobs": "Start background jobs",
                            "admin": "Administrative access",
                        },
                    },
                },
                "description": "OAuth2 Authorization Code + PKCE. Device flow also available at /o/device-authorization/.",
            },
        },
    },
}

REQUIRE_TOS_ACCEPTANCE = True
REQUIRE_DPA_ACCEPTANCE = True
TOS_LINK = env("TOS_LINK", default="/")
DPA_LINK = env("DPA_LINK", default="/")

SIGNUP_EMAIL_MX_CHECK = env.bool("SIGNUP_EMAIL_MX_CHECK", default=True)
# Email deliverability (speedpycom/services/email_deliverability.py). One
# validator for every door an address comes through: signup, invitations, public
# forms, imports. A bounce costs SES reputation, and above ~5% SES suspends the
# account, so refusing a typo while the person is still looking at the form is
# the cheapest moment to catch it.
# Off while the test suite runs, unless a test asks for it. This is a real DNS
# call: leaving it on makes every test that touches an email address depend on
# the network and on whatever example.com's zone happens to say today, which is
# a flaky-test factory. Tests that want it use
# @override_settings(EMAIL_DELIVERABILITY_CHECK=True) and mock the resolver.
_RUNNING_TESTS = "test" in sys.argv or "PYTEST_CURRENT_TEST" in os.environ
EMAIL_DELIVERABILITY_CHECK = env.bool(
    "EMAIL_DELIVERABILITY_CHECK", default=not DEBUG and not _RUNNING_TESTS
)
# 2s, not the 5s the inline signup check used: this now runs on public forms, and
# five seconds of a worker per submission is a denial-of-service assist.
EMAIL_MX_TIMEOUT_SECONDS = env.float("EMAIL_MX_TIMEOUT_SECONDS", default=2.0)
EMAIL_MX_CACHE_SECONDS = env.int("EMAIL_MX_CACHE_SECONDS", default=86400)
# Shorter than the positive TTL on purpose, so a domain that has just fixed its
# DNS is not refused for the rest of the day.
EMAIL_MX_NEGATIVE_CACHE_SECONDS = env.int(
    "EMAIL_MX_NEGATIVE_CACHE_SECONDS", default=3600
)
# RFC 5321 says a domain with only an A record is deliverable. Off by default,
# deliberately: the strict default refuses a few technically-valid domains, and
# that is the cheaper mistake than a bounce.
EMAIL_MX_ALLOW_IMPLICIT_MX = env.bool("EMAIL_MX_ALLOW_IMPLICIT_MX", default=False)

DEBUG_TOOLBAR_CONFIG = {
    "SHOW_TOOLBAR_CALLBACK": lambda request: DEBUG,
}
_EMAIL_URL_DEFAULT = "smtp://user:password@localhost:25"
# If EMAIL_URL is set but empty, remove it so the default is used.
# A non-empty but invalid EMAIL_URL will still raise an error as expected.
if env.str("EMAIL_URL", default=None) == "":
    os.environ.pop("EMAIL_URL", None)
email_config = env.email_url("EMAIL_URL", default=_EMAIL_URL_DEFAULT)

EMAIL_BACKEND = "post_office.EmailBackend"
EMAIL_HOST = email_config["EMAIL_HOST"]
EMAIL_PORT = email_config["EMAIL_PORT"]
EMAIL_HOST_USER = email_config["EMAIL_HOST_USER"]
EMAIL_HOST_PASSWORD = email_config["EMAIL_HOST_PASSWORD"]
EMAIL_USE_TLS = email_config.get("EMAIL_USE_TLS", False)
EMAIL_USE_SSL = email_config.get("EMAIL_USE_SSL", False)
DEFAULT_FROM_EMAIL = env.str("DEFAULT_FROM_EMAIL", default="admin@example.com")
SERVER_EMAIL = env.str("SERVER_EMAIL", default=DEFAULT_FROM_EMAIL)

# Pluggable email sending: EMAIL_PROVIDER picks the backend post_office delegates
# to. The outer EMAIL_BACKEND stays post_office (queuing + Celery); only the inner
# sending backend changes. See project/email_providers.py for the provider map.
# console/smtp use Django's built-in backends; the rest go through django-anymail.
EMAIL_PROVIDER = env.str("EMAIL_PROVIDER", default="console").lower().strip() or "console"
POST_OFFICE = {
    "BACKENDS": {
        # Every outgoing message passes the suppression guard, which then hands
        # off to resolve_email_backend(EMAIL_PROVIDER). Wrapping here rather
        # than at each call site is the point: allauth, team invitations and any
        # third-party package are all covered without touching their code.
        "default": "speedpycom.email_backends.SuppressionAwareEmailBackend",
    },
    "DEFAULT_PRIORITY": "now",
    "CELERY_ENABLED": True,
}

# --- Bounce and complaint handling -------------------------------------------
# Two halves, and the difference matters when you change ESP:
#
#   Enforcement — provider-agnostic. The SuppressedEmail list plus the backend
#   above. An address that hard-bounced is never ATTEMPTED again, because ESPs
#   throttle and eventually suspend an account that keeps hard-bouncing.
#
#   Detection — how you learn an address bounced. What ships here is SES via SNS
#   (speedpycom/services/sns.py, opt-in URLs in speedpycom/urls_email_events.py).
#   On another ESP, write that half and call
#   speedpycom.services.email_events.suppress() from it.
#
# See docs/email-bounces.md.

#: The SNS topic SES publishes delivery events to. **Set this before you
#: subscribe the endpoint.** While it is empty the webhook accepts any topic —
#: which lets the subscription handshake complete before you know the ARN, but
#: also means anyone who creates their own SNS topic can post to you with a
#: genuine AWS signature.
SES_EVENT_TOPIC_ARN = env.str("SES_EVENT_TOPIC_ARN", default="")

#: SES sends no events at all unless the message went out through a
#: configuration set that has an event destination attached. Omitting this is
#: silent: mail delivers perfectly and no events ever arrive.
AWS_SES_CONFIGURATION_SET = env.str("AWS_SES_CONFIGURATION_SET", default="")

#: Optional dotted path to a callable taking a recipient address and returning a
#: Team or None, used to attribute an event to a tenant. Unset means no
#: attribution, which is the right default for a single-tenant project.
#: Whatever you point this at MUST return None when the answer is ambiguous.
SPEEDPY_EMAIL_EVENT_TEAM_RESOLVER = env.str(
    "SPEEDPY_EMAIL_EVENT_TEAM_RESOLVER", default=""
)

# --- Blocking email addresses by domain --------------------------------------
# Two lists, kept apart on purpose: the bundled one is replaced wholesale when
# refreshed from upstream, so project-specific domains would be lost if they
# lived in it. See speedpycom/data/README.md and AGENTS.md.

#: Block the ~8,000 throwaway-mail providers bundled in
#: speedpycom/data/disposable_email_blocklist.conf.
#: NOTE FOR UPGRADERS: this is on by default, so signups from mailinator and
#: friends start being refused as soon as you take this version. Set it to False
#: if you were relying on accepting them.
SPEEDPY_BLOCK_DISPOSABLE_EMAIL_DOMAINS = env.bool(
    "SPEEDPY_BLOCK_DISPOSABLE_EMAIL_DOMAINS", default=True
)

#: The project's own list. One domain per line, `#` comments allowed, and a
#: leading dot (".example.com") also covers subdomains. Missing file is fine.
SPEEDPY_BLOCKED_EMAIL_DOMAINS_FILE = env.str(
    "SPEEDPY_BLOCKED_EMAIL_DOMAINS_FILE",
    default=str(BASE_DIR / "blocked_email_domains.txt"),
)

#: Extra domains from the environment, for a one-off block without a deploy of
#: the file. Merged with the file rather than replacing it.
SPEEDPY_BLOCKED_EMAIL_DOMAINS = env.list(
    "SPEEDPY_BLOCKED_EMAIL_DOMAINS", default=[]
)

#: Shown to people whose address we stopped emailing, on the account email page.
SUPPORT_EMAIL = env.str("SUPPORT_EMAIL", default="")

#: Where contact-form submissions are emailed. Defaults to SUPPORT_EMAIL; set a
#: dedicated inbox here to route them elsewhere. When empty, the notification
#: email is skipped (the submission is still saved to the database).
CONTACT_NOTIFICATION_EMAIL = env.str("CONTACT_NOTIFICATION_EMAIL", default=SUPPORT_EMAIL)

# Telegram ops notifications
# ---------------------------------------------------------------------------
# Bot token (from @BotFather) and the chat id of the admin/user to notify about
# ops events (new sign-ups, contact submissions, ...). When either is empty,
# ops notifications are silently disabled — safe to leave unset everywhere.
TELEGRAM_OPS_BOT_TOKEN = env.str("TELEGRAM_OPS_BOT_TOKEN", default="")
TELEGRAM_OPS_CHAT_ID = env.str("TELEGRAM_OPS_CHAT_ID", default="")

# SES goes through Anymail's boto3 session params rather than django-ses globals.
# Only pass explicit AWS keys when provided so that, when they are omitted, boto3
# falls back to its standard credential chain (IAM role, ~/.aws/credentials, etc.).
_AMAZON_SES_CLIENT_PARAMS = {"region_name": env.str("AWS_SES_REGION_NAME", default="eu-central-1")}
_aws_access_key_id = env.str("AWS_SES_ACCESS_KEY_ID", default="")
_aws_secret_access_key = env.str("AWS_SES_SECRET_ACCESS_KEY", default="")
if _aws_access_key_id and _aws_secret_access_key:
    _AMAZON_SES_CLIENT_PARAMS["aws_access_key_id"] = _aws_access_key_id
    _AMAZON_SES_CLIENT_PARAMS["aws_secret_access_key"] = _aws_secret_access_key

# Anymail per-ESP credentials. Placeholder defaults let the app boot without real
# keys; the selected provider will fail at send time until real credentials and a
# verified sender/domain are configured.
ANYMAIL = {
    "MAILGUN_API_KEY": env.str("MAILGUN_API_KEY", default="change_me"),
    "MAILGUN_SENDER_DOMAIN": env.str("MAILGUN_SENDER_DOMAIN", default="example.com"),
    "MAILGUN_API_URL": env.str("MAILGUN_API_URL", default="https://api.mailgun.net/v3"),
    "SENDGRID_API_KEY": env.str("SENDGRID_API_KEY", default="change_me"),
    "POSTMARK_SERVER_TOKEN": env.str("POSTMARK_SERVER_TOKEN", default="change_me"),
    "RESEND_API_KEY": env.str("RESEND_API_KEY", default="change_me"),
    "AMAZON_SES_CLIENT_PARAMS": _AMAZON_SES_CLIENT_PARAMS,
    # `or None`, not `or ""`: Anymail tests `is not None`, so an empty string
    # would send ConfigurationSetName="" and SES would reject every message.
    "AMAZON_SES_CONFIGURATION_SET_NAME": AWS_SES_CONFIGURATION_SET or None,
}

DEFAULT_ADMIN_PASSWORD = env("DEFAULT_ADMIN_PASSWORD", default=None)
DEMO_MODE = env.bool("DEMO_MODE", default=False)  # SPEEDPY_DEMO: fills login credentials on login form for demo purposes
SPEEDPY_TEAMS_ENABLED = env.bool("SPEEDPY_TEAMS_ENABLED", default=True)  # enable/disable teams functionality
# Owner-requested team deletion. 0 deletes on the click; anything else schedules
# the deletion that many hours out and lets the owner undo it until then. The
# team keeps working during the window — it is not deleted yet, and the undo
# button lives on the team settings page, which an inactive team cannot reach.
SPEEDPY_TEAM_DELETION_DELAY_HOURS = max(
    0, env.int("SPEEDPY_TEAM_DELETION_DELAY_HOURS", default=24)
)
# Dotted paths called with the team just before its rows go, for whatever the
# database cascade cannot reach (object storage, CDN, a provider's customer
# record). Each must be idempotent and must raise on failure — a raising hook
# keeps the team scheduled so the next run retries. See
# mainapp/models/teams.py::run_team_cleanup_hooks.
SPEEDPY_TEAM_DELETION_CLEANUP_HOOKS = env.list(
    "SPEEDPY_TEAM_DELETION_CLEANUP_HOOKS", default=[]
)

# Signups that never confirmed an email address. Verification is mandatory, so
# such a row can never be used — and if the address is suppressed, no further
# confirmation can even be sent. OFF by default: a boilerplate that deletes user
# accounts on a timer without being asked would be a nasty surprise. 7 is the
# recommended value, and the window MUST exceed
# ACCOUNT_EMAIL_CONFIRMATION_EXPIRE_DAYS (allauth's default is 3) or the purge
# races the last valid click on a confirmation link. Preview with
# `manage.py purge_unconfirmed_accounts --dry-run` before switching it on.
SPEEDPY_UNCONFIRMED_ACCOUNT_PURGE_DAYS = max(
    0, env.int("SPEEDPY_UNCONFIRMED_ACCOUNT_PURGE_DAYS", default=0)
)
# Called with the user before the row goes, for what the cascade cannot reach.
# The team entry is not optional in a teams project: Team has no FK to a user,
# so without it every purged signup leaves its auto-provisioned team behind.
SPEEDPY_UNCONFIRMED_ACCOUNT_PURGE_HOOKS = env.list(
    "SPEEDPY_UNCONFIRMED_ACCOUNT_PURGE_HOOKS",
    default=["mainapp.models.teams.delete_sole_member_teams"],
)
# Subclass this rather than editing the service (see speedpycom/services/account_purge.py).
SPEEDPY_UNCONFIRMED_ACCOUNT_PURGE_CLASS = env.str(
    "SPEEDPY_UNCONFIRMED_ACCOUNT_PURGE_CLASS",
    default="speedpycom.services.account_purge.UnconfirmedAccountPurge",
)
SPEEDPY_MFA_BACKEND = env.str("SPEEDPY_MFA_BACKEND", default="allauth_mfa")  # "django_otp" or "allauth_mfa"

# Token issuance gates — all on by default (conservative).
SPEEDPY_API_TOKEN_REQUIRE_VERIFIED_EMAIL = env.bool("SPEEDPY_API_TOKEN_REQUIRE_VERIFIED_EMAIL", default=True)
SPEEDPY_JWT_REQUIRE_MFA = env.bool("SPEEDPY_JWT_REQUIRE_MFA", default=True)
SPEEDPY_PAT_REQUIRE_RECENT_REAUTH = env.bool("SPEEDPY_PAT_REQUIRE_RECENT_REAUTH", default=True)

# API access audit log — off by default; enable for full per-request audit trail.
SPEEDPY_API_ACCESS_LOG_ENABLED = env.bool("SPEEDPY_API_ACCESS_LOG_ENABLED", default=False)

# ---------------------------------------------------------------------------
# Billing (pluggable Stripe / Paddle)
# ---------------------------------------------------------------------------
# Billing is OFF by default so fresh/demo installs work without provider
# credentials. When enabled, SPEEDPY_BILLING_PROVIDER selects which adapter
# handles new checkout/portal actions; existing subscriptions retain whichever
# provider created them. The billable object is the Team when teams are enabled
# and the User when they are disabled (see mainapp.billing.state).
SPEEDPY_BILLING_ENABLED = env.bool("SPEEDPY_BILLING_ENABLED", default=False)
SPEEDPY_BILLING_PROVIDER = env.str("SPEEDPY_BILLING_PROVIDER", default="")  # "stripe" or "paddle"
# Days a past-due subscription keeps paid runtime features (grace) before billing
# is disabled. New records are blocked during grace; runtime checks fail closed
# after it.
SPEEDPY_BILLING_GRACE_PERIOD_DAYS = env.int("SPEEDPY_BILLING_GRACE_PERIOD_DAYS", default=30)

# Stripe
# --- Outbound webhooks (REST Hooks) --------------------------------------
# A project may gate webhook endpoints on a plan feature by pointing
# SPEEDPY_WEBHOOK_TEAM_ELIGIBLE at a "(team) -> bool" callable and setting the
# 403 message in SPEEDPY_WEBHOOK_FEATURE_DENIED_DETAIL. Unset = every active
# team may hold endpoints (the default).
SPEEDPY_WEBHOOK_TEAM_ELIGIBLE = None
SPEEDPY_WEBHOOK_FEATURE_DENIED_DETAIL = "This team's plan does not include webhook access."
WEBHOOK_MAX_ACTIVE_ENDPOINTS_PER_TEAM = 50
# Delivery-log retention: redact payload/response after RETENTION_DAYS, delete
# the row after DELETE_DAYS. Delivery payloads can carry third-party PII.
WEBHOOK_DELIVERY_RETENTION_DAYS = 30
WEBHOOK_DELIVERY_DELETE_DAYS = 90

STRIPE_SECRET_KEY = env.str("STRIPE_SECRET_KEY", default="")
STRIPE_PUBLISHABLE_KEY = env.str("STRIPE_PUBLISHABLE_KEY", default="")
STRIPE_WEBHOOK_SECRET = env.str("STRIPE_WEBHOOK_SECRET", default="")

# Paddle (Billing v2)
PADDLE_ENVIRONMENT = env.str("PADDLE_ENVIRONMENT", default="sandbox")  # "sandbox" or "production"
PADDLE_API_KEY = env.str("PADDLE_API_KEY", default="")
PADDLE_CLIENT_TOKEN = env.str("PADDLE_CLIENT_TOKEN", default="")  # browser-safe, checkout only
PADDLE_WEBHOOK_SECRET = env.str("PADDLE_WEBHOOK_SECRET", default="")

# Per-plan provider price IDs. Read by mainapp.subscription_plans via _price_id();
# a missing ID simply means that plan/interval is not yet available for checkout.
STRIPE_PRICE_PRO_MONTHLY = env.str("STRIPE_PRICE_PRO_MONTHLY", default="")
STRIPE_PRICE_PRO_YEARLY = env.str("STRIPE_PRICE_PRO_YEARLY", default="")
STRIPE_PRICE_BUSINESS_MONTHLY = env.str("STRIPE_PRICE_BUSINESS_MONTHLY", default="")
STRIPE_PRICE_BUSINESS_YEARLY = env.str("STRIPE_PRICE_BUSINESS_YEARLY", default="")
PADDLE_PRICE_PRO_MONTHLY = env.str("PADDLE_PRICE_PRO_MONTHLY", default="")
PADDLE_PRICE_PRO_YEARLY = env.str("PADDLE_PRICE_PRO_YEARLY", default="")
PADDLE_PRICE_BUSINESS_MONTHLY = env.str("PADDLE_PRICE_BUSINESS_MONTHLY", default="")
PADDLE_PRICE_BUSINESS_YEARLY = env.str("PADDLE_PRICE_BUSINESS_YEARLY", default="")

if SPEEDPY_MFA_BACKEND == "django_otp":
    INSTALLED_APPS += [
        "django_otp",
        "django_otp.plugins.otp_totp",
        "django_otp.plugins.otp_static",
    ]
elif SPEEDPY_MFA_BACKEND == "allauth_mfa":
    INSTALLED_APPS += ["allauth.mfa"]

if SPEEDPY_MFA_BACKEND == "django_otp":
    _auth_idx = MIDDLEWARE.index("django.contrib.auth.middleware.AuthenticationMiddleware")
    MIDDLEWARE.insert(_auth_idx + 1, "django_otp.middleware.OTPMiddleware")
RECAPTCHA_PUBLIC_KEY = env("RECAPTCHA_PUBLIC_KEY", default="")
RECAPTCHA_PRIVATE_KEY = env("RECAPTCHA_PRIVATE_KEY", default="")
RECAPTCHA_REQUIRED_SCORE = env.float("RECAPTCHA_REQUIRED_SCORE", default=0.5)
# Applies to BOTH the auth forms and speedpycom.services.captcha, so the two
# cannot drift onto different timeouts. 10s (django-recaptcha's default) is a
# long time to hold a worker on a public POST path.
RECAPTCHA_VERIFY_REQUEST_TIMEOUT = env.int("RECAPTCHA_VERIFY_REQUEST_TIMEOUT", default=5)
# CAPTCHA on PUBLIC (unauthenticated) forms — see speedpycom/services/captcha.py.
# Swapping provider is a setting, not a rewrite. Both these are inert until
# RECAPTCHA_PUBLIC_KEY and RECAPTCHA_PRIVATE_KEY are set.
CAPTCHA_PROVIDER = env(
    "CAPTCHA_PROVIDER", default="speedpycom.services.captcha.recaptcha_v3"
)
# The score below which a verified visitor is FLAGGED (never refused). Separate
# from RECAPTCHA_REQUIRED_SCORE on purpose: that one rejects a login, this one
# only annotates a public submission for whoever reviews it.
CAPTCHA_MIN_SCORE = env.float("CAPTCHA_MIN_SCORE", default=0.5)
# The floor for a caller that guards a COST rather than a queue — lower on
# purpose. See speedpycom/services/captcha.py::gate_min_score.
CAPTCHA_GATE_MIN_SCORE = env.float("CAPTCHA_GATE_MIN_SCORE", default=0.3)
SILENCED_SYSTEM_CHECKS = ["django_recaptcha.recaptcha_test_key_error"]

LOGO_PATH = "static/mainapp/speedpy_logo.png"
LOGO_PATH_TEMPLATE = LOGO_PATH.removeprefix("static/") if LOGO_PATH.startswith("static/") else LOGO_PATH
TITLE = "SpeedPy"
TAGLINE = "Django-based SaaS boilerplate"
DEFAULT_SCHEMA = "https://" if not DEBUG else "http://"
SITE_URL = env("SITE_URL", default=None)
if not SITE_URL:
    try:
        first_host = ALLOWED_HOSTS[0]
        if first_host != "*":
            SITE_URL = DEFAULT_SCHEMA + ALLOWED_HOSTS[0]
    except IndexError:
        pass

if not SITE_URL:
    logger.warning("SITE_URL not set")

# --- Hosted MCP: OAuth hardening (applied only when MCP_ENABLED) ---
# The MCP-specific OAuth behaviour. Defined unconditionally so it is inspectable
# and testable, but merged into OAUTH2_PROVIDER only when MCP is enabled — a fork
# that never runs MCP keeps DOT's stock validator and default flags unchanged.
#
MCP_OAUTH2_PROVIDER_OVERRIDES = {
    # RFC 8707 audience matching by equality (never a prefix), and the CIMD
    # public-downgrade validator.
    "OAUTH2_VALIDATOR_CLASS": "speedpycom.api.oauth_validator.SpeedPyOAuth2Validator",
    "RESOURCE_SERVER_TOKEN_RESOURCE_VALIDATOR": "speedpycom.api.mcp_audience.validate_resource_exact",
    # Client ID Metadata Documents — both directories prefer them for one-click
    # connect. Safe ONLY because MCP_ENABLED also mounts the hardened consent
    # screen (speedpycom.api.oauth_consent), which names a CIMD client by the
    # host of its client_id URL rather than its self-asserted client_name. Never
    # turn this on without that view. See project/urls.py and
    # agents_docs/working_with_hosted_mcp.md.
    "CIMD_ENABLED": True,
    # RFC 9700 refresh-token replay protection for the public connector client
    # (pairs with ROTATE_REFRESH_TOKEN, already on).
    "REFRESH_TOKEN_REUSE_PROTECTION": True,
    # RFC 9700 refusals of grants/params we never want, plus the S256 requirement
    # both stores always send.
    "COMPLIANT_BCP_RFC9700_IMPLICIT_GRANT": True,
    "COMPLIANT_BCP_RFC9700_PASSWORD_GRANT": True,
    "COMPLIANT_BCP_RFC9700_PKCE_METHOD": True,
    "COMPLIANT_BCP_RFC9700_ACCESS_TOKEN_TRANSPORT": True,
    # RFC 9207 `iss` on authorization responses — earns ChatGPT's fixed connector
    # redirect URI and defends the client against a mix-up attack.
    "COMPLIANT_BCP_RFC9700_AUTHZ_RESPONSE_ISS": True,
    # Advertise "none" (public PKCE) in the authorization-server metadata
    # alongside the confidential methods. This is a discovery signal, not the
    # authentication decision (that follows Application.client_type); a CIMD
    # client that does not see "none" advertised falls through to looking for a
    # registration endpoint we do not offer.
    "OAUTH2_TOKEN_ENDPOINT_AUTH_METHODS_SUPPORTED": [
        "client_secret_basic",
        "client_secret_post",
        "none",
    ],
    # Native clients (Claude Code, Cursor) bind a loopback port at runtime;
    # `localhost` loopback matching needs this.
    "ALLOW_LOCALHOST_LOOPBACK": True,
}
if MCP_ENABLED:
    OAUTH2_PROVIDER.update(MCP_OAUTH2_PROVIDER_OVERRIDES)
    if SITE_URL:
        # RFC 9207 issuer; DOT emits `iss` from this.
        OAUTH2_PROVIDER["OIDC_ISS_ENDPOINT"] = SITE_URL.rstrip("/")

# MFA / TOTP Configuration
TOTP_ISSUER = env.str("TOTP_ISSUER", default="")

if SPEEDPY_MFA_BACKEND == "django_otp":
    OTP_TOTP_ISSUER = TOTP_ISSUER
    OTP_LOGIN_URL = reverse_lazy("account_login_otp")
elif SPEEDPY_MFA_BACKEND == "allauth_mfa":
    MFA_TOTP_ISSUER = TOTP_ISSUER
    MFA_RECOVERY_CODE_COUNT = env.int("MFA_RECOVERY_CODE_COUNT", default=10)
    MFA_SUPPORTED_TYPES = ["totp", "recovery_codes"]
