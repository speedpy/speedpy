from datetime import timedelta
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.template.loader import render_to_string
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from usermodel.adapters import CustomSocialAccountAdapter
from usermodel.forms import (
    UsermodelLoginForm,
    UsermodelResetPasswordForm,
    UsermodelResetPasswordKeyForm,
    UsermodelSignupForm,
)
from usermodel.models import PersonalAccessToken, User, _hash_token
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
        self.assertIn(response.status_code, [401, 403])

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

    def test_profile_image_urls_are_absolute(self):
        import io

        from PIL import Image

        img = Image.new("RGB", (100, 100), color="red")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        self.user.profile_picture.save("test.png", buf, save=True)
        self.user.refresh_from_db()

        self.client.force_authenticate(user=self.user)
        response = self.client.get("/api/v1/me/")
        self.assertTrue(
            response.data["profile_picture_url"].startswith("http"),
            "profile_picture_url should be an absolute URL",
        )
        if self.user.profile_picture_thumbnail:
            self.assertTrue(
                response.data["profile_picture_thumbnail_url"].startswith("http"),
                "profile_picture_thumbnail_url should be an absolute URL",
            )

        # Clean up uploaded file
        self.user.profile_picture.delete(save=False)
        if self.user.profile_picture_thumbnail:
            self.user.profile_picture_thumbnail.delete(save=False)


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

    @override_settings(API_DOCS_PUBLIC=True)
    def test_schema_includes_update_current_user(self):
        response = self.client.get("/api/schema/")
        self.assertIn("updateCurrentUser", str(response.content))

    @override_settings(API_DOCS_PUBLIC=True)
    def test_schema_includes_product_operations(self):
        response = self.client.get("/api/schema/")
        content = str(response.content)
        self.assertIn("listProducts", content)
        self.assertIn("getProduct", content)


class UpdateProfileAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            email="patch@example.com",
            password="testpass123",
            first_name="Ada",
            last_name="Lovelace",
        )

    def test_anonymous_rejected(self):
        response = self.client.patch(
            "/api/v1/me/",
            {"first_name": "Grace"},
            format="json",
        )
        self.assertIn(response.status_code, [401, 403])

    def test_patch_updates_first_name(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.patch(
            "/api/v1/me/",
            {"first_name": "Grace"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["first_name"], "Grace")
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, "Grace")

    def test_patch_updates_last_name(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.patch(
            "/api/v1/me/",
            {"last_name": "Hopper"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["last_name"], "Hopper")
        self.user.refresh_from_db()
        self.assertEqual(self.user.last_name, "Hopper")

    def test_patch_returns_full_user_response(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.patch(
            "/api/v1/me/",
            {"first_name": "Grace"},
            format="json",
        )
        self.assertEqual(
            set(response.data.keys()),
            CurrentUserAPITests.EXPECTED_FIELDS,
        )

    def test_email_not_writable(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.patch(
            "/api/v1/me/",
            {"email": "hacked@example.com"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "patch@example.com")

    def test_rejects_url_in_first_name(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.patch(
            "/api/v1/me/",
            {"first_name": "http://evil.com"},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("first_name", response.data)

    def test_rejects_url_in_last_name(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.patch(
            "/api/v1/me/",
            {"last_name": "https://phish.io"},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("last_name", response.data)

    def test_empty_patch_succeeds(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.patch(
            "/api/v1/me/",
            {},
            format="json",
        )
        self.assertEqual(response.status_code, 200)

    def test_patch_multiple_fields(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.patch(
            "/api/v1/me/",
            {"first_name": "Grace", "last_name": "Hopper"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["first_name"], "Grace")
        self.assertEqual(response.data["last_name"], "Hopper")
        self.assertEqual(response.data["full_name"], "Grace Hopper")

    def test_patch_with_session_auth_and_csrf(self):
        """PATCH via session login requires CSRF token (DRF SessionAuthentication)."""
        from django.test import Client

        session_client = Client(enforce_csrf_checks=True)
        session_client.login(email="patch@example.com", password="testpass123")

        # Without CSRF token, should be rejected
        response = session_client.patch(
            "/api/v1/me/",
            data='{"first_name": "Grace"}',
            content_type="application/json",
        )
        self.assertIn(response.status_code, [401, 403])

        # With CSRF token, should succeed
        response = session_client.get("/api/v1/me/")
        csrf_token = response.cookies.get("csrftoken")
        if csrf_token:
            response = session_client.patch(
                "/api/v1/me/",
                data='{"first_name": "Grace"}',
                content_type="application/json",
                headers={"X-CSRFToken": csrf_token.value},
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["first_name"], "Grace")

    def test_patch_profile_picture_upload(self):
        """PATCH can upload a profile picture via multipart."""
        import io

        from PIL import Image

        self.client.force_authenticate(user=self.user)

        img = Image.new("RGB", (100, 100), color="blue")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.name = "avatar.png"
        buf.seek(0)

        response = self.client.patch(
            "/api/v1/me/",
            {"profile_picture": buf},
            format="multipart",
        )
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.profile_picture)
        self.assertIsNotNone(response.data["profile_picture_url"])

        # Clean up
        self.user.profile_picture.delete(save=False)
        if self.user.profile_picture_thumbnail:
            self.user.profile_picture_thumbnail.delete(save=False)

    def test_patch_clear_profile_picture(self):
        """PATCH with profile_picture=null clears the image."""
        self.client.force_authenticate(user=self.user)
        response = self.client.patch(
            "/api/v1/me/",
            {"profile_picture": None},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertFalse(self.user.profile_picture)


class ProductAPITests(TestCase):
    def setUp(self):
        from demoapp.models import Product

        self.client = APIClient()
        self.user = User.objects.create_user(
            email="prodapi@example.com",
            password="testpass123",
        )
        self.product = Product.objects.create(
            name="Test Widget",
            sku="TST-001",
            category="software",
            status="active",
            price="29.99",
            inventory=100,
            description="A test product.",
        )

    def test_anonymous_rejected_list(self):
        response = self.client.get("/api/v1/products/")
        self.assertIn(response.status_code, [401, 403])

    def test_anonymous_rejected_detail(self):
        response = self.client.get(f"/api/v1/products/{self.product.pk}/")
        self.assertIn(response.status_code, [401, 403])

    def test_list_returns_200(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get("/api/v1/products/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(len(response.data["results"]), 1)

    def test_list_pagination_keys(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get("/api/v1/products/")
        self.assertEqual(
            set(response.data.keys()),
            {"count", "next", "previous", "results"},
        )

    def test_detail_returns_200(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get(f"/api/v1/products/{self.product.pk}/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["name"], "Test Widget")
        self.assertEqual(response.data["sku"], "TST-001")

    def test_detail_field_contract(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get(f"/api/v1/products/{self.product.pk}/")
        expected = {
            "id", "name", "sku", "category", "status",
            "price", "inventory", "description",
            "created_at", "updated_at",
        }
        self.assertEqual(set(response.data.keys()), expected)

    def test_detail_404_for_nonexistent(self):
        import uuid

        self.client.force_authenticate(user=self.user)
        response = self.client.get(f"/api/v1/products/{uuid.uuid4()}/")
        self.assertEqual(response.status_code, 404)


class PersonalAccessTokenModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="pat@example.com", password="testpass123"
        )

    def test_create_token_returns_instance_and_raw(self):
        pat, raw_token = PersonalAccessToken.create_token(
            user=self.user, name="Test token"
        )
        self.assertIsNotNone(pat.id)
        self.assertTrue(raw_token.startswith("spd_"))
        self.assertEqual(pat.name, "Test token")

    def test_token_stored_as_hash(self):
        pat, raw_token = PersonalAccessToken.create_token(
            user=self.user, name="Hashed"
        )
        self.assertNotEqual(pat.token_hash, raw_token)
        self.assertEqual(pat.token_hash, _hash_token(raw_token))
        self.assertEqual(len(pat.token_hash), 64)  # SHA-256 hex

    def test_authenticate_valid_token(self):
        pat, raw_token = PersonalAccessToken.create_token(
            user=self.user, name="Auth test"
        )
        found = PersonalAccessToken.authenticate(raw_token)
        self.assertIsNotNone(found)
        self.assertEqual(found.id, pat.id)

    def test_authenticate_invalid_token(self):
        found = PersonalAccessToken.authenticate("spd_invalid_token_value")
        self.assertIsNone(found)

    def test_authenticate_revoked_token(self):
        pat, raw_token = PersonalAccessToken.create_token(
            user=self.user, name="Revokable"
        )
        pat.revoke()
        found = PersonalAccessToken.authenticate(raw_token)
        self.assertIsNone(found)

    def test_revocation_is_immediate(self):
        pat, _ = PersonalAccessToken.create_token(
            user=self.user, name="Revoke me"
        )
        self.assertFalse(pat.is_revoked)
        pat.revoke()
        pat.refresh_from_db()
        self.assertTrue(pat.is_revoked)

    def test_authenticate_expired_token(self):
        pat, raw_token = PersonalAccessToken.create_token(
            user=self.user,
            name="Expired",
            expires_at=timezone.now() - timedelta(hours=1),
        )
        found = PersonalAccessToken.authenticate(raw_token)
        self.assertIsNone(found)

    def test_authenticate_not_yet_expired(self):
        pat, raw_token = PersonalAccessToken.create_token(
            user=self.user,
            name="Future",
            expires_at=timezone.now() + timedelta(days=30),
        )
        found = PersonalAccessToken.authenticate(raw_token)
        self.assertIsNotNone(found)

    def test_record_usage_updates_last_used_at(self):
        pat, _ = PersonalAccessToken.create_token(
            user=self.user, name="Usage test"
        )
        self.assertIsNone(pat.last_used_at)
        pat.record_usage()
        pat.refresh_from_db()
        self.assertIsNotNone(pat.last_used_at)

    def test_scopes_stored(self):
        pat, _ = PersonalAccessToken.create_token(
            user=self.user,
            name="Scoped",
            scopes=["read:profile", "read:teams"],
        )
        pat.refresh_from_db()
        self.assertEqual(pat.scopes, ["read:profile", "read:teams"])


class PersonalAccessTokenAuthTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            email="bearer@example.com", password="testpass123"
        )
        self.pat, self.raw_token = PersonalAccessToken.create_token(
            user=self.user, name="Bearer test"
        )

    def test_bearer_auth_succeeds(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.raw_token}")
        response = self.client.get("/api/v1/me/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["email"], "bearer@example.com")

    def test_bearer_auth_updates_last_used(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.raw_token}")
        self.client.get("/api/v1/me/")
        self.pat.refresh_from_db()
        self.assertIsNotNone(self.pat.last_used_at)

    def test_invalid_bearer_token_rejected(self):
        self.client.credentials(HTTP_AUTHORIZATION="Bearer spd_invalid")
        response = self.client.get("/api/v1/me/")
        self.assertEqual(response.status_code, 401)

    def test_revoked_token_rejected(self):
        self.pat.revoke()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.raw_token}")
        response = self.client.get("/api/v1/me/")
        self.assertEqual(response.status_code, 401)

    def test_expired_token_rejected(self):
        self.pat.expires_at = timezone.now() - timedelta(hours=1)
        self.pat.save(update_fields=["expires_at"])
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.raw_token}")
        response = self.client.get("/api/v1/me/")
        self.assertEqual(response.status_code, 401)

    def test_inactive_user_rejected(self):
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.raw_token}")
        response = self.client.get("/api/v1/me/")
        self.assertEqual(response.status_code, 401)

    def test_no_auth_header_falls_through(self):
        response = self.client.get("/api/v1/me/")
        self.assertIn(response.status_code, [401, 403])

    def test_scoped_token_allowed_for_matching_scope(self):
        pat, raw = PersonalAccessToken.create_token(
            user=self.user, name="Scoped read", scopes=["read:products"]
        )
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")
        response = self.client.get("/api/v1/products/")
        self.assertEqual(response.status_code, 200)

    def test_scoped_token_denied_for_wrong_scope(self):
        pat, raw = PersonalAccessToken.create_token(
            user=self.user, name="Wrong scope", scopes=["read:teams"]
        )
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")
        response = self.client.get("/api/v1/products/")
        self.assertIn(response.status_code, [401, 403])

    def test_empty_scopes_grants_full_access(self):
        pat, raw = PersonalAccessToken.create_token(
            user=self.user, name="Full access", scopes=[]
        )
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")
        response = self.client.get("/api/v1/products/")
        self.assertEqual(response.status_code, 200)


class PersonalAccessTokenUITests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="uitest@example.com", password="testpass123"
        )
        self.client.login(email="uitest@example.com", password="testpass123")

    def test_list_page_loads(self):
        response = self.client.get("/accounts/tokens/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "API Tokens")

    def test_create_page_loads(self):
        response = self.client.get("/accounts/tokens/create/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Create API Token")

    def test_create_token_flow(self):
        response = self.client.post(
            "/accounts/tokens/create/",
            {"name": "My CI Token"},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "spd_")
        self.assertEqual(PersonalAccessToken.objects.filter(user=self.user).count(), 1)

    def test_one_time_reveal(self):
        # Create a token
        self.client.post("/accounts/tokens/create/", {"name": "Once"}, follow=False)
        # First visit shows the token
        response = self.client.get("/accounts/tokens/")
        self.assertContains(response, "spd_")
        # Second visit should NOT show the token
        response = self.client.get("/accounts/tokens/")
        self.assertNotContains(response, "spd_")

    def test_revoke_token(self):
        pat, _ = PersonalAccessToken.create_token(user=self.user, name="Revoke UI")
        response = self.client.post(
            f"/accounts/tokens/{pat.pk}/revoke/", follow=True
        )
        self.assertEqual(response.status_code, 200)
        pat.refresh_from_db()
        self.assertTrue(pat.is_revoked)

    def test_anonymous_cannot_access_tokens(self):
        self.client.logout()
        response = self.client.get("/accounts/tokens/")
        self.assertEqual(response.status_code, 302)

    def test_list_shows_token_status(self):
        PersonalAccessToken.create_token(user=self.user, name="Active one")
        pat2, _ = PersonalAccessToken.create_token(user=self.user, name="Revoked one")
        pat2.revoke()
        # Clear session so no raw token is shown
        self.client.get("/accounts/tokens/")
        response = self.client.get("/accounts/tokens/")
        self.assertContains(response, "Active")
        self.assertContains(response, "Revoked")


class JWTAuthTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            email="jwt@example.com", password="jwtpass123"
        )

    def test_obtain_token_pair(self):
        response = self.client.post(
            "/api/auth/token/",
            {"email": "jwt@example.com", "password": "jwtpass123"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("access", response.data)
        self.assertIn("refresh", response.data)

    def test_obtain_token_invalid_credentials(self):
        response = self.client.post(
            "/api/auth/token/",
            {"email": "jwt@example.com", "password": "wrong"},
            format="json",
        )
        self.assertEqual(response.status_code, 401)

    def test_access_token_authenticates(self):
        response = self.client.post(
            "/api/auth/token/",
            {"email": "jwt@example.com", "password": "jwtpass123"},
            format="json",
        )
        access = response.data["access"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
        response = self.client.get("/api/v1/me/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["email"], "jwt@example.com")

    def test_refresh_token_rotates(self):
        response = self.client.post(
            "/api/auth/token/",
            {"email": "jwt@example.com", "password": "jwtpass123"},
            format="json",
        )
        refresh = response.data["refresh"]
        response = self.client.post(
            "/api/auth/token/refresh/",
            {"refresh": refresh},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("access", response.data)
        self.assertIn("refresh", response.data)
        # Old refresh should now be blacklisted
        self.assertNotEqual(response.data["refresh"], refresh)

    def test_blacklisted_refresh_rejected(self):
        response = self.client.post(
            "/api/auth/token/",
            {"email": "jwt@example.com", "password": "jwtpass123"},
            format="json",
        )
        refresh = response.data["refresh"]
        # Rotate: this blacklists the old token
        self.client.post(
            "/api/auth/token/refresh/",
            {"refresh": refresh},
            format="json",
        )
        # Old refresh should be rejected
        response = self.client.post(
            "/api/auth/token/refresh/",
            {"refresh": refresh},
            format="json",
        )
        self.assertEqual(response.status_code, 401)

    def test_revoke_refresh_token(self):
        response = self.client.post(
            "/api/auth/token/",
            {"email": "jwt@example.com", "password": "jwtpass123"},
            format="json",
        )
        refresh = response.data["refresh"]
        response = self.client.post(
            "/api/auth/token/revoke/",
            {"refresh": refresh},
            format="json",
        )
        self.assertEqual(response.status_code, 205)
        # Revoked token should no longer refresh
        response = self.client.post(
            "/api/auth/token/refresh/",
            {"refresh": refresh},
            format="json",
        )
        self.assertEqual(response.status_code, 401)

    def test_revoke_invalid_token(self):
        response = self.client.post(
            "/api/auth/token/revoke/",
            {"refresh": "invalid.token.value"},
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_expired_access_token_rejected(self):
        """Access tokens with past expiry should be rejected."""
        from rest_framework_simplejwt.tokens import AccessToken

        token = AccessToken.for_user(self.user)
        token.set_exp(lifetime=timedelta(seconds=-1))
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {str(token)}")
        response = self.client.get("/api/v1/me/")
        self.assertEqual(response.status_code, 401)

    @override_settings(API_DOCS_PUBLIC=True)
    def test_schema_includes_jwt_operations(self):
        response = self.client.get("/api/schema/")
        content = str(response.content)
        self.assertIn("createToken", content)
        self.assertIn("refreshToken", content)
        self.assertIn("revokeToken", content)
