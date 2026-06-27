"""Create/sync Stripe products & prices for the paid subscription plans.

Driven by the canonical plan registry (``mainapp.subscription_plans``). Idempotent
via stable price **lookup keys** (``<plan>_<interval>``): on rerun, existing
prices are reused rather than duplicated, and their product is reused too. Prints
the resulting ``.env`` price-id lines.

Skips the free plan and any contact-us tier. Never needs live credentials for
``--dry-run``.

Usage:
    uv run python manage.py setup_stripe_catalog
    uv run python manage.py setup_stripe_catalog --dry-run
"""

import stripe
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from mainapp.subscription_plans import INTERVALS, get_paid_plans

_STRIPE_INTERVAL = {"monthly": "month", "yearly": "year"}


def env_var_name(plan_key, interval):
    return f"STRIPE_PRICE_{plan_key.upper()}_{interval.upper()}"


def lookup_key(plan_key, interval):
    return f"{plan_key}_{interval}"


class Command(BaseCommand):
    help = "Create or sync Stripe products and recurring prices for the paid plans."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be created without calling the Stripe API.",
        )

    def handle(self, *args, **options):
        self.dry_run = options["dry_run"]

        if not self.dry_run:
            if not settings.STRIPE_SECRET_KEY:
                raise CommandError("STRIPE_SECRET_KEY is not set (use --dry-run to preview).")
            stripe.api_key = settings.STRIPE_SECRET_KEY

        self.stdout.write("Stripe catalog sync" + (" [DRY RUN]" if self.dry_run else ""))
        env_lines = []

        for cfg in get_paid_plans():
            if cfg.get("is_contact"):
                self.stdout.write(f"- skipping contact-us plan: {cfg['name']}")
                continue

            product_name = f"{settings.TITLE} {cfg['name']}"
            product_id = self._resolve_product(cfg, product_name)

            for interval in INTERVALS:
                amount = cfg["price_monthly"] if interval == "monthly" else cfg["price_yearly"]
                key = lookup_key(cfg["key"], interval)
                env_var = env_var_name(cfg["key"], interval)

                price = None if self.dry_run else self._find_price(key)
                if price:
                    self.stdout.write(f"  = price exists: {key} ({price['id']})")
                elif self.dry_run:
                    self.stdout.write(f"  + would create price: {key} (${amount})")
                    price = {"id": f"<{key}_price_id>"}
                else:
                    price = stripe.Price.create(
                        product=product_id,
                        currency="usd",
                        unit_amount=int(amount) * 100,
                        recurring={"interval": _STRIPE_INTERVAL[interval]},
                        lookup_key=key,
                        transfer_lookup_key=True,
                        metadata={"plan_key": cfg["key"], "interval": interval},
                    )
                    self.stdout.write(
                        self.style.SUCCESS(f"  + created price: {key} ({price['id']})")
                    )

                env_lines.append(f"{env_var}={price['id']}")

        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("Add these to your .env:"))
        self.stdout.write("\n".join(env_lines))

    def _resolve_product(self, cfg, product_name):
        """Reuse the product backing an existing price for this plan, else create."""
        if self.dry_run:
            self.stdout.write(f"+ would ensure product: {product_name}")
            return f"<{cfg['key']}_product_id>"

        for interval in INTERVALS:
            price = self._find_price(lookup_key(cfg["key"], interval))
            if price:
                return price["product"]

        product = stripe.Product.create(
            name=product_name, metadata={"plan_key": cfg["key"]}
        )
        self.stdout.write(self.style.SUCCESS(f"+ created product: {product_name} ({product['id']})"))
        return product["id"]

    @staticmethod
    def _find_price(key):
        prices = stripe.Price.list(lookup_keys=[key], limit=1)
        return prices["data"][0] if prices["data"] else None
