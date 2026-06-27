"""Tests for the catalog management commands in dry-run mode (no API calls)."""

from io import StringIO

from django.core.management import call_command
from django.test import TestCase


class StripeCatalogCommandTests(TestCase):
    def test_dry_run_lists_paid_plans_and_env_vars(self):
        out = StringIO()
        call_command("setup_stripe_catalog", "--dry-run", stdout=out)
        output = out.getvalue()
        self.assertIn("DRY RUN", output)
        self.assertIn("STRIPE_PRICE_PRO_MONTHLY=", output)
        self.assertIn("STRIPE_PRICE_BUSINESS_YEARLY=", output)
        # Free plan never appears; enterprise (contact) is skipped.
        self.assertNotIn("STRIPE_PRICE_FREE", output)
        self.assertIn("skipping contact-us plan", output)


class PaddleCatalogCommandTests(TestCase):
    def test_dry_run_lists_paid_plans_and_env_vars(self):
        out = StringIO()
        call_command("setup_paddle_catalog", "--dry-run", stdout=out)
        output = out.getvalue()
        self.assertIn("DRY RUN", output)
        self.assertIn("PADDLE_PRICE_PRO_MONTHLY=", output)
        self.assertIn("PADDLE_PRICE_BUSINESS_YEARLY=", output)
        self.assertNotIn("PADDLE_PRICE_FREE", output)
        self.assertIn("skipping contact-us plan", output)
