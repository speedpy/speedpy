from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.template.loader import render_to_string
from django.test import TestCase

from usermodel.adapters import CustomSocialAccountAdapter
from usermodel.models import User
from usermodel.validators import validate_no_url


class ValidateNoUrlTests(TestCase):
    def test_rejects_urls_and_link_schemes(self):
        for value in [
            "http://evil.com",
            "Click https://phish.io now",
            "John www.bad.com",
            "javascript:alert(1)",
            "data:text/html;base64,xx",
            "mailto:x@y.z",
        ]:
            with self.subTest(value=value):
                with self.assertRaises(ValidationError):
                    validate_no_url(value)

    def test_allows_ordinary_names(self):
        for value in ["John Doe", "Mary-Jane", "O'Brien", "José", ""]:
            with self.subTest(value=value):
                validate_no_url(value)  # should not raise


class UserNameValidationTests(TestCase):
    def test_full_clean_rejects_url_in_name(self):
        user = User(email="a@example.com", first_name="http://evil.com")
        with self.assertRaises(ValidationError) as ctx:
            user.full_clean()
        self.assertIn("first_name", ctx.exception.message_dict)

    def test_full_clean_accepts_clean_name(self):
        user = User(email="b@example.com", first_name="Jane", last_name="Doe")
        user.set_password("x")
        user.full_clean()  # should not raise


class SocialAccountAdapterTests(TestCase):
    def test_populate_user_strips_url_names(self):
        adapter = CustomSocialAccountAdapter()

        class FakeUser:
            first_name = "Evil http://phish.io"
            last_name = "Doe"

        class FakeSocialLogin:
            user = FakeUser()

        sociallogin = FakeSocialLogin()
        with patch(
            "allauth.socialaccount.adapter.DefaultSocialAccountAdapter.populate_user",
            lambda self, request, sl, data: sl.user,
        ):
            user = adapter.populate_user(None, sociallogin, {})

        self.assertEqual(user.first_name, "")
        self.assertEqual(user.last_name, "Doe")


class EmailConfirmationMessageTests(TestCase):
    def test_confirmation_email_has_no_name_personalization(self):
        class FakeSite:
            name = "SpeedPy"
            domain = "speedpy.test"

        rendered = render_to_string(
            "account/email/email_confirmation_message.txt",
            {
                "current_site": FakeSite,
                "activate_url": "https://speedpy.test/confirm/abc",
            },
        )
        self.assertIn("your email address was used to register", rendered)
        self.assertIn("https://speedpy.test/confirm/abc", rendered)
