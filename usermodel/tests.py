from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.template.loader import render_to_string
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from usermodel.adapters import CustomSocialAccountAdapter
from usermodel.forms import (
    UsermodelLoginForm,
    UsermodelResetPasswordForm,
    UsermodelResetPasswordKeyForm,
    UsermodelSignupForm,
)
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


AUTH_FORMS = [
    UsermodelSignupForm,
    UsermodelLoginForm,
    UsermodelResetPasswordForm,
    UsermodelResetPasswordKeyForm,
]


class RecaptchaToggleTests(TestCase):
    @override_settings(RECAPTCHA_PUBLIC_KEY="", RECAPTCHA_PRIVATE_KEY="")
    def test_disabled_when_keys_missing(self):
        for form_class in AUTH_FORMS:
            with self.subTest(form=form_class.__name__):
                self.assertNotIn("captcha", form_class().fields)

    @override_settings(RECAPTCHA_PUBLIC_KEY="pub", RECAPTCHA_PRIVATE_KEY="priv")
    def test_enabled_when_keys_present(self):
        for form_class in AUTH_FORMS:
            with self.subTest(form=form_class.__name__):
                self.assertIn("captcha", form_class().fields)

    @override_settings(RECAPTCHA_PUBLIC_KEY="pub", RECAPTCHA_PRIVATE_KEY="")
    def test_disabled_when_only_one_key_present(self):
        for form_class in AUTH_FORMS:
            with self.subTest(form=form_class.__name__):
                self.assertNotIn("captcha", form_class().fields)


class CurrentUserAPITests(TestCase):
    EXPECTED_FIELDS = {
        "id",
        "email",
        "first_name",
        "last_name",
        "full_name",
        "is_email_confirmed",
        "profile_picture_url",
        "profile_picture_thumbnail_url",
        "date_joined",
    }

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            email="api@example.com",
            password="testpass123",
            first_name="Ada",
            last_name="Lovelace",
        )

    def test_anonymous_rejected(self):
        response = self.client.get("/api/v1/me/")
        self.assertEqual(response.status_code, 403)

    def test_authenticated_returns_200(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get("/api/v1/me/")
        self.assertEqual(response.status_code, 200)

    def test_response_contains_exactly_approved_fields(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get("/api/v1/me/")
        self.assertEqual(set(response.data.keys()), self.EXPECTED_FIELDS)

    def test_response_values_match_user(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get("/api/v1/me/")
        data = response.data
        self.assertEqual(data["id"], str(self.user.id))
        self.assertEqual(data["email"], self.user.email)
        self.assertEqual(data["first_name"], "Ada")
        self.assertEqual(data["last_name"], "Lovelace")
        self.assertEqual(data["full_name"], "Ada Lovelace")
        self.assertEqual(data["is_email_confirmed"], self.user.is_email_confirmed)

    def test_missing_profile_images_serialize_as_null(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get("/api/v1/me/")
        self.assertIsNone(response.data["profile_picture_url"])
        self.assertIsNone(response.data["profile_picture_thumbnail_url"])


class APISchemaTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    @override_settings(API_DOCS_PUBLIC=True)
    def test_schema_returns_success(self):
        response = self.client.get("/api/schema/")
        self.assertEqual(response.status_code, 200)

    @override_settings(API_DOCS_PUBLIC=True)
    def test_schema_includes_get_current_user(self):
        response = self.client.get("/api/schema/")
        self.assertIn("getCurrentUser", str(response.content))

    @override_settings(API_DOCS_PUBLIC=True)
    def test_docs_render(self):
        response = self.client.get("/api/docs/")
        self.assertEqual(response.status_code, 200)

    @override_settings(API_DOCS_PUBLIC=True)
    def test_redoc_render(self):
        response = self.client.get("/api/redoc/")
        self.assertEqual(response.status_code, 200)

    @override_settings(API_DOCS_PUBLIC=False)
    def test_schema_requires_staff_when_not_public(self):
        response = self.client.get("/api/schema/")
        self.assertIn(response.status_code, [302, 403])

    @override_settings(API_DOCS_PUBLIC=False)
    def test_docs_require_staff_when_not_public(self):
        response = self.client.get("/api/docs/")
        self.assertIn(response.status_code, [302, 403])

    @override_settings(API_DOCS_PUBLIC=False)
    def test_redoc_requires_staff_when_not_public(self):
        response = self.client.get("/api/redoc/")
        self.assertIn(response.status_code, [302, 403])

    @override_settings(API_DOCS_PUBLIC=False)
    def test_staff_can_access_schema(self):
        staff = User.objects.create_user(
            email="staff@example.com",
            password="staffpass123",
            is_staff=True,
        )
        self.client.login(email="staff@example.com", password="staffpass123")
        response = self.client.get("/api/schema/")
        self.assertEqual(response.status_code, 200)
