"""Create/sync Paddle products & prices for the paid subscription plans.

Driven by the canonical plan registry (``mainapp.subscription_plans``) so Paddle
never drifts from the app's own plan definitions. Idempotent: matches existing
products by name and existing prices by (product, billing interval), reusing them
instead of creating duplicates. Prints the resulting ``.env`` price-id lines.

Skips the free plan and any contact-us tier. Never needs live credentials for
``--dry-run``.

Usage:
    uv run python manage.py setup_paddle_catalog
    uv run python manage.py setup_paddle_catalog --dry-run
    uv run python manage.py setup_paddle_catalog --tax-category=saas
"""

import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from mainapp.billing.paddle import api_base
from mainapp.subscription_plans import INTERVALS, get_paid_plans

# Paddle interval keyword per local interval.
_PADDLE_INTERVAL = {"monthly": "month", "yearly": "year"}
_TIMEOUT = 30


def env_var_name(plan_key, interval):
    return f"PADDLE_PRICE_{plan_key.upper()}_{interval.upper()}"


class Command(BaseCommand):
    help = "Create or sync Paddle products and prices for the paid plans."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be created without calling the Paddle API.",
        )
        parser.add_argument(
            "--tax-category",
            default="standard",
            help="Paddle tax category for products (default: standard).",
        )

    def handle(self, *args, **options):
        self.dry_run = options["dry_run"]
        self.tax_category = options["tax_category"]

        if not self.dry_run and not settings.PADDLE_API_KEY:
            raise CommandError("PADDLE_API_KEY is not set (use --dry-run to preview).")

        self.base = api_base()
        self.headers = {
            "Authorization": f"Bearer {getattr(settings, 'PADDLE_API_KEY', '')}",
            "Content-Type": "application/json",
        }

        self.stdout.write(
            f"Paddle environment '{getattr(settings, 'PADDLE_ENVIRONMENT', 'sandbox')}' ({self.base})"
            + (" [DRY RUN]" if self.dry_run else "")
        )

        existing_products = {} if self.dry_run else {p["name"]: p for p in self._list("/products")}
        env_lines = []

        for cfg in get_paid_plans():
            if cfg.get("is_contact"):
                self.stdout.write(f"- skipping contact-us plan: {cfg['name']}")
                continue

            product_name = f"{settings.TITLE} {cfg['name']}"
            product = existing_products.get(product_name)
            if product:
                self.stdout.write(f"= product exists: {product_name} ({product['id']})")
            elif self.dry_run:
                self.stdout.write(f"+ would create product: {product_name}")
                product = {"id": f"<{cfg['key']}_product_id>"}
            else:
                product = self._create_product(product_name)
                self.stdout.write(
                    self.style.SUCCESS(f"+ created product: {product_name} ({product['id']})")
                )

            existing_prices = (
                [] if self.dry_run else self._list(f"/prices?product_id={product['id']}")
            )
            by_interval = {
                pr.get("billing_cycle", {}).get("interval"): pr
                for pr in existing_prices
                if pr.get("billing_cycle")
            }

            for interval in INTERVALS:
                amount = cfg["price_monthly"] if interval == "monthly" else cfg["price_yearly"]
                paddle_interval = _PADDLE_INTERVAL[interval]
                env_var = env_var_name(cfg["key"], interval)

                price = by_interval.get(paddle_interval)
                if price:
                    self.stdout.write(
                        f"  = price exists: {cfg['name']} {interval} ({price['id']})"
                    )
                elif self.dry_run:
                    self.stdout.write(
                        f"  + would create price: {cfg['name']} {interval} (${amount})"
                    )
                    price = {"id": f"<{cfg['key']}_{interval}_price_id>"}
                else:
                    price = self._create_price(
                        product_id=product["id"],
                        description=f"{cfg['name']} {interval.capitalize()}",
                        amount_cents=str(int(amount) * 100),
                        interval=paddle_interval,
                    )
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"  + created price: {cfg['name']} {interval} ({price['id']})"
                        )
                    )

                env_lines.append(f"{env_var}={price['id']}")

        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("Add these to your .env:"))
        self.stdout.write("\n".join(env_lines))

    # ----- API helpers -------------------------------------------------

    def _list(self, path):
        results = []
        url = f"{self.base}{path}"
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}per_page=200"
        while url:
            resp = requests.get(url, headers=self.headers, timeout=_TIMEOUT)
            self._raise_for_status(resp, f"GET {path}")
            body = resp.json()
            results.extend(body.get("data", []))
            pagination = body.get("meta", {}).get("pagination", {})
            url = pagination.get("next") if pagination.get("has_more") else None
        return results

    def _create_product(self, name):
        payload = {"name": name, "tax_category": self.tax_category, "type": "standard"}
        resp = requests.post(
            f"{self.base}/products", headers=self.headers, json=payload, timeout=_TIMEOUT
        )
        self._raise_for_status(resp, "POST /products")
        return resp.json()["data"]

    def _create_price(self, product_id, description, amount_cents, interval):
        payload = {
            "product_id": product_id,
            "description": description,
            "unit_price": {"amount": amount_cents, "currency_code": "USD"},
            "billing_cycle": {"interval": interval, "frequency": 1},
            "tax_mode": "external",
        }
        resp = requests.post(
            f"{self.base}/prices", headers=self.headers, json=payload, timeout=_TIMEOUT
        )
        self._raise_for_status(resp, "POST /prices")
        return resp.json()["data"]

    def _raise_for_status(self, resp, what):
        if resp.status_code >= 400:
            raise CommandError(f"{what} failed [{resp.status_code}]: {resp.text}")
