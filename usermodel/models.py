import os
import uuid
from io import BytesIO

from django.core.files.base import ContentFile
from django.db import models
from django.contrib.auth.base_user import AbstractBaseUser
from django.contrib.auth.models import PermissionsMixin
from django.core.mail import send_mail
from django.utils.translation import gettext_lazy as _
from django.utils import timezone
from django.conf import settings
from PIL import Image

from usermodel.managers import UserManager

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

    first_name = models.CharField(_('First Name'), max_length=50, blank=True)
    last_name = models.CharField(_('Last Name'), max_length=50, blank=True)
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
        regenerate_thumbnail = False
        if self.profile_picture:
            if self.pk:
                previous = type(self).objects.filter(pk=self.pk).first()
                previous_name = previous.profile_picture.name if previous and previous.profile_picture else ''
                if previous_name != self.profile_picture.name:
                    regenerate_thumbnail = True
            else:
                regenerate_thumbnail = True
        elif self.profile_picture_thumbnail:
            self.profile_picture_thumbnail.delete(save=False)

        if regenerate_thumbnail:
            self._generate_profile_picture_thumbnail()

        super().save(*args, **kwargs)

    def _generate_profile_picture_thumbnail(self):
        self.profile_picture.seek(0)
        image = Image.open(self.profile_picture)
        has_alpha = image.mode in ('RGBA', 'LA') or (
            image.mode == 'P' and 'transparency' in image.info
        )
        image = image.convert('RGBA' if has_alpha else 'RGB')
        image.thumbnail(PROFILE_THUMBNAIL_SIZE, Image.Resampling.LANCZOS)

        buffer = BytesIO()
        if has_alpha:
            image.save(buffer, format='PNG', optimize=True)
            extension = 'png'
        else:
            image.save(buffer, format='JPEG', quality=85, optimize=True)
            extension = 'jpg'

        self.profile_picture.seek(0)

        base_name, _ext = os.path.splitext(os.path.basename(self.profile_picture.name))
        self.profile_picture_thumbnail.save(
            f"{base_name}_thumb.{extension}",
            ContentFile(buffer.getvalue()),
            save=False,
        )
