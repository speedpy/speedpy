import io
import base64
import qrcode
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth import login, get_user_model
from django.views.generic import TemplateView, FormView, View
from django.shortcuts import redirect
from django.urls import reverse_lazy, reverse
from django.contrib import messages
from django.utils import timezone
from django.http import HttpResponseRedirect
from django.core.cache import cache
from django_otp import login as otp_login
from django_otp.plugins.otp_totp.models import TOTPDevice
from django_otp.plugins.otp_static.models import StaticDevice, StaticToken
from django_otp.util import random_hex

from mainapp.forms import (
    OTPSetupVerificationForm,
    OTPTokenForm,
    OTPDisableForm,
)
from mainapp.models import UserOTPProfile

User = get_user_model()


class OTPSetupView(LoginRequiredMixin, TemplateView):
    """Display QR code for initial OTP setup"""
    template_name = 'account/otp/setup.html'

    def get(self, request, *args, **kwargs):
        # Check if user already has OTP enabled
        profile, created = UserOTPProfile.objects.get_or_create(user=request.user)

        if profile.otp_enabled and profile.has_active_totp_device:
            messages.info(request, "Two-factor authentication is already enabled.")
            return redirect('account_otp_settings')

        # Create or get unconfirmed TOTP device
        device, created = TOTPDevice.objects.get_or_create(
            user=request.user,
            confirmed=False,
            defaults={'name': 'default'}
        )

        # If device already exists and is confirmed, create new unconfirmed one
        if not created and device.confirmed:
            # Delete old unconfirmed devices
            TOTPDevice.objects.filter(user=request.user, confirmed=False).delete()
            device = TOTPDevice.objects.create(
                user=request.user,
                name='default',
                confirmed=False
            )

        # Generate QR code
        config_url = device.config_url
        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(config_url)
        qr.make(fit=True)

        img = qr.make_image(fill_color="black", back_color="white")
        buffer = io.BytesIO()
        img.save(buffer, format='PNG')
        img_str = base64.b64encode(buffer.getvalue()).decode()

        context = self.get_context_data(**kwargs)
        context.update({
            'device': device,
            'qr_code': f'data:image/png;base64,{img_str}',
            'secret_key': device.key,
            'form': OTPSetupVerificationForm(),
        })
        return self.render_to_response(context)


class OTPVerifySetupView(LoginRequiredMixin, FormView):
    """Verify OTP token during setup"""
    template_name = 'account/otp/setup.html'
    form_class = OTPSetupVerificationForm
    success_url = reverse_lazy('account_otp_backup_codes')

    def form_valid(self, form):
        token = form.cleaned_data['token']

        # Get unconfirmed device
        try:
            device = TOTPDevice.objects.get(user=self.request.user, confirmed=False)
        except TOTPDevice.DoesNotExist:
            messages.error(self.request, "No OTP device found. Please start setup again.")
            return redirect('account_otp_setup')

        # Verify token
        if device.verify_token(token):
            # Confirm device
            device.confirmed = True
            device.save()

            # Update user profile
            profile, created = UserOTPProfile.objects.get_or_create(user=self.request.user)
            profile.otp_enabled = True
            profile.enabled_at = timezone.now()
            profile.save()

            # Generate backup codes
            self._generate_backup_codes(self.request.user)

            messages.success(
                self.request,
                "Two-factor authentication has been enabled successfully!"
            )
            return super().form_valid(form)
        else:
            messages.error(self.request, "Invalid verification code. Please try again.")
            return redirect('account_otp_setup')

    def _generate_backup_codes(self, user):
        """Generate 10 backup codes"""
        # Delete existing backup codes
        StaticDevice.objects.filter(user=user).delete()

        # Create static device
        device = StaticDevice.objects.create(
            user=user,
            name='backup',
            confirmed=True
        )

        # Generate 10 backup codes
        for _ in range(10):
            token = random_hex(6).upper()  # 6-character hex code
            StaticToken.objects.create(device=device, token=token)

        # Update profile
        profile = UserOTPProfile.objects.get(user=user)
        profile.backup_codes_generated = True
        profile.save()


class OTPBackupCodesView(LoginRequiredMixin, TemplateView):
    """Display backup codes (only shown once after setup or regeneration)"""
    template_name = 'account/otp/backup_codes.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        try:
            device = StaticDevice.objects.get(user=self.request.user, confirmed=True)
            # Get all backup codes (they're all unused if they exist; used ones are deleted)
            backup_codes = device.token_set.all().values_list('token', flat=True)
            context['backup_codes'] = list(backup_codes)
        except StaticDevice.DoesNotExist:
            context['backup_codes'] = []

        return context


class OTPDisableView(LoginRequiredMixin, FormView):
    """Disable OTP (requires password confirmation)"""
    template_name = 'account/otp/disable.html'
    form_class = OTPDisableForm
    success_url = reverse_lazy('account_otp_settings')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def form_valid(self, form):
        user = self.request.user

        # Delete all TOTP devices
        TOTPDevice.objects.filter(user=user).delete()

        # Delete all static devices (backup codes)
        StaticDevice.objects.filter(user=user).delete()

        # Update profile
        try:
            profile = UserOTPProfile.objects.get(user=user)
            profile.otp_enabled = False
            profile.disabled_at = timezone.now()
            profile.backup_codes_generated = False
            profile.save()
        except UserOTPProfile.DoesNotExist:
            pass

        messages.success(self.request, "Two-factor authentication has been disabled.")
        return super().form_valid(form)


class OTPRegenerateBackupCodesView(LoginRequiredMixin, View):
    """Regenerate backup codes"""

    def post(self, request):
        user = request.user

        # Check if OTP is enabled
        try:
            profile = UserOTPProfile.objects.get(user=user)
            if not profile.otp_enabled:
                messages.error(request, "Two-factor authentication is not enabled.")
                return redirect('account_otp_settings')
        except UserOTPProfile.DoesNotExist:
            messages.error(request, "Two-factor authentication is not enabled.")
            return redirect('account_otp_settings')

        # Delete old backup codes
        StaticDevice.objects.filter(user=user).delete()

        # Create new static device
        device = StaticDevice.objects.create(
            user=user,
            name='backup',
            confirmed=True
        )

        # Generate 10 new backup codes
        for _ in range(10):
            token = random_hex(6).upper()
            StaticToken.objects.create(device=device, token=token)

        messages.success(request, "Backup codes have been regenerated. Please save them now.")
        return redirect('account_otp_backup_codes')


class OTPSettingsView(LoginRequiredMixin, TemplateView):
    """OTP settings overview page (linked from sidebar)"""
    template_name = 'account/otp/settings.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user

        try:
            profile = UserOTPProfile.objects.get(user=user)
            context['otp_profile'] = profile
        except UserOTPProfile.DoesNotExist:
            context['otp_profile'] = None

        # Get TOTP devices
        totp_devices = TOTPDevice.objects.filter(user=user, confirmed=True)
        context['totp_devices'] = totp_devices
        context['otp_enabled'] = totp_devices.exists()

        # Check backup codes
        try:
            device = StaticDevice.objects.get(user=user, confirmed=True)
            # Count all backup codes (they're all unused if they exist; used ones are deleted)
            unused_codes_count = device.token_set.count()
            context['backup_codes_count'] = unused_codes_count
        except StaticDevice.DoesNotExist:
            context['backup_codes_count'] = 0

        return context


class OTPLoginView(FormView):
    """OTP token input during login (after password verification)"""
    template_name = 'account/otp/login.html'
    form_class = OTPTokenForm

    def dispatch(self, request, *args, **kwargs):
        # Check if user is in pre-auth state
        if 'otp_pre_auth_user_id' not in request.session:
            messages.error(request, "Invalid OTP login session.")
            return redirect('account_login')
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Get user email for display
        try:
            user_id = self.request.session.get('otp_pre_auth_user_id')
            user = User.objects.get(id=user_id)
            context['user_email'] = user.email
        except User.DoesNotExist:
            context['user_email'] = ''
        return context

    def form_valid(self, form):
        token = form.cleaned_data['token']
        user_id = self.request.session.get('otp_pre_auth_user_id')
        backend = self.request.session.get('otp_pre_auth_backend')

        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            messages.error(self.request, "User not found.")
            return redirect('account_login')

        # Try TOTP device
        totp_devices = TOTPDevice.objects.filter(user=user, confirmed=True)
        for device in totp_devices:
            if device.verify_token(token):
                # Token valid, complete login
                user.backend = backend
                login(self.request, user)
                otp_login(self.request, device)

                # Update last used
                try:
                    profile = UserOTPProfile.objects.get(user=user)
                    profile.last_used_at = timezone.now()
                    profile.save()
                except UserOTPProfile.DoesNotExist:
                    pass

                # Clear session
                del self.request.session['otp_pre_auth_user_id']
                del self.request.session['otp_pre_auth_backend']

                messages.success(self.request, "Successfully logged in.")
                return redirect(reverse('dashboard'))

        # Try backup codes (static devices)
        try:
            static_device = StaticDevice.objects.get(user=user, confirmed=True)
            # Check if token matches any backup code
            backup_token = static_device.token_set.filter(
                token=token.upper()
            ).first()

            if backup_token:
                # Delete the used backup code (django-otp deletes used tokens)
                backup_token.delete()

                # Complete login
                user.backend = backend
                login(self.request, user)
                otp_login(self.request, static_device)

                # Update last used
                try:
                    profile = UserOTPProfile.objects.get(user=user)
                    profile.last_used_at = timezone.now()
                    profile.save()
                except UserOTPProfile.DoesNotExist:
                    pass

                # Clear session
                del self.request.session['otp_pre_auth_user_id']
                del self.request.session['otp_pre_auth_backend']

                # Warn about backup code usage
                remaining = static_device.token_set.count()
                messages.warning(
                    self.request,
                    f"You used a backup code. {remaining} backup codes remaining."
                )
                return redirect(reverse('dashboard'))
        except StaticDevice.DoesNotExist:
            pass

        # Invalid token - implement rate limiting
        return self._handle_failed_attempt(user_id, form)

    def _handle_failed_attempt(self, user_id, form):
        """Handle failed OTP attempt with rate limiting"""
        cache_key = f'otp_failed_attempts_{user_id}'

        attempts = cache.get(cache_key, 0)
        attempts += 1
        cache.set(cache_key, attempts, timeout=900)  # 15 minutes

        if attempts >= 5:
            # Lock out after 5 failed attempts
            messages.error(
                self.request,
                "Too many failed attempts. Please try again in 15 minutes or use a backup code."
            )
            del self.request.session['otp_pre_auth_user_id']
            del self.request.session['otp_pre_auth_backend']
            return redirect('account_login')

        messages.error(self.request, "Invalid verification code. Please try again.")
        return self.form_invalid(form)
