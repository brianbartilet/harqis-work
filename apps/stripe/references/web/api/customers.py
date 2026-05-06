"""Stripe Customers service.

Docs: https://docs.stripe.com/api/customers
"""
from typing import Optional

from core.web.services.core.decorators.deserializer import deserialized
from apps.stripe.references.web.base_api_service import BaseApiServiceStripe
from apps.stripe.references.dto.customers import DtoStripeCustomer
from apps.stripe.references.dto.common import DtoStripeListResult


class ApiServiceStripeCustomers(BaseApiServiceStripe):
    """Customer CRUD."""

    def __init__(self, config, **kwargs):
        super().__init__(config, **kwargs)

    @deserialized(DtoStripeListResult, many=False)
    def list_customers(
        self,
        limit: int = 10,
        email: Optional[str] = None,
        starting_after: Optional[str] = None,
    ) -> DtoStripeListResult:
        """List customers. Filter by `email` for an exact-match lookup
        (Stripe stores email case-sensitively but matches case-insensitively)."""
        self.request.get().add_uri_parameter('customers') \
            .add_query_string('limit', str(limit))
        if email:
            self.request.add_query_string('email', email)
        if starting_after:
            self.request.add_query_string('starting_after', starting_after)
        return self.client.execute_request(self.request.build())

    @deserialized(DtoStripeCustomer)
    def get_customer(self, customer_id: str) -> DtoStripeCustomer:
        """Retrieve a single customer by id."""
        self.request.get().add_uri_parameter(f'customers/{customer_id}')
        return self.client.execute_request(self.request.build())

    def create_customer(
        self,
        email: Optional[str] = None,
        name: Optional[str] = None,
        description: Optional[str] = None,
        phone: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> dict:
        """Create a customer record."""
        body: dict = {}
        if email:
            body['email'] = email
        if name:
            body['name'] = name
        if description:
            body['description'] = description
        if phone:
            body['phone'] = phone
        if metadata:
            for k, v in metadata.items():
                body[f'metadata[{k}]'] = v
        self.request.post().add_uri_parameter('customers').set_body(body)
        return self.client.execute_request(self.request.build())

    def update_customer(self, customer_id: str, **fields) -> dict:
        """Update fields on a customer. Pass any of: email, name, description,
        phone, metadata (dict). See Stripe docs for the full field list."""
        body: dict = {}
        for k, v in fields.items():
            if k == 'metadata' and isinstance(v, dict):
                for mk, mv in v.items():
                    body[f'metadata[{mk}]'] = mv
            else:
                body[k] = v
        self.request.post().add_uri_parameter(f'customers/{customer_id}').set_body(body)
        return self.client.execute_request(self.request.build())

    def delete_customer(self, customer_id: str) -> dict:
        """Permanently delete a customer. Cancels all active subscriptions."""
        self.request.delete().add_uri_parameter(f'customers/{customer_id}')
        return self.client.execute_request(self.request.build())

    @deserialized(DtoStripeListResult, many=False)
    def search_customers(self, query: str, limit: int = 10) -> DtoStripeListResult:
        """Search customers using Stripe's query language.

        Examples: `email:'a@b.com'`, `name:'Brian'`, `metadata['key']:'value'`.
        Docs: https://docs.stripe.com/search
        """
        self.request.get().add_uri_parameter('customers/search') \
            .add_query_string('query', query) \
            .add_query_string('limit', str(limit))
        return self.client.execute_request(self.request.build())
