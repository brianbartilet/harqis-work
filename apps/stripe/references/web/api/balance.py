"""Stripe Balance + Balance Transactions service.

Docs:
    https://docs.stripe.com/api/balance
    https://docs.stripe.com/api/balance_transactions
"""
from typing import Optional, List

from core.web.services.core.decorators.deserializer import deserialized
from apps.stripe.references.web.base_api_service import BaseApiServiceStripe
from apps.stripe.references.dto.balance import (
    DtoStripeBalance,
    DtoStripeBalanceTransaction,
)
from apps.stripe.references.dto.common import DtoStripeListResult


class ApiServiceStripeBalance(BaseApiServiceStripe):
    """Read account balance and the balance-transactions ledger."""

    def __init__(self, config, **kwargs):
        super().__init__(config, **kwargs)

    @deserialized(DtoStripeBalance)
    def get_balance(self) -> DtoStripeBalance:
        """Current account balance — `available`, `pending`, `instant_available`."""
        self.request.get().add_uri_parameter('balance')
        return self.client.execute_request(self.request.build())

    @deserialized(DtoStripeListResult, many=False)
    def list_balance_transactions(
        self,
        limit: int = 10,
        starting_after: Optional[str] = None,
        ending_before: Optional[str] = None,
        type_filter: Optional[str] = None,
    ) -> DtoStripeListResult:
        """List balance transactions (charges, refunds, payouts, fees).

        Args:
            limit:           Page size (1-100). Stripe default is 10.
            starting_after:  Pagination cursor — id of the last item from the previous page.
            ending_before:   Reverse-pagination cursor.
            type_filter:     Restrict to a transaction type
                             (`charge`, `refund`, `payout`, `adjustment`, …).
        """
        self.request.get().add_uri_parameter('balance_transactions') \
            .add_query_string('limit', str(limit))
        if starting_after:
            self.request.add_query_string('starting_after', starting_after)
        if ending_before:
            self.request.add_query_string('ending_before', ending_before)
        if type_filter:
            self.request.add_query_string('type', type_filter)
        return self.client.execute_request(self.request.build())

    @deserialized(DtoStripeBalanceTransaction)
    def get_balance_transaction(self, txn_id: str) -> DtoStripeBalanceTransaction:
        """Get a single balance-transaction ledger entry by id."""
        self.request.get().add_uri_parameter(f'balance_transactions/{txn_id}')
        return self.client.execute_request(self.request.build())
