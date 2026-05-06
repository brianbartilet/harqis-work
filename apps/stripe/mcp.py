"""MCP tools for Stripe.

Exposes the safe / read-heavy Stripe operations to AI agents. Mutating
operations (`create_customer`, `cancel_subscription`, `void_invoice`, …)
are intentionally exposed too — gate them via the agent profile's
`tools.allowed` allowlist if you want a read-only Stripe agent.
"""
import logging
from typing import Optional, List

from mcp.server.fastmcp import FastMCP

from apps.stripe.config import CONFIG
from apps.stripe.references.web.api.balance import ApiServiceStripeBalance
from apps.stripe.references.web.api.charges import ApiServiceStripeCharges
from apps.stripe.references.web.api.customers import ApiServiceStripeCustomers
from apps.stripe.references.web.api.invoices import ApiServiceStripeInvoices
from apps.stripe.references.web.api.payment_intents import ApiServiceStripePaymentIntents
from apps.stripe.references.web.api.subscriptions import ApiServiceStripeSubscriptions
from apps.stripe.references.web.api.events import ApiServiceStripeEvents

logger = logging.getLogger("harqis-mcp.stripe")


def _to_dict(obj):
    if hasattr(obj, "__dict__"):
        return obj.__dict__
    if isinstance(obj, dict):
        return obj
    return {}


def _list_dump(result) -> List[dict]:
    """Stripe list responses come back as `DtoStripeListResult` with a
    `data` list that may contain raw dicts (untyped) or DTO instances."""
    items = getattr(result, "data", None) or []
    return [_to_dict(i) for i in items]


def register_stripe_tools(mcp: FastMCP):

    # ── Balance ──────────────────────────────────────────────────────────────

    @mcp.tool()
    def stripe_get_balance() -> dict:
        """Current Stripe account balance: available, pending, and instant-available
        amounts split per currency. Amounts are in the smallest currency unit
        (cents for USD)."""
        logger.info("Tool called: stripe_get_balance")
        result = ApiServiceStripeBalance(CONFIG).get_balance()
        return _to_dict(result)

    @mcp.tool()
    def stripe_list_balance_transactions(
        limit: int = 10,
        type_filter: Optional[str] = None,
    ) -> List[dict]:
        """List balance-ledger entries (charges, refunds, payouts, fees), newest first.

        Args:
            limit:       Page size (1-100). Default 10.
            type_filter: Restrict to a transaction type — `charge`, `refund`,
                         `payout`, `adjustment`, `application_fee`, …
        """
        logger.info("Tool called: stripe_list_balance_transactions limit=%s type=%s",
                    limit, type_filter)
        result = ApiServiceStripeBalance(CONFIG).list_balance_transactions(
            limit=limit, type_filter=type_filter,
        )
        items = _list_dump(result)
        logger.info("stripe_list_balance_transactions returned %d item(s)", len(items))
        return items

    # ── Charges ──────────────────────────────────────────────────────────────

    @mcp.tool()
    def stripe_list_charges(limit: int = 10, customer: Optional[str] = None) -> List[dict]:
        """List recent charges, newest first.

        Args:
            limit:    Page size (1-100). Default 10.
            customer: Filter by customer id (`cus_…`).
        """
        logger.info("Tool called: stripe_list_charges limit=%s customer=%s", limit, customer)
        result = ApiServiceStripeCharges(CONFIG).list_charges(limit=limit, customer=customer)
        return _list_dump(result)

    @mcp.tool()
    def stripe_get_charge(charge_id: str) -> dict:
        """Retrieve a single charge by id (`ch_…`).

        Args:
            charge_id: Stripe charge id, prefixed `ch_`.
        """
        logger.info("Tool called: stripe_get_charge id=%s", charge_id)
        return _to_dict(ApiServiceStripeCharges(CONFIG).get_charge(charge_id))

    # ── Customers ────────────────────────────────────────────────────────────

    @mcp.tool()
    def stripe_list_customers(limit: int = 10, email: Optional[str] = None) -> List[dict]:
        """List customers; optionally filter by exact email match.

        Args:
            limit: Page size (1-100). Default 10.
            email: Exact email match (case-insensitive).
        """
        logger.info("Tool called: stripe_list_customers limit=%s email=%s", limit, email)
        result = ApiServiceStripeCustomers(CONFIG).list_customers(limit=limit, email=email)
        return _list_dump(result)

    @mcp.tool()
    def stripe_get_customer(customer_id: str) -> dict:
        """Retrieve a single customer by id (`cus_…`)."""
        logger.info("Tool called: stripe_get_customer id=%s", customer_id)
        return _to_dict(ApiServiceStripeCustomers(CONFIG).get_customer(customer_id))

    @mcp.tool()
    def stripe_search_customers(query: str, limit: int = 10) -> List[dict]:
        """Search customers using Stripe's query language.

        Args:
            query: Stripe search expression. Examples:
                   `email:'a@b.com'`, `name:'Brian'`, `metadata['org']:'acme'`.
                   Docs: https://docs.stripe.com/search
            limit: Page size (1-100). Default 10.
        """
        logger.info("Tool called: stripe_search_customers query=%r", query)
        result = ApiServiceStripeCustomers(CONFIG).search_customers(query=query, limit=limit)
        return _list_dump(result)

    @mcp.tool()
    def stripe_create_customer(
        email: Optional[str] = None,
        name: Optional[str] = None,
        description: Optional[str] = None,
        phone: Optional[str] = None,
    ) -> dict:
        """Create a customer record. Returns the new customer object including
        its assigned id (`cus_…`).

        Args:
            email:       Customer email.
            name:        Display name.
            description: Free-form description (visible in the Stripe dashboard).
            phone:       E.164 phone number.
        """
        logger.info("Tool called: stripe_create_customer email=%s", email)
        return _to_dict(ApiServiceStripeCustomers(CONFIG).create_customer(
            email=email, name=name, description=description, phone=phone,
        ))

    # ── Invoices ─────────────────────────────────────────────────────────────

    @mcp.tool()
    def stripe_list_invoices(
        limit: int = 10,
        customer: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[dict]:
        """List invoices, newest first.

        Args:
            limit:    Page size (1-100). Default 10.
            customer: Filter by customer id.
            status:   Filter by status — `draft`, `open`, `paid`, `uncollectible`, `void`.
        """
        logger.info("Tool called: stripe_list_invoices limit=%s customer=%s status=%s",
                    limit, customer, status)
        result = ApiServiceStripeInvoices(CONFIG).list_invoices(
            limit=limit, customer=customer, status=status,
        )
        return _list_dump(result)

    @mcp.tool()
    def stripe_get_invoice(invoice_id: str) -> dict:
        """Retrieve a single invoice by id (`in_…`)."""
        logger.info("Tool called: stripe_get_invoice id=%s", invoice_id)
        return _to_dict(ApiServiceStripeInvoices(CONFIG).get_invoice(invoice_id))

    @mcp.tool()
    def stripe_get_upcoming_invoice(customer: str) -> dict:
        """Preview the next invoice for a customer (e.g. next subscription period)."""
        logger.info("Tool called: stripe_get_upcoming_invoice customer=%s", customer)
        return _to_dict(ApiServiceStripeInvoices(CONFIG).get_upcoming_invoice(customer))

    # ── Payment Intents ──────────────────────────────────────────────────────

    @mcp.tool()
    def stripe_list_payment_intents(
        limit: int = 10,
        customer: Optional[str] = None,
    ) -> List[dict]:
        """List PaymentIntents, newest first."""
        logger.info("Tool called: stripe_list_payment_intents limit=%s customer=%s",
                    limit, customer)
        result = ApiServiceStripePaymentIntents(CONFIG).list_payment_intents(
            limit=limit, customer=customer,
        )
        return _list_dump(result)

    @mcp.tool()
    def stripe_get_payment_intent(intent_id: str) -> dict:
        """Retrieve a single PaymentIntent by id (`pi_…`)."""
        logger.info("Tool called: stripe_get_payment_intent id=%s", intent_id)
        return _to_dict(ApiServiceStripePaymentIntents(CONFIG).get_payment_intent(intent_id))

    # ── Subscriptions ────────────────────────────────────────────────────────

    @mcp.tool()
    def stripe_list_subscriptions(
        limit: int = 10,
        customer: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[dict]:
        """List subscriptions.

        Args:
            limit:    Page size (1-100). Default 10.
            customer: Filter by customer id.
            status:   Filter by status — `active`, `past_due`, `canceled`,
                      `trialing`, `all`.
        """
        logger.info("Tool called: stripe_list_subscriptions limit=%s customer=%s status=%s",
                    limit, customer, status)
        result = ApiServiceStripeSubscriptions(CONFIG).list_subscriptions(
            limit=limit, customer=customer, status=status,
        )
        return _list_dump(result)

    @mcp.tool()
    def stripe_get_subscription(subscription_id: str) -> dict:
        """Retrieve a single subscription by id (`sub_…`)."""
        logger.info("Tool called: stripe_get_subscription id=%s", subscription_id)
        return _to_dict(ApiServiceStripeSubscriptions(CONFIG).get_subscription(subscription_id))

    # ── Events ───────────────────────────────────────────────────────────────

    @mcp.tool()
    def stripe_list_events(
        limit: int = 10,
        type_filter: Optional[str] = None,
    ) -> List[dict]:
        """List events (audit trail / webhook history), newest first.

        Args:
            limit:       Page size (1-100). Default 10.
            type_filter: Filter by event type — e.g. `charge.succeeded`,
                         `invoice.paid`, `customer.subscription.deleted`.
        """
        logger.info("Tool called: stripe_list_events limit=%s type=%s", limit, type_filter)
        result = ApiServiceStripeEvents(CONFIG).list_events(
            limit=limit, type_filter=type_filter,
        )
        return _list_dump(result)

    @mcp.tool()
    def stripe_get_event(event_id: str) -> dict:
        """Retrieve a single event by id (`evt_…`)."""
        logger.info("Tool called: stripe_get_event id=%s", event_id)
        return _to_dict(ApiServiceStripeEvents(CONFIG).get_event(event_id))
