from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils.crypto import get_random_string
from django.conf import settings
from allauth.account.models import EmailAddress
import os


User = get_user_model()


class Command(BaseCommand):
    def handle(self, *args, **kwargs):
        email = 'admin@example.com'
        new_password = settings.DEFAULT_ADMIN_PASSWORD
        if not new_password:
            new_password = get_random_string(10)
        try:
            if not User.objects.filter(is_superuser=True).exists():
                self.stdout.write("No superusers found, creating one")
                u = User.objects.create_superuser(email=email, password=new_password, first_name="Admin", last_name="User")
                self.stdout.write("=======================")
                self.stdout.write("A superuser has been created")
                self.stdout.write(f"Email: {email}")
                self.stdout.write(f"Password: {new_password}")
                self.stdout.write("=======================")
                EmailAddress.objects.create(
                    user=u,
                    email=email,
                    primary=True,
                    verified=True
                )
            else:
                self.stdout.write("A superuser exists in the database. Skipping.")
        except Exception as e:
            self.stderr.write(f"There was an error {e}")
