# Paddle Billing Setup

SpeedPy ships a pluggable billing layer. This guide covers wiring **Paddle**
(Billing v2) as the provider. Billing is **off by default** — nothing here is
required to run the app locally or in demo mode.

See also: [STRIPE_SETUP.md](STRIPE_SETUP.md) for the Stripe provider, and
`mainapp/subscription_plans.py` for the canonical plan/price registry that drives
the pricing page, billing UI, feature gating, and the catalog command below.

SpeedPy uses its **own** thin Paddle adapter (`mainapp/billing/paddle.py`) — it
does not depend on `django-paddle-billing`. SpeedPy's local
`BillingCustomer`/`BillingSubscription` records are the source of truth.

## How billing works in SpeedPy

- The **billable account** is the `Team` when `SPEEDPY_TEAMS_ENABLED=True`, and the
  `User` when teams are disabled.
- The plan registry is the single source of truth. Provider price IDs are read
  from env vars; a missing ID disables checkout for that plan/interval only.
- Checkout `custom_data` carries `billable_type`, `billable_id`, `plan_key`, and
  `interval`; webhooks resolve the account from that data, never the email.
- Runtime state is three-valued: `enabled` / `grace` / `disabled`. Unknown
  statuses and prices never grant paid access (fail closed).

## 1. Enable billing

```bash
SPEEDPY_BILLING_ENABLED=True
SPEEDPY_BILLING_PROVIDER=paddle
SPEEDPY_BILLING_GRACE_PERIOD_DAYS=30   # optional, default 30
```

## 2. Sandbox vs production

Paddle keeps **sandbox** and **production** fully separate (different dashboards,
keys, and price IDs). Pick the environment explicitly:

```bash
PADDLE_ENVIRONMENT=sandbox    # or "production"
```

## 3. Keys & tokens

From the Paddle dashboard (Developer Tools):

```bash
PADDLE_API_KEY=...           # server-side API key (catalog, portal sessions)
PADDLE_CLIENT_TOKEN=...      # browser-safe client token (checkout only)
PADDLE_WEBHOOK_SECRET=...    # notification destination secret (step 5)
```

Minimal API key scopes: products & prices read/write (for catalog), customer
read/write, subscription read, customer portal sessions write.

Under **Checkout → Website approval**, add every domain that will open checkout
(production, staging, and `localhost` for development).

## 4. Create products & prices

The catalog command creates one product per paid plan and a monthly + yearly
price each, idempotently (matched by product name and billing interval). It skips
the free plan and the contact-us (Enterprise) tier. Prices are created with
`tax_mode: external` (tax added at checkout).

```bash
uv run python manage.py setup_paddle_catalog --dry-run   # preview, no API calls
uv run python manage.py setup_paddle_catalog             # create/sync
uv run python manage.py setup_paddle_catalog --tax-category=saas
```

Copy the printed env lines into your `.env`:

```bash
PADDLE_PRICE_PRO_MONTHLY=pri_...
PADDLE_PRICE_PRO_YEARLY=pri_...
PADDLE_PRICE_BUSINESS_MONTHLY=pri_...
PADDLE_PRICE_BUSINESS_YEARLY=pri_...
```

## 5. Webhook (notification) destination

Add a notification destination in the Paddle dashboard:

- **URL:** `https://your-domain/billing/webhooks/paddle/`
- **Events:** the `subscription.*` family — `subscription.created`,
  `subscription.activated`, `subscription.updated`, `subscription.past_due`,
  `subscription.paused`, `subscription.resumed`, `subscription.canceled`,
  `subscription.trialing`.

Copy the destination's secret into `PADDLE_WEBHOOK_SECRET`. Signatures are
verified directly against the `Paddle-Signature` header
(`ts=<unix>;h1=<hmac-sha256 of "{ts}:{body}">`). Events are de-duplicated by
event id, so retries and out-of-order deliveries are safe. The endpoint always
returns 200 for handled logic errors so Paddle does not retry indefinitely.

## 6. Status mapping

| Paddle status | Local status | Effect |
|---|---|---|
| `active`, `trialing` | active | paid features on |
| `past_due` | past_due | grace period (paid features on, new records blocked) |
| `paused` | paused | paid features on |
| `canceled` / `cancelled` | canceled | access until period end, then downgraded |
| unknown | ignored | never grants access |

## Go-live checklist

- [ ] `PADDLE_ENVIRONMENT=production` with production keys/tokens.
- [ ] Business/website verification approved in Paddle.
- [ ] Re-run `setup_paddle_catalog` against production and update price-id env vars.
- [ ] Register the production webhook destination and set `PADDLE_WEBHOOK_SECRET`.
- [ ] `SPEEDPY_BILLING_ENABLED=True`, `SPEEDPY_BILLING_PROVIDER=paddle`.
- [ ] Test a real checkout, the customer portal, and a cancellation end-to-end.
- [ ] Confirm the daily `process_billing_subscriptions` Celery beat task is running.
