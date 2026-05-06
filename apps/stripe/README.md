# Stripe

Integration with the [Stripe REST API v1](https://docs.stripe.com/api). Payments, customers, invoices, subscriptions, balance, and the events audit trail.

## Description

Stripe processes payments, manages customers, runs subscriptions, and emits an event stream that doubles as an audit log. This integration covers the read-heavy and lightly-mutating endpoints needed for finance dashboards, daily reconciliation, and customer/subscription management. Webhook handling is not in scope — use the `events` API as a polling alternative if you don't host a public webhook endpoint.

**API docs:** https://docs.stripe.com/api  
**Auth:** Bearer token (the secret key — `sk_live_…` or `sk_test_…`). Stripe's docs document Basic-Auth-with-secret-key as the primary mechanism but explicitly support `Authorization: Bearer <key>` as an alternative.  
**Wire format:** GET requests use query parameters; **POST/DELETE bodies are `application/x-www-form-urlencoded`** (NOT JSON — this is unusual for modern REST APIs and the base service overrides the framework default to match).

## Supported Automations

- [x] webservices
- [ ] browser
- [ ] desktop
- [ ] mobile
- [ ] iot

## Directory Structure

```
apps/stripe/
├── README.md
├── __init__.py
├── config.py
├── mcp.py
├── references/
│   ├── __init__.py
│   ├── dto/
│   │   ├── __init__.py
│   │   ├── balance.py
│   │   ├── charges.py
│   │   ├── common.py
│   │   ├── customers.py
│   │   ├── events.py
│   │   ├── invoices.py
│   │   ├── payment_intents.py
│   │   └── subscriptions.py
│   └── web/
│       ├── __init__.py
│       ├── base_api_service.py
│       └── api/
│           ├── __init__.py
│           ├── balance.py
│           ├── charges.py
│           ├── customers.py
│           ├── events.py
│           ├── invoices.py
│           ├── payment_intents.py
│           └── subscriptions.py
└── tests/
    ├── __init__.py
    ├── test_balance.py
    ├── test_charges.py
    ├── test_customers.py
    ├── test_events.py
    ├── test_invoices.py
    ├── test_payment_intents.py
    └── test_subscriptions.py
```

## Configuration

`apps_config.yaml`:

```yaml
STRIPE:
  app_id: 'stripe'
  client: 'rest'
  parameters:
    base_url: 'https://api.stripe.com/v1'
    response_encoding: 'utf-8'
    verify: True
    timeout: 60
    stream: False
  app_data:
    api_key: ${STRIPE_API_KEY}
  return_data_only: True
```

`.env/apps.env`:

```
STRIPE_API_KEY=sk_test_...      # or sk_live_... for production
```

## Available Services

| Service class | Methods | Purpose |
|---|---|---|
| `ApiServiceStripeBalance` | `get_balance`, `list_balance_transactions`, `get_balance_transaction` | Account balance + ledger entries |
| `ApiServiceStripeCharges` | `list_charges`, `get_charge`, `create_charge` | Legacy one-off charges (prefer PaymentIntents) |
| `ApiServiceStripeCustomers` | `list_customers`, `get_customer`, `create_customer`, `update_customer`, `delete_customer`, `search_customers` | Customer CRUD + Stripe-search-language queries |
| `ApiServiceStripeInvoices` | `list_invoices`, `get_invoice`, `create_invoice`, `finalize_invoice`, `send_invoice`, `void_invoice`, `get_upcoming_invoice` | Invoice lifecycle + next-period preview |
| `ApiServiceStripePaymentIntents` | `list_payment_intents`, `get_payment_intent`, `create_payment_intent`, `confirm_payment_intent`, `cancel_payment_intent` | Modern payment lifecycle (SCA / 3DS) |
| `ApiServiceStripeSubscriptions` | `list_subscriptions`, `get_subscription`, `create_subscription`, `update_subscription`, `cancel_subscription` | Subscription lifecycle |
| `ApiServiceStripeEvents` | `list_events`, `get_event` | Audit trail / webhook history (use as a polling alternative to webhooks) |

## MCP Tools

| Tool | Args | Returns |
|---|---|---|
| `stripe_get_balance` | — | Account balance dict (`available`, `pending`, `instant_available`) |
| `stripe_list_balance_transactions` | `limit?`, `type_filter?` | List of ledger entries |
| `stripe_list_charges` | `limit?`, `customer?` | List of charges |
| `stripe_get_charge` | `charge_id` | Single charge |
| `stripe_list_customers` | `limit?`, `email?` | List of customers |
| `stripe_get_customer` | `customer_id` | Single customer |
| `stripe_search_customers` | `query`, `limit?` | Stripe-search-language result list |
| `stripe_create_customer` | `email?`, `name?`, `description?`, `phone?` | New customer object |
| `stripe_list_invoices` | `limit?`, `customer?`, `status?` | List of invoices |
| `stripe_get_invoice` | `invoice_id` | Single invoice |
| `stripe_get_upcoming_invoice` | `customer` | Preview of next invoice for a customer |
| `stripe_list_payment_intents` | `limit?`, `customer?` | List of PaymentIntents |
| `stripe_get_payment_intent` | `intent_id` | Single PaymentIntent |
| `stripe_list_subscriptions` | `limit?`, `customer?`, `status?` | List of subscriptions |
| `stripe_get_subscription` | `subscription_id` | Single subscription |
| `stripe_list_events` | `limit?`, `type_filter?` | List of events |
| `stripe_get_event` | `event_id` | Single event |

## Tests

```sh
pytest apps/stripe/tests/ -m smoke         # quick read-only checks
pytest apps/stripe/tests/ -m sanity        # round-trip list → get
```

All tests are live integration tests — they hit `api.stripe.com`. Set `STRIPE_API_KEY` in `.env/apps.env` first; a test-mode key (`sk_test_...`) is sufficient.

## Notes

- **Pagination** is cursor-based via `starting_after` (id of the last seen item) and `limit` (1-100, default 10).
- **Money is in the smallest currency unit** — `1099` USD = `$10.99`. The `currency` field is ISO-4217 lowercase (`usd`, `eur`, `gbp`).
- **Search** (`stripe_search_customers`) uses Stripe's own query language: `email:'a@b.com'`, `name:'Brian'`, `metadata['org']:'acme'`. See https://docs.stripe.com/search.
- **Idempotency** keys (`Idempotency-Key` header) are not implemented in this scaffold — for retry-safe writes from a Celery task, add the header in your service call before retrying.
- **Webhooks** are not in scope. Use `list_events` as a polling alternative if you can't host a public webhook endpoint.
- **Mutating tools** (`stripe_create_customer`, etc.) are exposed via MCP — gate them via the agent profile's `tools.allowed` allowlist if you want a read-only Stripe agent.
- The base service overrides the framework's default `Content-Type: application/json` to `application/x-www-form-urlencoded` — required by Stripe.
