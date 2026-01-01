import uuid
from django.db import models
from django.conf import settings
from django.utils.translation import gettext_lazy as _


class UserOTPProfile(models.Model):
    """Track user OTP preferences and metadata"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='otp_profile'
    )

    # Preferences
    otp_enabled = models.BooleanField(
        default=False,
        help_text=_("Whether user has enabled OTP")
    )
    backup_codes_generated = models.BooleanField(
        default=False,
        help_text=_("Whether backup codes have been generated")
    )

    # Metadata
    enabled_at = models.DateTimeField(null=True, blank=True)
    disabled_at = models.DateTimeField(null=True, blank=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'mainapp_user_otp_profile'
        verbose_name = _('User OTP Profile')
        verbose_name_plural = _('User OTP Profiles')

    def __str__(self):
        return f"OTP Profile for {self.user.email}"

    @property
    def has_active_totp_device(self):
        """Check if user has confirmed TOTP device"""
        from django_otp.plugins.otp_totp.models import TOTPDevice
        return TOTPDevice.objects.filter(
            user=self.user,
            confirmed=True
        ).exists()

    @property
    def has_backup_codes(self):
        """Check if user has backup codes (all existing tokens are unused; used ones are deleted)"""
        from django_otp.plugins.otp_static.models import StaticDevice
        try:
            device = StaticDevice.objects.get(user=self.user, confirmed=True)
            return device.token_set.exists()
        except StaticDevice.DoesNotExist:
            return False
