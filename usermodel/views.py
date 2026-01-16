from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse_lazy
from django.views.generic import UpdateView

from usermodel.forms import UserProfileForm


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
