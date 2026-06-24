"""
OpenAPI schema quality tests.

Asserts that every public operation has an explicit operationId, summary,
description, and tags, and that the tag metadata covers all used tags.
"""

import tempfile

import yaml
from django.core.management import call_command
from django.test import TestCase

# HTTP methods that represent operations in an OpenAPI path item.
_HTTP_METHODS = {"get", "put", "post", "delete", "options", "head", "patch", "trace"}

# Expected operation IDs — these are the generated-client method-name contract.
# Changing any of these breaks downstream generated clients.
EXPECTED_OPERATION_IDS = {
    "createToken",
    "refreshToken",
    "revokeToken",
    "getCurrentUser",
    "updateCurrentUser",
    "listTeams",
    "getTeam",
    "listTeamMembers",
    "createTeamInvitation",
    "listProducts",
    "getProduct",
    "listTeamWebhookEndpoints",
    "createTeamWebhookEndpoint",
    "getTeamWebhookEndpoint",
    "updateTeamWebhookEndpoint",
    "patchTeamWebhookEndpoint",
    "deleteTeamWebhookEndpoint",
    "rotateTeamWebhookEndpointSecret",
    "testTeamWebhookEndpoint",
    "listTeamWebhookDeliveries",
    "getTeamWebhookDelivery",
    "retryTeamWebhookDelivery",
    "listUserWebhookEndpoints",
    "getIntegrationManifest",
    "dcr_register",
}


def _generate_schema():
    """Generate, validate, and parse the OpenAPI schema."""
    with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as f:
        path = f.name
    call_command("spectacular", "--file", path, "--validate")
    with open(path) as f:
        return yaml.safe_load(f.read())


class OpenAPISchemaQualityTest(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.schema = _generate_schema()
        # Collect ALL operations, including those missing operationId.
        cls.operations = []
        for path, methods in cls.schema.get("paths", {}).items():
            for method, op in methods.items():
                if method in _HTTP_METHODS and isinstance(op, dict):
                    cls.operations.append((path, method, op))

    def test_schema_validates(self):
        """Schema should be parseable and contain paths."""
        self.assertIn("paths", self.schema)
        self.assertGreater(len(self.schema["paths"]), 0)

    def test_all_operations_have_operation_id(self):
        for path, method, op in self.operations:
            with self.subTest(path=path, method=method):
                self.assertIn("operationId", op, f"{method.upper()} {path} missing operationId")
                self.assertTrue(op["operationId"].strip())

    def test_all_operations_have_summary(self):
        for path, method, op in self.operations:
            with self.subTest(path=path, method=method):
                self.assertIn("summary", op, f"{method.upper()} {path} missing summary")
                self.assertTrue(op["summary"].strip())

    def test_all_operations_have_description(self):
        for path, method, op in self.operations:
            with self.subTest(path=path, method=method):
                self.assertIn("description", op, f"{method.upper()} {path} missing description")
                self.assertTrue(op["description"].strip())

    def test_all_operations_have_tags(self):
        for path, method, op in self.operations:
            with self.subTest(path=path, method=method):
                self.assertIn("tags", op, f"{method.upper()} {path} missing tags")
                self.assertGreater(len(op["tags"]), 0)

    def test_expected_operation_ids_present(self):
        actual_ids = {op.get("operationId") for _, _, op in self.operations}
        missing = EXPECTED_OPERATION_IDS - actual_ids
        self.assertFalse(missing, f"Missing expected operation IDs: {missing}")

    def test_no_duplicate_operation_ids(self):
        ids = [op["operationId"] for _, _, op in self.operations if "operationId" in op]
        duplicates = {oid for oid in ids if ids.count(oid) > 1}
        self.assertFalse(duplicates, f"Duplicate operation IDs: {duplicates}")

    def test_tag_metadata_covers_all_used_tags(self):
        defined_tags = {t["name"] for t in self.schema.get("tags", [])}
        used_tags = set()
        for _, _, op in self.operations:
            used_tags.update(op.get("tags", []))
        missing = used_tags - defined_tags
        self.assertFalse(missing, f"Tags used but not defined in metadata: {missing}")

    def test_oauth2_tag_defined(self):
        """The oauth2 tag must be in top-level metadata since DCR uses it."""
        tag_names = {t["name"] for t in self.schema.get("tags", [])}
        self.assertIn("oauth2", tag_names)
