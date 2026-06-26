from datetime import timedelta
from pathlib import Path
import environ
import os
import structlog
from django.core.exceptions import ImproperlyConfigured
from django.urls import reverse_lazy

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

ADMIN_URL = env.str("ADMIN_URL", default="admin/")
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
    "usermodel.apps.UsermodelConfig",
    "speedpycom",
    "mainapp.apps.MainappConfig",
    "django_recaptcha",
    "demoapp",
    "rest_framework",
    "drf_spectacular",
    "rest_framework_simplejwt",
    "rest_framework_simplejwt.token_blacklist",
    "oauth2_provider",
    "corsheaders",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
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
                "project.context_processors.demo_mode",
                "project.context_processors.site_url",
                "project.context_processors.og_tags",
                "project.context_processors.teams_enabled",
                "project.context_processors.tours_enabled",
                "project.context_processors.current_year",
                "project.context_processors.mfa_backend",
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
    "loggers": {"": {"handlers": ["console"], "level": "DEBUG"}},
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

MEDIA_ROOT = env("MEDIA_ROOT", default=BASE_DIR / "media")
MEDIA_URL = env("MEDIA_PATH", default="/media/")
WHITENOISE_USE_FINDERS = True
WHITENOISE_AUTOREFRESH = DEBUG
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
        "read:products": "Read products",
        "read:webhooks": "List and inspect webhook endpoints and deliveries",
        "write:webhooks": "Create, update, and delete webhook endpoints",
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

DCR_ENABLED = env.bool("DCR_ENABLED", default=DEBUG)

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
        {"name": "products", "description": "Product catalog (demo) — read-only product listing."},
        {"name": "webhooks", "description": "Webhook management — CRUD endpoints, deliveries, rotate secrets, test and retry."},
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
                            "read:products": "Read products",
                            "read:webhooks": "List and inspect webhook endpoints and deliveries",
                            "write:webhooks": "Create, update, and delete webhook endpoints",
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
POST_OFFICE = {
    "BACKENDS": {
        # "default": "django_ses.SESBackend",
        "default": "django.core.mail.backends.console.EmailBackend",
        # "default": "django.core.mail.backends.smtp.EmailBackend",
    },
    "DEFAULT_PRIORITY": "now",
    "CELERY_ENABLED": True,
}

AWS_SES_REGION_NAME = "eu-central-1"
AWS_SES_REGION_ENDPOINT = "email.eu-central-1.amazonaws.com"
AWS_SES_ACCESS_KEY_ID = env("AWS_SES_ACCESS_KEY_ID", default="change_me")
AWS_SES_SECRET_ACCESS_KEY = env("AWS_SES_SECRET_ACCESS_KEY", default="change_me")
AWS_SES_AUTO_THROTTLE = 0.5

DEFAULT_ADMIN_PASSWORD = env("DEFAULT_ADMIN_PASSWORD", default=None)
DEMO_MODE = env.bool("DEMO_MODE", default=False)  # fills login and password on login form for demo purposes
SPEEDPY_TEAMS_ENABLED = env.bool("SPEEDPY_TEAMS_ENABLED", default=True)  # enable/disable teams functionality
SPEEDPY_MFA_BACKEND = env.str("SPEEDPY_MFA_BACKEND", default="allauth_mfa")  # "django_otp" or "allauth_mfa"

# Token issuance gates — all on by default (conservative).
SPEEDPY_API_TOKEN_REQUIRE_VERIFIED_EMAIL = env.bool("SPEEDPY_API_TOKEN_REQUIRE_VERIFIED_EMAIL", default=True)
SPEEDPY_JWT_REQUIRE_MFA = env.bool("SPEEDPY_JWT_REQUIRE_MFA", default=True)
SPEEDPY_PAT_REQUIRE_RECENT_REAUTH = env.bool("SPEEDPY_PAT_REQUIRE_RECENT_REAUTH", default=True)

# API access audit log — off by default; enable for full per-request audit trail.
SPEEDPY_API_ACCESS_LOG_ENABLED = env.bool("SPEEDPY_API_ACCESS_LOG_ENABLED", default=False)

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

# MFA / TOTP Configuration
TOTP_ISSUER = env.str("TOTP_ISSUER", default="")

if SPEEDPY_MFA_BACKEND == "django_otp":
    OTP_TOTP_ISSUER = TOTP_ISSUER
    OTP_LOGIN_URL = reverse_lazy("account_login_otp")
elif SPEEDPY_MFA_BACKEND == "allauth_mfa":
    MFA_TOTP_ISSUER = TOTP_ISSUER
    MFA_RECOVERY_CODE_COUNT = env.int("MFA_RECOVERY_CODE_COUNT", default=10)
    MFA_SUPPORTED_TYPES = ["totp", "recovery_codes"]
