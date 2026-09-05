"""Tests for the ``setup_stripe_catalog`` management command.

The command reads Stripe SDK objects with bracket access (``price["id"]``,
``prices["data"]``). Stripe v15 keeps bracket reads on ``StripeObject`` but drops
``dict`` inheritance, so these tests feed real SDK objects (not plain dicts) to
prove both the reuse and create paths still work.
"""

from io import StringIO
from unittest.mock import patch

import stripe
from django.core.management import call_command
from django.test import TestCase, override_settings

from mainapp.subscription_plans import get_paid_plans

_CMD = "mainapp.management.commands.setup_stripe_catalog.stripe"


def _has_creatable_plan():
    return any(not cfg.get("is_contact") for cfg in get_paid_plans())


@override_settings(STRIPE_SECRET_KEY="sk_test")
class SetupStripeCatalogTests(TestCase):
    def setUp(self):
        if not _has_creatable_plan():
            self.skipTest("no creatable paid plans configured")

    @patch(f"{_CMD}.Price.create")
    @patch(f"{_CMD}.Product.create")
    @patch(f"{_CMD}.Price.list")
    def test_creates_products_and_prices_when_absent(self, mock_list, mock_prod, mock_price):
        # No existing prices anywhere -> create product + prices.
        mock_list.return_value = stripe.ListObject.construct_from(
            {"object": "list", "data": []}, "sk_test"
        )
        mock_prod.return_value = stripe.Product.construct_from(
            {"id": "prod_new"}, "sk_test"
        )
        mock_price.side_effect = lambda **kw: stripe.Price.construct_from(
            {"id": f"price_{kw['lookup_key']}", "product": "prod_new"}, "sk_test"
        )

        out = StringIO()
        call_command("setup_stripe_catalog", stdout=out)

        self.assertTrue(mock_prod.called)
        self.assertTrue(mock_price.called)
        self.assertIn("created price", out.getvalue())

    @patch(f"{_CMD}.Price.create")
    @patch(f"{_CMD}.Product.create")
    @patch(f"{_CMD}.Price.list")
    def test_reuses_existing_prices(self, mock_list, mock_prod, mock_price):
        # Every lookup finds an existing price -> nothing is created.
        mock_list.return_value = stripe.ListObject.construct_from(
            {"object": "list", "data": [{"id": "price_existing", "product": "prod_existing"}]},
            "sk_test",
        )

        out = StringIO()
        call_command("setup_stripe_catalog", stdout=out)

        self.assertFalse(mock_prod.called)
        self.assertFalse(mock_price.called)
        self.assertIn("price exists", out.getvalue())

    def test_dry_run_makes_no_sdk_calls(self):
        with patch(f"{_CMD}.Price.list") as mock_list:
            out = StringIO()
            call_command("setup_stripe_catalog", "--dry-run", stdout=out)
            self.assertFalse(mock_list.called)
