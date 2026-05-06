"""Stripe Invoices service.

Docs: https://docs.stripe.com/api/invoices
"""
from typing import Optional

from core.web.services.core.decorators.deserializer import deserialized
from apps.stripe.references.web.base_api_service import BaseApiServiceStripe
from apps.stripe.references.dto.invoices import DtoStripeInvoice
from apps.stripe.references.dto.common import DtoStripeListResult


class ApiServiceStripeInvoices(BaseApiServiceStripe):
    """Read and manage invoices."""

    def __init__(self, config, **kwargs):
        super().__init__(config, **kwargs)

    @deserialized(DtoStripeListResult, many=False)
    def list_invoices(
        self,
        limit: int = 10,
        customer: Optional[str] = None,
        status: Optional[str] = None,
        subscription: Optional[str] = None,
        starting_after: Optional[str] = None,
    ) -> DtoStripeListResult:
        """List invoices, most recent first.

        Args:
            limit:         Page size (1-100).
            customer:      Filter by customer id.
            status:        Filter by status: `draft`, `open`, `paid`, `uncollectible`, `void`.
            subscription:  Filter by subscription id.
            starting_after: Pagination cursor.
        """
        self.request.get().add_uri_parameter('invoices') \
            .add_query_string('limit', str(limit))
        if customer:
            self.request.add_query_string('customer', customer)
        if status:
            self.request.add_query_string('status', status)
        if subscription:
            self.request.add_query_string('subscription', subscription)
        if starting_after:
            self.request.add_query_string('starting_after', starting_after)
        return self.client.execute_request(self.request.build())

    @deserialized(DtoStripeInvoice)
    def get_invoice(self, invoice_id: str) -> DtoStripeInvoice:
        """Retrieve a single invoice by id."""
        self.request.get().add_uri_parameter(f'invoices/{invoice_id}')
        return self.client.execute_request(self.request.build())

    def create_invoice(
        self,
        customer: str,
        auto_advance: bool = True,
        collection_method: str = 'charge_automatically',
        description: Optional[str] = None,
    ) -> dict:
        """Create a draft invoice for a customer.

        With `auto_advance=True` Stripe will finalise and attempt collection
        automatically; pass `False` to keep it as a draft for manual review.
        """
        body: dict = {
            'customer': customer,
            'auto_advance': str(auto_advance).lower(),
            'collection_method': collection_method,
        }
        if description:
            body['description'] = description
        self.request.post().add_uri_parameter('invoices').set_body(body)
        return self.client.execute_request(self.request.build())

    def finalize_invoice(self, invoice_id: str) -> dict:
        """Move a draft invoice into the `open` state and lock its line items."""
        self.request.post().add_uri_parameter(f'invoices/{invoice_id}/finalize')
        return self.client.execute_request(self.request.build())

    def send_invoice(self, invoice_id: str) -> dict:
        """Email the invoice to the customer (only for collection_method=send_invoice)."""
        self.request.post().add_uri_parameter(f'invoices/{invoice_id}/send')
        return self.client.execute_request(self.request.build())

    def void_invoice(self, invoice_id: str) -> dict:
        """Void an open invoice — irreversible."""
        self.request.post().add_uri_parameter(f'invoices/{invoice_id}/void')
        return self.client.execute_request(self.request.build())

    @deserialized(DtoStripeInvoice)
    def get_upcoming_invoice(self, customer: str) -> DtoStripeInvoice:
        """Preview the next invoice for a customer (e.g. next subscription period)."""
        self.request.get().add_uri_parameter('invoices/upcoming') \
            .add_query_string('customer', customer)
        return self.client.execute_request(self.request.build())
