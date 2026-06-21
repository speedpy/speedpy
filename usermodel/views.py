import base64
import hashlib

import structlog
from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.utils import timezone
from django.views.generic import FormView, ListView, UpdateView, View

from usermodel.forms import PersonalAccessTokenForm, UserProfileForm
from usermodel.models import PersonalAccessToken

logger = structlog.get_logger(__name__)


def _get_fernet():
    """Derive a Fernet key from Django's SECRET_KEY."""
    key = hashlib.sha256(settings.SECRET_KEY.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def _encrypt_token(raw_token):
    return _get_fernet().encrypt(raw_token.encode()).decode()


def _decrypt_token(encrypted):
    try:
        return _get_fernet().decrypt(encrypted.encode()).decode()
    except InvalidToken:
        return None


class ProfileEditView(LoginRequiredMixin, UpdateView):
    """View for editing user profile information."""

    form_class = UserProfileForm
    template_name = 'account/profile/edit.html'
    success_url = reverse_lazy('account_profile')

    def get_object(self):
        return self.request.user

    def form_valid(self, form):
        messages.success(self.request, 'Your profile has been updated.')
        return super().form_valid(form)


class PersonalAccessTokenListView(LoginRequiredMixin, ListView):
    """List and manage personal access tokens."""

    template_name = "account/pat/list.html"
    context_object_name = "tokens"

    def get_queryset(self):
        return PersonalAccessToken.objects.filter(user=self.request.user)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        encrypted_token = self.request.session.pop("new_pat_encrypted_token", None)
        context["new_token_name"] = self.request.session.pop("new_pat_name", None)
        context["new_token"] = _decrypt_token(encrypted_token) if encrypted_token else None
        context["now"] = timezone.now()
        return context


class PersonalAccessTokenCreateView(LoginRequiredMixin, FormView):
    """Create a new personal access token."""

    template_name = "account/pat/create.html"
    form_class = PersonalAccessTokenForm
    success_url = reverse_lazy("account_pat_list")

    def form_valid(self, form):
        pat, raw_token = PersonalAccessToken.create_token(
            user=self.request.user,
            name=form.cleaned_data["name"],
            scopes=form.cleaned_data.get("scopes", []),
            expires_at=form.cleaned_data.get("expires_at"),
        )
        logger.info(
            "pat_created",
            user_id=str(self.request.user.id),
            token_id=str(pat.id),
            token_name=pat.name,
        )
        self.request.session["new_pat_encrypted_token"] = _encrypt_token(raw_token)
        self.request.session["new_pat_name"] = pat.name
        messages.success(self.request, f'Token "{pat.name}" created. Copy it now — it won\'t be shown again.')
        return redirect(self.success_url)


class PersonalAccessTokenRevokeView(LoginRequiredMixin, View):
    """Revoke a personal access token."""

    def post(self, request, pk):
        pat = get_object_or_404(
            PersonalAccessToken, pk=pk, user=request.user
        )
        pat.revoke()
        logger.info(
            "pat_revoked",
            user_id=str(request.user.id),
            token_id=str(pat.id),
            token_name=pat.name,
        )
        messages.success(request, f'Token "{pat.name}" has been revoked.')
        return redirect("account_pat_list")
