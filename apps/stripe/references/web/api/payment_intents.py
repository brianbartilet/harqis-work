"""Stripe PaymentIntents service.

PaymentIntents is the modern replacement for direct Charges — it tracks
the full lifecycle of a payment including SCA / 3DS authentication.

Docs: https://docs.stripe.com/api/payment_intents
"""
from typing import Optional, List

from core.web.services.core.decorators.deserializer import deserialized
from apps.stripe.references.web.base_api_service import BaseApiServiceStripe
from apps.stripe.references.dto.payment_intents import DtoStripePaymentIntent
from apps.stripe.references.dto.common import DtoStripeListResult


class ApiServiceStripePaymentIntents(BaseApiServiceStripe):
    """PaymentIntent lifecycle — create, retrieve, confirm, capture, cancel."""

    def __init__(self, config, **kwargs):
        super().__init__(config, **kwargs)

    @deserialized(DtoStripeListResult, many=False)
    def list_payment_intents(
        self,
        limit: int = 10,
        customer: Optional[str] = None,
        starting_after: Optional[str] = None,
    ) -> DtoStripeListResult:
        """List PaymentIntents, most recent first."""
        self.request.get().add_uri_parameter('payment_intents') \
            .add_query_string('limit', str(limit))
        if customer:
            self.request.add_query_string('customer', customer)
        if starting_after:
            self.request.add_query_string('starting_after', starting_after)
        return self.client.execute_request(self.request.build())

    @deserialized(DtoStripePaymentIntent)
    def get_payment_intent(self, intent_id: str) -> DtoStripePaymentIntent:
        """Retrieve a single PaymentIntent by id."""
        self.request.get().add_uri_parameter(f'payment_intents/{intent_id}')
        return self.client.execute_request(self.request.build())

    def create_payment_intent(
        self,
        amount: int,
        currency: str,
        customer: Optional[str] = None,
        payment_method: Optional[str] = None,
        confirm: bool = False,
        description: Optional[str] = None,
        payment_method_types: Optional[List[str]] = None,
    ) -> dict:
        """Create a PaymentIntent.

        Args:
            amount:               Smallest currency unit (cents for USD).
            currency:             ISO-4217 lowercase, e.g. `'usd'`.
            customer:             Customer id to attach the intent to.
            payment_method:       PaymentMethod id to associate.
            confirm:              If True, confirm immediately (skip the
                                  client-side `stripe.confirmPayment` call).
            description:          Free-form description.
            payment_method_types: Allowed payment-method types (default
                                  `['card']`).
        """
        body: dict = {'amount': amount, 'currency': currency}
        if customer:
            body['customer'] = customer
        if payment_method:
            body['payment_method'] = payment_method
        if confirm:
            body['confirm'] = 'true'
        if description:
            body['description'] = description
        for i, pmt in enumerate(payment_method_types or []):
            body[f'payment_method_types[{i}]'] = pmt
        self.request.post().add_uri_parameter('payment_intents').set_body(body)
        return self.client.execute_request(self.request.build())

    def confirm_payment_intent(
        self,
        intent_id: str,
        payment_method: Optional[str] = None,
    ) -> dict:
        """Confirm a previously-created PaymentIntent."""
        body: dict = {}
        if payment_method:
            body['payment_method'] = payment_method
        self.request.post().add_uri_parameter(f'payment_intents/{intent_id}/confirm').set_body(body)
        return self.client.execute_request(self.request.build())

    def cancel_payment_intent(
        self,
        intent_id: str,
        cancellation_reason: Optional[str] = None,
    ) -> dict:
        """Cancel a PaymentIntent that hasn't completed yet."""
        body: dict = {}
        if cancellation_reason:
            body['cancellation_reason'] = cancellation_reason
        self.request.post().add_uri_parameter(f'payment_intents/{intent_id}/cancel').set_body(body)
        return self.client.execute_request(self.request.build())
