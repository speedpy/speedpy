"""The CIMD public downgrade for one-click MCP connectors.

Some directory clients declare a confidential ``token_endpoint_auth_method``
(ChatGPT: ``private_key_jwt``) or an extra grant type (Claude: ``jwt-bearer``)
that DOT's stock CIMD path rejects, 400ing the authorize step.
:class:`SpeedPyOAuth2Validator` makes one deliberate, **allowlisted** exception:
it resolves that document as a public PKCE client instead.

Each test guards one edge of that exception. The behaviour is off unless the
client_id is on ``MCP_CIMD_PUBLIC_DOWNGRADE_CLIENT_IDS`` and CIMD is enabled, so
these tests turn both on explicitly.
"""

import contextlib
from datetime import timedelta
from unittest import mock

from django.conf import settings as dj_settings
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone
from oauth2_provider import cimd
from oauth2_provider.cimd import CIMDError
from oauth2_provider.models import get_application_model
from oauthlib.common import Request

from speedpycom.api.oauth_validator import (
    _GRANT_TYPE_MAP,
    SpeedPyOAuth2Validator,
    build_public_downgrade_kwargs,
)

Application = get_application_model()

CHATGPT_CLIENT_ID = "https://chatgpt.com/oauth/client.json"
OTHER_CLIENT_ID = "https://other.test/oauth/client.json"
CHATGPT_REDIRECT = "https://chatgpt.com/connector_platform_oauth_redirect"

# ChatGPT's real-shaped document: a self-asserted confidential client.
CHATGPT_DOC = {
    "client_id": CHATGPT_CLIENT_ID,
    "client_name": "ChatGPT",
    "token_endpoint_auth_method": "private_key_jwt",
    "token_endpoint_auth_methods_supported": ["none", "private_key_jwt"],
    "grant_types": ["authorization_code", "refresh_token"],
    "redirect_uris": [CHATGPT_REDIRECT],
}

CLAUDE_CLIENT_ID = "https://claude.ai/oauth/mcp-oauth-client-metadata"
CLAUDE_REDIRECT = "https://claude.ai/api/mcp/auth_callback"

# Claude's real document: a public (`none`) client, but with an extra grant type
# (`jwt-bearer`) that makes DOT's stock CIMD resolver reject the whole document.
CLAUDE_DOC = {
    "client_id": CLAUDE_CLIENT_ID,
    "client_name": "Claude",
    "client_uri": "https://claude.ai",
    "redirect_uris": [CLAUDE_REDIRECT],
    "grant_types": [
        "authorization_code",
        "refresh_token",
        "urn:ietf:params:oauth:grant-type:jwt-bearer",
    ],
    "response_types": ["code"],
    "token_endpoint_auth_method": "none",
}

# CIMD is off by default in the boilerplate; the downgrade tests turn it on and
# allowlist both directory clients.
_CIMD_ON = {**dj_settings.OAUTH2_PROVIDER, "CIMD_ENABLED": True}
_ALLOWLIST = [CHATGPT_CLIENT_ID, CLAUDE_CLIENT_ID]


def _doc(client_id, **overrides):
    doc = dict(CHATGPT_DOC, client_id=client_id)
    doc.update(overrides)
    return doc


class FakeFetcher:
    """Stand-in for ``CIMD_METADATA_FETCHER`` returning a canned document.

    ``fetch`` mirrors ``SafeMetadataFetcher.fetch``'s contract: it returns
    ``(metadata_dict, max_age_seconds)`` keyed on the requested client_id, or
    raises :class:`CIMDError` for an unknown URL.
    """

    documents = {}
    max_age = 3600

    def fetch(self, client_id):
        try:
            return self.documents[client_id], self.max_age
        except KeyError as exc:
            raise CIMDError(f"no document for {client_id!r}") from exc


def _patch_fetcher(fetcher):
    """Patch ``oauth2_settings.CIMD_METADATA_FETCHER`` without desyncing it.

    Accessing the attribute first materialises it in the settings object's
    ``__dict__``; otherwise ``mock`` restores by ``delattr`` on teardown and the
    next ``override_settings`` reload raises.
    """
    from oauth2_provider.settings import oauth2_settings

    _ = oauth2_settings.CIMD_METADATA_FETCHER
    return mock.patch.object(oauth2_settings, "CIMD_METADATA_FETCHER", fetcher)


def _with_fetcher(documents):
    fetcher = type("_Fetcher", (FakeFetcher,), {"documents": documents})
    return _patch_fetcher(fetcher)


def _token_request(client_id, body=""):
    request = Request("https://testserver/o/token/", http_method="POST", body=body)
    request.client_id = client_id
    return request


class BuildPublicDowngradeKwargsTests(TestCase):
    """The field validation, in isolation — the downgrade is narrow on purpose."""

    def test_a_private_key_jwt_document_becomes_public_kwargs(self):
        kwargs = build_public_downgrade_kwargs(CHATGPT_DOC)
        self.assertEqual(kwargs["name"], "ChatGPT")
        self.assertEqual(kwargs["redirect_uris"], CHATGPT_REDIRECT)
        self.assertEqual(kwargs["authorization_grant_type"], Application.GRANT_AUTHORIZATION_CODE)

    def test_a_real_shared_secret_is_still_refused(self):
        with self.assertRaises(CIMDError):
            build_public_downgrade_kwargs(_doc(CHATGPT_CLIENT_ID, client_secret="s3cret"))
        with self.assertRaises(CIMDError):
            build_public_downgrade_kwargs(_doc(CHATGPT_CLIENT_ID, client_secret_expires_at=0))

    def test_redirect_uris_are_still_required(self):
        for bad in ([], "not-a-list", [123]):
            with self.subTest(redirect_uris=bad):
                with self.assertRaises(CIMDError):
                    build_public_downgrade_kwargs(_doc(CHATGPT_CLIENT_ID, redirect_uris=bad))

    def test_extra_grant_types_are_tolerated_by_selecting_authorization_code(self):
        for extra in (
            ["authorization_code", "implicit"],
            ["authorization_code", "refresh_token", "urn:ietf:params:oauth:grant-type:jwt-bearer"],
            ["urn:ietf:params:oauth:grant-type:jwt-bearer", "authorization_code"],
        ):
            with self.subTest(grant_types=extra):
                kwargs = build_public_downgrade_kwargs(_doc(CHATGPT_CLIENT_ID, grant_types=extra))
                self.assertEqual(
                    kwargs["authorization_grant_type"], Application.GRANT_AUTHORIZATION_CODE
                )

    def test_a_document_with_no_supported_grant_is_still_refused(self):
        for grants in (
            ["refresh_token"],
            ["urn:ietf:params:oauth:grant-type:jwt-bearer"],
            ["urn:ietf:params:oauth:grant-type:jwt-bearer", "refresh_token"],
        ):
            with self.subTest(grant_types=grants):
                with self.assertRaises(CIMDError):
                    build_public_downgrade_kwargs(_doc(CHATGPT_CLIENT_ID, grant_types=grants))

    def test_grant_type_map_matches_dot(self):
        # Our local copy of the grant-type map must equal DOT's. A DOT upgrade
        # that adds, removes, or re-points an entry (e.g. changes the ``implicit``
        # mapping) is caught here rather than in production.
        self.assertEqual(_GRANT_TYPE_MAP, cimd.GRANT_TYPE_MAP)

    def test_parity_with_dot_field_validation_for_none_documents(self):
        # The one difference from DOT is the auth-method check. For a plain
        # ``none`` document that DOT itself accepts (a single meaningful grant),
        # every field must resolve identically — including each grant in the map,
        # so a change to DOT's shared validation or resolution is caught.
        for grants in (
            None,  # omitted -> defaults to authorization_code
            ["authorization_code"],
            ["authorization_code", "refresh_token"],
            ["implicit"],
        ):
            with self.subTest(grant_types=grants):
                doc = _doc(CHATGPT_CLIENT_ID, token_endpoint_auth_method="none")
                if grants is None:
                    doc.pop("grant_types", None)
                else:
                    doc["grant_types"] = grants
                self.assertEqual(
                    build_public_downgrade_kwargs(doc),
                    cimd._build_application_kwargs(doc),
                )

    def test_shared_field_rejections_match_dot(self):
        # For the field checks we share with DOT (secret presence, bad
        # redirect_uris), both must reject the same documents.
        for bad in (
            _doc(CHATGPT_CLIENT_ID, token_endpoint_auth_method="none", client_secret="s"),
            _doc(CHATGPT_CLIENT_ID, token_endpoint_auth_method="none", redirect_uris=[]),
            _doc(CHATGPT_CLIENT_ID, token_endpoint_auth_method="none", redirect_uris="nope"),
        ):
            with self.subTest(doc=bad):
                with self.assertRaises(CIMDError):
                    build_public_downgrade_kwargs(bad)
                with self.assertRaises(CIMDError):
                    cimd._build_application_kwargs(bad)


@override_settings(MCP_CIMD_PUBLIC_DOWNGRADE_CLIENT_IDS=_ALLOWLIST, OAUTH2_PROVIDER=_CIMD_ON)
class LoadApplicationTests(TestCase):
    """The resolver seam, driven through ``_load_application``."""

    def setUp(self):
        cache.clear()
        self.validator = SpeedPyOAuth2Validator()

    def test_allowlisted_private_key_jwt_document_resolves_as_public(self):
        with _with_fetcher({CHATGPT_CLIENT_ID: CHATGPT_DOC}):
            request = _token_request(CHATGPT_CLIENT_ID)
            app = self.validator._load_application(CHATGPT_CLIENT_ID, request)
        self.assertIsNotNone(app)
        self.assertEqual(app.client_type, Application.CLIENT_PUBLIC)
        self.assertEqual(app.registration_source, Application.RegistrationSource.CIMD)
        self.assertEqual(app.authorization_grant_type, Application.GRANT_AUTHORIZATION_CODE)
        self.assertEqual(app.redirect_uris, CHATGPT_REDIRECT)
        self.assertIsNone(app.user)
        self.assertIs(request.client, app)

    def test_claudes_multi_grant_document_resolves_as_public(self):
        with _with_fetcher({CLAUDE_CLIENT_ID: CLAUDE_DOC}):
            request = _token_request(CLAUDE_CLIENT_ID)
            app = self.validator._load_application(CLAUDE_CLIENT_ID, request)
        self.assertIsNotNone(app)
        self.assertEqual(app.client_type, Application.CLIENT_PUBLIC)
        self.assertEqual(app.authorization_grant_type, Application.GRANT_AUTHORIZATION_CODE)
        self.assertEqual(app.redirect_uris, CLAUDE_REDIRECT)

    def test_a_stored_public_row_is_reused_without_a_second_fetch(self):
        with _with_fetcher({CHATGPT_CLIENT_ID: CHATGPT_DOC}):
            self.validator._load_application(CHATGPT_CLIENT_ID, _token_request(CHATGPT_CLIENT_ID))
        self.assertEqual(Application.objects.filter(client_id=CHATGPT_CLIENT_ID).count(), 1)
        # An empty fetcher would raise if a second fetch were attempted.
        with _with_fetcher({}):
            app = self.validator._load_application(CHATGPT_CLIENT_ID, _token_request(CHATGPT_CLIENT_ID))
        self.assertIsNotNone(app)
        self.assertEqual(app.client_type, Application.CLIENT_PUBLIC)

    def test_a_non_allowlisted_private_key_jwt_document_is_still_rejected(self):
        with _with_fetcher({OTHER_CLIENT_ID: _doc(OTHER_CLIENT_ID)}):
            app = self.validator._load_application(OTHER_CLIENT_ID, _token_request(OTHER_CLIENT_ID))
        self.assertIsNone(app)
        self.assertFalse(Application.objects.filter(client_id=OTHER_CLIENT_ID).exists())

    def test_an_empty_allowlist_restores_stock_behaviour(self):
        with override_settings(MCP_CIMD_PUBLIC_DOWNGRADE_CLIENT_IDS=[]):
            with _with_fetcher({CHATGPT_CLIENT_ID: CHATGPT_DOC}):
                app = self.validator._load_application(
                    CHATGPT_CLIENT_ID, _token_request(CHATGPT_CLIENT_ID)
                )
        self.assertIsNone(app)
        self.assertFalse(Application.objects.filter(client_id=CHATGPT_CLIENT_ID).exists())

    def test_a_plain_none_document_is_resolved_by_stock_unchanged(self):
        none_doc = _doc(OTHER_CLIENT_ID, token_endpoint_auth_method="none")
        with _with_fetcher({OTHER_CLIENT_ID: none_doc}):
            app = self.validator._load_application(OTHER_CLIENT_ID, _token_request(OTHER_CLIENT_ID))
        self.assertIsNotNone(app)
        self.assertEqual(app.client_type, Application.CLIENT_PUBLIC)
        self.assertEqual(app.registration_source, Application.RegistrationSource.CIMD)

    def test_an_unexpected_fetcher_error_fails_closed(self):
        class ExplodingFetcher:
            def fetch(self, client_id):
                raise RuntimeError("boom")

        with _patch_fetcher(ExplodingFetcher):
            app = self.validator._load_application(
                CHATGPT_CLIENT_ID, _token_request(CHATGPT_CLIENT_ID)
            )
        self.assertIsNone(app)
        self.assertFalse(Application.objects.filter(client_id=CHATGPT_CLIENT_ID).exists())

    @override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})
    def test_a_failed_downgrade_backs_off_and_skips_the_next_fetch(self):
        cache.clear()
        calls = {"n": 0}

        class CountingFetcher:
            def fetch(self, client_id):
                calls["n"] += 1
                raise CIMDError("remote down")

        with _patch_fetcher(CountingFetcher):
            self.assertIsNone(
                self.validator._load_application(CHATGPT_CLIENT_ID, _token_request(CHATGPT_CLIENT_ID))
            )
            self.assertIsNone(
                self.validator._load_application(CHATGPT_CLIENT_ID, _token_request(CHATGPT_CLIENT_ID))
            )
        self.assertEqual(calls["n"], 1, "second request should be short-circuited by the backoff")

    def test_the_in_flight_cap_refuses_a_fetch_without_backing_off(self):
        import speedpycom.api.oauth_validator as validator_mod

        @contextlib.contextmanager
        def _full_slot():
            yield False  # cap reached

        calls = {"n": 0}

        class CountingFetcher:
            def fetch(self, client_id):
                calls["n"] += 1
                return CHATGPT_DOC, 3600

        with mock.patch.object(validator_mod, "_downgrade_fetch_slot", _full_slot):
            with _patch_fetcher(CountingFetcher):
                app = self.validator._load_application(
                    CHATGPT_CLIENT_ID, _token_request(CHATGPT_CLIENT_ID)
                )
        self.assertIsNone(app)
        self.assertEqual(calls["n"], 0, "no fetch while over capacity")
        self.assertFalse(Application.objects.filter(client_id=CHATGPT_CLIENT_ID).exists())

    def test_a_manual_client_owning_the_url_is_never_taken_over(self):
        manual = Application.objects.create(
            client_id=CHATGPT_CLIENT_ID,
            client_type=Application.CLIENT_CONFIDENTIAL,
            authorization_grant_type=Application.GRANT_AUTHORIZATION_CODE,
            redirect_uris=CHATGPT_REDIRECT,
            registration_source=Application.RegistrationSource.MANUAL,
        )
        with _with_fetcher({CHATGPT_CLIENT_ID: CHATGPT_DOC}):
            app = self.validator._load_application(CHATGPT_CLIENT_ID, _token_request(CHATGPT_CLIENT_ID))
        self.assertEqual(app.pk, manual.pk)
        self.assertEqual(app.client_type, Application.CLIENT_CONFIDENTIAL)
        self.assertEqual(app.registration_source, Application.RegistrationSource.MANUAL)


@override_settings(MCP_CIMD_PUBLIC_DOWNGRADE_CLIENT_IDS=_ALLOWLIST, OAUTH2_PROVIDER=_CIMD_ON)
class AssertionLoggingTests(TestCase):
    """The token step records a presented assertion as ignored."""

    LOGGER = "speedpycom.api.oauth_validator"

    def setUp(self):
        cache.clear()
        self.validator = SpeedPyOAuth2Validator()
        self.app = Application.objects.create(
            client_id=CHATGPT_CLIENT_ID,
            client_type=Application.CLIENT_PUBLIC,
            authorization_grant_type=Application.GRANT_AUTHORIZATION_CODE,
            redirect_uris=CHATGPT_REDIRECT,
            registration_source=Application.RegistrationSource.CIMD,
            cimd_expires_at=timezone.now() + timedelta(hours=1),
        )

    def test_a_presented_assertion_is_logged_and_the_public_client_authenticates(self):
        import jwt

        assertion = jwt.encode(
            {"iss": CHATGPT_CLIENT_ID}, "unused", algorithm="HS256", headers={"kid": "test-kid"}
        )
        body = (
            "grant_type=authorization_code"
            "&client_assertion_type=urn:ietf:params:oauth:client-assertion-type:jwt-bearer"
            f"&client_assertion={assertion}"
        )
        request = _token_request(CHATGPT_CLIENT_ID, body=body)
        with self.assertLogs(self.LOGGER, level="INFO") as captured:
            authenticated = self.validator.authenticate_client_id(CHATGPT_CLIENT_ID, request)
        self.assertTrue(authenticated)
        line = "\n".join(captured.output)
        self.assertIn("assertion_present=True", line)
        self.assertIn("jwt_alg='HS256'", line)
        self.assertIn("jwt_kid='test-kid'", line)
        self.assertIn("outcome=authenticated", line)
        self.assertIn("branch=public_client_id", line)
        self.assertNotIn(assertion, line)

    def test_the_raw_token_body_is_never_logged(self):
        body = "grant_type=authorization_code&code=SECRET_CODE&code_verifier=SECRET_VERIFIER"
        request = _token_request(CHATGPT_CLIENT_ID, body=body)
        with self.assertLogs(self.LOGGER, level="INFO") as captured:
            self.validator.authenticate_client_id(CHATGPT_CLIENT_ID, request)
        line = "\n".join(captured.output)
        self.assertIn("assertion_present=False", line)
        self.assertNotIn("SECRET_CODE", line)
        self.assertNotIn("SECRET_VERIFIER", line)

    def test_an_oversized_attacker_alg_is_bounded_in_the_log(self):
        import jwt

        assertion = jwt.encode({"iss": "x"}, "unused", algorithm="HS256", headers={"kid": "K" * 5000})
        request = _token_request(
            CHATGPT_CLIENT_ID,
            body=f"grant_type=authorization_code&client_assertion={assertion}",
        )
        with self.assertLogs(self.LOGGER, level="INFO") as captured:
            self.validator.authenticate_client_id(CHATGPT_CLIENT_ID, request)
        line = "\n".join(captured.output)
        self.assertIn("truncated", line)
        self.assertNotIn("K" * 200, line)

    def test_a_confidential_row_on_the_allowlisted_id_is_not_logged_as_a_downgrade(self):
        self.app.client_type = Application.CLIENT_CONFIDENTIAL
        self.app.registration_source = Application.RegistrationSource.MANUAL
        self.app.save()
        request = _token_request(CHATGPT_CLIENT_ID, body="grant_type=authorization_code")
        with self.assertNoLogs(self.LOGGER, level="INFO"):
            self.validator.authenticate_client_id(CHATGPT_CLIENT_ID, request)
