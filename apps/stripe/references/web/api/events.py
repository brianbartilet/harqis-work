"""Stripe Events service.

Events are the audit trail — every state change in your account creates
an event. Useful for backfilling missed webhooks or building activity feeds.

Docs: https://docs.stripe.com/api/events
"""
from typing import Optional, List

from core.web.services.core.decorators.deserializer import deserialized
from apps.stripe.references.web.base_api_service import BaseApiServiceStripe
from apps.stripe.references.dto.events import DtoStripeEvent
from apps.stripe.references.dto.common import DtoStripeListResult


class ApiServiceStripeEvents(BaseApiServiceStripe):
    """List and retrieve events."""

    def __init__(self, config, **kwargs):
        super().__init__(config, **kwargs)

    @deserialized(DtoStripeListResult, many=False)
    def list_events(
        self,
        limit: int = 10,
        type_filter: Optional[str] = None,
        types: Optional[List[str]] = None,
        starting_after: Optional[str] = None,
    ) -> DtoStripeListResult:
        """List events, most recent first.

        Args:
            limit:        Page size (1-100).
            type_filter:  Filter by a single event type (e.g. `charge.succeeded`).
            types:        Filter by multiple event types.
            starting_after: Pagination cursor.
        """
        self.request.get().add_uri_parameter('events') \
            .add_query_string('limit', str(limit))
        if type_filter:
            self.request.add_query_string('type', type_filter)
        for i, t in enumerate(types or []):
            self.request.add_query_string(f'types[{i}]', t)
        if starting_after:
            self.request.add_query_string('starting_after', starting_after)
        return self.client.execute_request(self.request.build())

    @deserialized(DtoStripeEvent)
    def get_event(self, event_id: str) -> DtoStripeEvent:
        """Retrieve a single event by id."""
        self.request.get().add_uri_parameter(f'events/{event_id}')
        return self.client.execute_request(self.request.build())
