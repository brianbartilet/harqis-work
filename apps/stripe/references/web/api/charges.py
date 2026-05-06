"""Stripe Charges service.

Docs: https://docs.stripe.com/api/charges
"""
from typing import Optional

from core.web.services.core.decorators.deserializer import deserialized
from apps.stripe.references.web.base_api_service import BaseApiServiceStripe
from apps.stripe.references.dto.charges import DtoStripeCharge
from apps.stripe.references.dto.common import DtoStripeListResult


class ApiServiceStripeCharges(BaseApiServiceStripe):
    """Read and create one-off charges. For modern integrations, prefer
    PaymentIntents (`apps.stripe.references.web.api.payment_intents`)."""

    def __init__(self, config, **kwargs):
        super().__init__(config, **kwargs)

    @deserialized(DtoStripeListResult, many=False)
    def list_charges(
        self,
        limit: int = 10,
        customer: Optional[str] = None,
        starting_after: Optional[str] = None,
    ) -> DtoStripeListResult:
        """List recent charges, most recent first."""
        self.request.get().add_uri_parameter('charges') \
            .add_query_string('limit', str(limit))
        if customer:
            self.request.add_query_string('customer', customer)
        if starting_after:
            self.request.add_query_string('starting_after', starting_after)
        return self.client.execute_request(self.request.build())

    @deserialized(DtoStripeCharge)
    def get_charge(self, charge_id: str) -> DtoStripeCharge:
        """Retrieve a single charge by id."""
        self.request.get().add_uri_parameter(f'charges/{charge_id}')
        return self.client.execute_request(self.request.build())

    def create_charge(
        self,
        amount: int,
        currency: str,
        source: Optional[str] = None,
        customer: Optional[str] = None,
        description: Optional[str] = None,
    ) -> dict:
        """Create a charge (legacy API — prefer PaymentIntents).

        Args:
            amount:      Smallest currency unit (cents for USD).
            currency:    ISO-4217 lowercase, e.g. `'usd'`.
            source:      Payment source token (card token, source id).
            customer:    Existing customer id (use instead of `source` for
                         saved customers).
            description: Free-form description shown in the dashboard.
        """
        body: dict = {'amount': amount, 'currency': currency}
        if source:
            body['source'] = source
        if customer:
            body['customer'] = customer
        if description:
            body['description'] = description
        self.request.post().add_uri_parameter('charges').set_body(body)
        return self.client.execute_request(self.request.build())
