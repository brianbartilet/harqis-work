"""Stripe Subscriptions service.

Docs: https://docs.stripe.com/api/subscriptions
"""
from typing import Optional, List

from core.web.services.core.decorators.deserializer import deserialized
from apps.stripe.references.web.base_api_service import BaseApiServiceStripe
from apps.stripe.references.dto.subscriptions import DtoStripeSubscription
from apps.stripe.references.dto.common import DtoStripeListResult


class ApiServiceStripeSubscriptions(BaseApiServiceStripe):
    """Subscription lifecycle."""

    def __init__(self, config, **kwargs):
        super().__init__(config, **kwargs)

    @deserialized(DtoStripeListResult, many=False)
    def list_subscriptions(
        self,
        limit: int = 10,
        customer: Optional[str] = None,
        status: Optional[str] = None,
        price: Optional[str] = None,
        starting_after: Optional[str] = None,
    ) -> DtoStripeListResult:
        """List subscriptions.

        Args:
            limit:    Page size (1-100).
            customer: Filter by customer id.
            status:   Filter by status — `active`, `past_due`, `unpaid`,
                      `canceled`, `incomplete`, `incomplete_expired`,
                      `trialing`, `all`.
            price:    Filter by price id.
        """
        self.request.get().add_uri_parameter('subscriptions') \
            .add_query_string('limit', str(limit))
        if customer:
            self.request.add_query_string('customer', customer)
        if status:
            self.request.add_query_string('status', status)
        if price:
            self.request.add_query_string('price', price)
        if starting_after:
            self.request.add_query_string('starting_after', starting_after)
        return self.client.execute_request(self.request.build())

    @deserialized(DtoStripeSubscription)
    def get_subscription(self, subscription_id: str) -> DtoStripeSubscription:
        """Retrieve a single subscription by id."""
        self.request.get().add_uri_parameter(f'subscriptions/{subscription_id}')
        return self.client.execute_request(self.request.build())

    def create_subscription(
        self,
        customer: str,
        prices: List[str],
        trial_period_days: Optional[int] = None,
        default_payment_method: Optional[str] = None,
    ) -> dict:
        """Create a subscription for a customer.

        Args:
            customer:               Customer id.
            prices:                 List of price ids to attach as line items.
            trial_period_days:      Optional trial length.
            default_payment_method: Override the customer's default PM.
        """
        body: dict = {'customer': customer}
        for i, price in enumerate(prices):
            body[f'items[{i}][price]'] = price
        if trial_period_days is not None:
            body['trial_period_days'] = trial_period_days
        if default_payment_method:
            body['default_payment_method'] = default_payment_method
        self.request.post().add_uri_parameter('subscriptions').set_body(body)
        return self.client.execute_request(self.request.build())

    def update_subscription(self, subscription_id: str, **fields) -> dict:
        """Update arbitrary fields on a subscription. See Stripe docs for the
        full field list. Pass `cancel_at_period_end=True` to schedule
        cancellation at the end of the current billing period."""
        self.request.post().add_uri_parameter(f'subscriptions/{subscription_id}').set_body(fields)
        return self.client.execute_request(self.request.build())

    def cancel_subscription(
        self,
        subscription_id: str,
        invoice_now: bool = False,
        prorate: bool = False,
    ) -> dict:
        """Cancel a subscription immediately (irreversible).

        Use `update_subscription(id, cancel_at_period_end=True)` to schedule
        cancellation at the end of the current billing period instead.
        """
        body: dict = {
            'invoice_now': str(invoice_now).lower(),
            'prorate': str(prorate).lower(),
        }
        self.request.delete().add_uri_parameter(f'subscriptions/{subscription_id}').set_body(body)
        return self.client.execute_request(self.request.build())
