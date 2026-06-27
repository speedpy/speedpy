# Stripe Billing Setup

SpeedPy ships a pluggable billing layer. This guide covers wiring **Stripe** as
the provider. Billing is **off by default** — nothing here is required to run the
app locally or in demo mode.

See also: [PADDLE_SETUP.md](PADDLE_SETUP.md) for the Paddle provider, and
`mainapp/subscription_plans.py` for the canonical plan/price registry that drives
the pricing page, billing UI, feature gating, and the catalog command below.

## How billing works in SpeedPy

- The **billable account** is the `Team` when `SPEEDPY_TEAMS_ENABLED=True`, and the
  `User` when teams are disabled.
- The plan registry (`mainapp/subscription_plans.py`) is the single source of
  truth. Provider price IDs are read from env vars so a missing ID never breaks
  the app — it just disables checkout for that plan/interval.
- Checkout metadata carries `billable_type`, `billable_id`, `plan_key`, and
  `interval`; webhooks resolve the account from that metadata, never the email.
- Runtime state is three-valued: `enabled` / `grace` / `disabled`. Unknown
  statuses and prices never grant paid access (fail closed).

## 1. Enable billing

```bash
SPEEDPY_BILLING_ENABLED=True
SPEEDPY_BILLING_PROVIDER=stripe
SPEEDPY_BILLING_GRACE_PERIOD_DAYS=30   # optional, default 30
```

## 2. API keys

Create a **restricted** or standard secret key in the Stripe Dashboard
(Developers → API keys). For catalog setup and checkout/portal you need:
products & prices write, checkout sessions write, billing portal sessions write,
subscriptions read.

```bash
STRIPE_SECRET_KEY=sk_test_...        # or sk_live_... in production
STRIPE_PUBLISHABLE_KEY=pk_test_...   # optional, for client-side use
STRIPE_WEBHOOK_SECRET=whsec_...      # from the webhook endpoint (step 4)
```

Use **test mode** keys for staging and **live mode** keys for production — they
are separate Stripe environments.

## 3. Create products & prices

The catalog command creates one product per paid plan and a recurring monthly +
yearly price each, idempotently (stable price **lookup keys** `<plan>_<interval>`).
It skips the free plan and the contact-us (Enterprise) tier.

```bash
uv run python manage.py setup_stripe_catalog --dry-run   # preview, no API calls
uv run python manage.py setup_stripe_catalog             # create/sync
```

Copy the printed env lines into your `.env`:

```bash
STRIPE_PRICE_PRO_MONTHLY=price_...
STRIPE_PRICE_PRO_YEARLY=price_...
STRIPE_PRICE_BUSINESS_MONTHLY=price_...
STRIPE_PRICE_BUSINESS_YEARLY=price_...
```

Re-running the command reuses existing prices by lookup key, so it is safe.

## 4. Webhook endpoint

Add an endpoint in the Stripe Dashboard (Developers → Webhooks):

- **URL:** `https://your-domain/billing/webhooks/stripe/`
- **Events:** `checkout.session.completed`, `customer.subscription.created`,
  `customer.subscription.updated`, `customer.subscription.deleted`.
  (`invoice.payment_failed` surfaces as a `customer.subscription.updated` with
  status `past_due`, which is handled.)

Copy the signing secret into `STRIPE_WEBHOOK_SECRET`. Signatures are verified with
`stripe.Webhook.construct_event`; events are de-duplicated by event id, so retries
and out-of-order deliveries are safe.

## 5. Status mapping

| Stripe status | Local status | Effect |
|---|---|---|
| `active`, `trialing` | active | paid features on |
| `past_due` | past_due | grace period (paid features on, new records blocked) |
| `paused` | paused | paid features on |
| `canceled` | canceled | access until period end, then downgraded to free |
| `unpaid` | expired | downgraded to free |
| `incomplete*`, unknown | ignored | never grants access |

## Go-live checklist

- [ ] Switch to live `STRIPE_SECRET_KEY` / `STRIPE_WEBHOOK_SECRET`.
- [ ] Re-run `setup_stripe_catalog` against live mode and update the price-id env vars.
- [ ] Register the live webhook endpoint and confirm it receives events.
- [ ] `SPEEDPY_BILLING_ENABLED=True`, `SPEEDPY_BILLING_PROVIDER=stripe`.
- [ ] Test a real checkout, the customer portal, and a cancellation end-to-end.
- [ ] Confirm the daily `process_billing_subscriptions` Celery beat task is running.
