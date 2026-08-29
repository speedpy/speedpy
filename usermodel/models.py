import hashlib
import os
import secrets
import uuid

from django.db import models
from django.contrib.auth.base_user import AbstractBaseUser
from django.contrib.auth.models import PermissionsMixin
from django.core.mail import send_mail
from django.utils.translation import gettext_lazy as _
from django.utils import timezone
from django.conf import settings

from usermodel.managers import UserManager
from usermodel.validators import validate_no_url

# The stored profile picture is downscaled to this box (the original is never
# kept); the thumbnail is derived from it. Both are re-encoded web-native.
PROFILE_PICTURE_SIZE = (512, 512)
PROFILE_THUMBNAIL_SIZE = (96, 96)


class User(AbstractBaseUser, PermissionsMixin):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(
        db_collation=settings.CI_COLLATION,
        max_length=255,
        unique=True,
        error_messages={
            'unique': _('A user with such email already exists')
        }
    )

    first_name = models.CharField(_('First Name'), max_length=50, blank=True, validators=[validate_no_url])
    last_name = models.CharField(_('Last Name'), max_length=50, blank=True, validators=[validate_no_url])
    profile_picture = models.ImageField(
        _('Profile Picture'),
        upload_to='profile_pictures/',
        blank=True,
        null=True,
    )
    profile_picture_thumbnail = models.ImageField(
        _('Profile Picture Thumbnail'),
        upload_to='profile_pictures/thumbnails/',
        blank=True,
        null=True,
        editable=False,
    )
    is_staff = models.BooleanField(
        _('Staff Status'),
        default=False,
        help_text=_('Designates whether the user can log into this admin site.')
    )
    is_active = models.BooleanField(
        _('Active'),
        default=True,
        help_text=_('Designates whether this user should be treated as active.')
    )

    is_email_confirmed = models.BooleanField(
        _('Email Confirmed'),
        default=False
    )
    date_joined = models.DateTimeField(
        _('Date Joined'),
        default=timezone.now
    )

    objects = UserManager()

    EMAIL_FIELD = 'email'
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = [
        'first_name',
        'last_name',
    ]

    class Meta:
        verbose_name = _('User')
        verbose_name_plural = _('Users')

    def clean(self):
        super().clean()
        self.email = self.__class__.objects.normalize_email(self.email)

    def get_full_name(self):
        return f"{self.first_name} {self.last_name}"

    def get_short_name(self):
        return f"{self.first_name}"

    def email_user(self, subject, message, from_email=None, **kwargs):
        send_mail(subject, message, from_email, recipient_list=[self.email], **kwargs)

    def save(self, *args, **kwargs):
        process_picture = False
        if self.profile_picture:
            if self.pk:
                previous = type(self).objects.filter(pk=self.pk).first()
                previous_name = previous.profile_picture.name if previous and previous.profile_picture else ''
                if previous_name != self.profile_picture.name:
                    process_picture = True
            else:
                process_picture = True
        elif self.profile_picture_thumbnail:
            self.profile_picture_thumbnail.delete(save=False)

        if process_picture:
            self._process_profile_picture()
            # Both derived fields must persist even when the caller restricts
            # update_fields — the profile API saves update_fields=['profile_picture'].
            update_fields = kwargs.get('update_fields')
            if update_fields is not None:
                kwargs['update_fields'] = set(update_fields) | {
                    'profile_picture', 'profile_picture_thumbnail'
                }

        super().save(*args, **kwargs)

    def _process_profile_picture(self):
        """Downscale + convert the uploaded picture to a web-native format and
        derive the thumbnail from it. The full-resolution original is never
        stored (avatars display small — no need to waste space), and HEIC is
        converted so it renders in every browser. See speedpycom.images."""
        from speedpycom.images import prepare_image

        source = self.profile_picture
        main = prepare_image(source, max(PROFILE_PICTURE_SIZE))
        source.seek(0)
        thumbnail = prepare_image(source, max(PROFILE_THUMBNAIL_SIZE))

        # Replace the upload with the processed image before the row is written,
        # so the original bytes are never committed to storage.
        self.profile_picture.save(main.name, main, save=False)

        base_name, _ext = os.path.splitext(os.path.basename(self.profile_picture.name))
        thumb_ext = os.path.splitext(thumbnail.name)[1] or '.jpg'
        self.profile_picture_thumbnail.save(
            f"{base_name}_thumb{thumb_ext}",
            thumbnail,
            save=False,
        )


TOKEN_PREFIX = "spd_"
TOKEN_BYTE_LENGTH = 32


def _generate_token():
    """Generate a random token with a recognizable prefix."""
    raw = secrets.token_hex(TOKEN_BYTE_LENGTH)
    return f"{TOKEN_PREFIX}{raw}"


def _hash_token(raw_token):
    """SHA-256 hash for token storage."""
    return hashlib.sha256(raw_token.encode()).hexdigest()


class PersonalAccessToken(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="personal_access_tokens",
    )
    name = models.CharField(_("Token name"), max_length=255)
    token_hash = models.CharField(
        _("Token hash"), max_length=64, unique=True, editable=False
    )
    scopes = models.JSONField(
        _("Scopes"),
        default=list,
        blank=True,
        help_text=_("List of scope strings, e.g. ['read:profile', 'read:teams']."),
    )
    created_at = models.DateTimeField(_("Created"), auto_now_add=True)
    last_used_at = models.DateTimeField(_("Last used"), null=True, blank=True)
    expires_at = models.DateTimeField(
        _("Expires"),
        null=True,
        blank=True,
        help_text=_("Leave blank for a non-expiring token."),
    )
    is_revoked = models.BooleanField(_("Revoked"), default=False)

    class Meta:
        ordering = ("-created_at",)
        verbose_name = _("Personal access token")
        verbose_name_plural = _("Personal access tokens")

    def __str__(self):
        return f"{self.name} ({self.user.email})"

    @classmethod
    def create_token(cls, user, name, scopes=None, expires_at=None):
        """
        Create a new PAT and return (instance, raw_token).

        The raw_token is only available at creation time — it is not stored.
        """
        raw_token = _generate_token()
        pat = cls.objects.create(
            user=user,
            name=name,
            token_hash=_hash_token(raw_token),
            scopes=scopes or [],
            expires_at=expires_at,
        )
        return pat, raw_token

    @classmethod
    def authenticate(cls, raw_token):
        """
        Look up a PAT by its raw token value.

        Returns the PAT instance if valid, None otherwise.
        """
        token_hash = _hash_token(raw_token)
        try:
            pat = cls.objects.select_related("user").get(
                token_hash=token_hash, is_revoked=False
            )
        except cls.DoesNotExist:
            return None

        if pat.expires_at and pat.expires_at <= timezone.now():
            return None

        return pat

    def revoke(self):
        """Immediately revoke this token."""
        self.is_revoked = True
        self.save(update_fields=["is_revoked"])

    def record_usage(self):
        """Update last_used_at timestamp."""
        self.last_used_at = timezone.now()
        self.save(update_fields=["last_used_at"])

    @property
    def is_expired(self):
        if not self.expires_at:
            return False
        return self.expires_at <= timezone.now()


def _truncate_ip(ip_string):
    """Truncate an IP address for privacy: zero last octet (IPv4 /24) or mask to /48 (IPv6)."""
    import ipaddress

    if not ip_string:
        return ""
    try:
        addr = ipaddress.ip_address(ip_string)
    except ValueError:
        return ""
    if isinstance(addr, ipaddress.IPv4Address):
        network = ipaddress.IPv4Network(f"{addr}/24", strict=False)
        return str(network.network_address)
    # IPv6 — mask to /48
    network = ipaddress.IPv6Network(f"{addr}/48", strict=False)
    return str(network.network_address)


class ApiAccessLog(models.Model):
    """Per-request audit trail for API access, gated by SPEEDPY_API_ACCESS_LOG_ENABLED."""

    id = models.BigAutoField(primary_key=True)
    timestamp = models.DateTimeField(_("Timestamp"), default=timezone.now, db_index=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="api_access_logs",
    )
    token_type = models.CharField(
        _("Token type"), max_length=16, blank=True,
        help_text=_("e.g. 'pat', 'oauth2', 'jwt', 'session'"),
    )
    token_id = models.CharField(
        _("Token ID"), max_length=64, blank=True,
        help_text=_("PAT UUID or OAuth2 token PK — never the raw secret."),
    )
    scopes = models.JSONField(_("Scopes"), default=list, blank=True)
    method = models.CharField(_("HTTP method"), max_length=10)
    path = models.CharField(_("Request path"), max_length=2048)
    status_code = models.PositiveSmallIntegerField(_("Status code"), null=True, blank=True)
    ip_truncated = models.CharField(_("IP (truncated)"), max_length=45, blank=True)
    request_id = models.CharField(_("Request ID"), max_length=128, blank=True, db_index=True)
    user_agent = models.CharField(_("User-Agent"), max_length=512, blank=True)

    class Meta:
        ordering = ("-timestamp",)
        verbose_name = _("API access log")
        verbose_name_plural = _("API access logs")
        indexes = [
            models.Index(fields=["user", "-timestamp"], name="accesslog_user_ts"),
        ]

    def __str__(self):
        return f"{self.method} {self.path} [{self.status_code}]"
