from apps.oanda.references.web.base_api_service import BaseApiServiceAppOanda
from core.web.services.core.decorators.deserializer import deserialized


class ApiServiceTrades(BaseApiServiceAppOanda):

    def __init__(self, config, **kwargs):
        super(ApiServiceTrades, self).__init__(config, **kwargs)
        self.initialize()

    def initialize(self):
        self.request.set_base_uri('accounts')

    @deserialized(dict, child='trades')
    def get_trades_from_account(self, account_id, **kwargs):
        """GET /accounts/{accountID}/trades

        Args:
            account_id: OANDA account ID
            **kwargs: Optional query params: instrument, state, count, ids, beforeID
        """
        self.request.get() \
            .add_uri_parameter(account_id) \
            .add_uri_parameter('trades') \
            .add_query_strings(**kwargs)

        return self.client.execute_request(self.request.build())

    @deserialized(dict, child='trades')
    def get_open_trades_from_account(self, account_id):
        """GET /accounts/{accountID}/openTrades

        Args:
            account_id: OANDA account ID
        """
        self.request.get() \
            .add_uri_parameter(account_id) \
            .add_uri_parameter('openTrades')

        return self.client.execute_request(self.request.build())

    @deserialized(dict, child='trade')
    def get_trade(self, account_id, trade_specifier):
        """GET /accounts/{accountID}/trades/{tradeSpecifier}

        Args:
            account_id: OANDA account ID
            trade_specifier: Trade ID or client trade ID (prefix '@' for client IDs)
        """
        self.request.get() \
            .add_uri_parameter(account_id) \
            .add_uri_parameter('trades') \
            .add_uri_parameter(trade_specifier)

        return self.client.execute_request(self.request.build())

    @deserialized(dict)
    def close_trade(self, account_id, trade_specifier, units=None):
        """PUT /accounts/{accountID}/trades/{tradeSpecifier}/close

        Args:
            account_id: OANDA account ID
            trade_specifier: Trade ID or client trade ID
            units: Number of units to close (omit or 'ALL' to close entirely)
        """
        body = {}
        if units is not None:
            body['units'] = str(units)

        self.request.put() \
            .add_uri_parameter(account_id) \
            .add_uri_parameter('trades') \
            .add_uri_parameter(trade_specifier) \
            .add_uri_parameter('close') \
            .add_json_payload(body)

        return self.client.execute_request(self.request.build())

    @deserialized(dict)
    def update_trade_client_extensions(self, account_id, trade_specifier, client_extensions_body):
        """PUT /accounts/{accountID}/trades/{tradeSpecifier}/clientExtensions

        Args:
            account_id: OANDA account ID
            trade_specifier: Trade ID or client trade ID
            client_extensions_body: Dict with tradeClientExtensions key
        """
        self.request.put() \
            .add_uri_parameter(account_id) \
            .add_uri_parameter('trades') \
            .add_uri_parameter(trade_specifier) \
            .add_uri_parameter('clientExtensions') \
            .add_json_payload(client_extensions_body)

        return self.client.execute_request(self.request.build())

    @deserialized(dict)
    def update_trade_orders(self, account_id, trade_specifier, orders_body):
        """PUT /accounts/{accountID}/trades/{tradeSpecifier}/orders

        Modify the take profit, stop loss, or trailing stop loss orders
        attached to a trade.

        Args:
            account_id: OANDA account ID
            trade_specifier: Trade ID or client trade ID
            orders_body: Dict with takeProfit, stopLoss, guaranteedStopLoss,
                         and/or trailingStopLoss keys
        """
        self.request.put() \
            .add_uri_parameter(account_id) \
            .add_uri_parameter('trades') \
            .add_uri_parameter(trade_specifier) \
            .add_uri_parameter('orders') \
            .add_json_payload(orders_body)

        return self.client.execute_request(self.request.build())
