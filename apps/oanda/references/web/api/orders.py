from apps.oanda.references.web.base_api_service import BaseApiServiceAppOanda
from core.web.services.core.decorators.deserializer import deserialized


class ApiServiceOandaOrders(BaseApiServiceAppOanda):

    def __init__(self, config, **kwargs):
        super(ApiServiceOandaOrders, self).__init__(config, **kwargs)
        self.initialize()

    def initialize(self):
        self.request.set_base_uri('accounts')

    @deserialized(dict)
    def create_order(self, account_id, order_body):
        """POST /accounts/{accountID}/orders

        Args:
            account_id: OANDA account ID
            order_body: Dict with 'order' key containing order parameters
        """
        self.request.post() \
            .add_uri_parameter(account_id) \
            .add_uri_parameter('orders') \
            .add_json_payload(order_body)

        return self.client.execute_request(self.request.build())

    @deserialized(dict, child='orders')
    def get_orders(self, account_id, instrument=None, state=None, count=50):
        """GET /accounts/{accountID}/orders

        Args:
            account_id: OANDA account ID
            instrument: Filter by instrument (e.g. 'EUR_USD')
            state: Filter by state (PENDING, FILLED, TRIGGERED, CANCELLED, ALL)
            count: Max orders to return (default 50)
        """
        self.request.get() \
            .add_uri_parameter(account_id) \
            .add_uri_parameter('orders') \
            .add_query_string('count', count)

        if instrument is not None:
            self.request.add_query_string('instrument', instrument)
        if state is not None:
            self.request.add_query_string('state', state)

        return self.client.execute_request(self.request.build())

    @deserialized(dict, child='orders')
    def get_pending_orders(self, account_id):
        """GET /accounts/{accountID}/pendingOrders

        Args:
            account_id: OANDA account ID
        """
        self.request.get() \
            .add_uri_parameter(account_id) \
            .add_uri_parameter('pendingOrders')

        return self.client.execute_request(self.request.build())

    @deserialized(dict, child='order')
    def get_order(self, account_id, order_specifier):
        """GET /accounts/{accountID}/orders/{orderSpecifier}

        Args:
            account_id: OANDA account ID
            order_specifier: Order ID or client order ID (prefix with '@' for client IDs)
        """
        self.request.get() \
            .add_uri_parameter(account_id) \
            .add_uri_parameter('orders') \
            .add_uri_parameter(order_specifier)

        return self.client.execute_request(self.request.build())

    @deserialized(dict)
    def replace_order(self, account_id, order_specifier, order_body):
        """PUT /accounts/{accountID}/orders/{orderSpecifier}

        Args:
            account_id: OANDA account ID
            order_specifier: Order ID or client order ID
            order_body: Dict with 'order' key containing replacement order parameters
        """
        self.request.put() \
            .add_uri_parameter(account_id) \
            .add_uri_parameter('orders') \
            .add_uri_parameter(order_specifier) \
            .add_json_payload(order_body)

        return self.client.execute_request(self.request.build())

    @deserialized(dict)
    def cancel_order(self, account_id, order_specifier):
        """PUT /accounts/{accountID}/orders/{orderSpecifier}/cancel

        Args:
            account_id: OANDA account ID
            order_specifier: Order ID or client order ID
        """
        self.request.put() \
            .add_uri_parameter(account_id) \
            .add_uri_parameter('orders') \
            .add_uri_parameter(order_specifier) \
            .add_uri_parameter('cancel')

        return self.client.execute_request(self.request.build())

    @deserialized(dict)
    def update_order_client_extensions(self, account_id, order_specifier, client_extensions_body):
        """PUT /accounts/{accountID}/orders/{orderSpecifier}/clientExtensions

        Args:
            account_id: OANDA account ID
            order_specifier: Order ID or client order ID
            client_extensions_body: Dict with clientExtensions and/or tradeClientExtensions
        """
        self.request.put() \
            .add_uri_parameter(account_id) \
            .add_uri_parameter('orders') \
            .add_uri_parameter(order_specifier) \
            .add_uri_parameter('clientExtensions') \
            .add_json_payload(client_extensions_body)

        return self.client.execute_request(self.request.build())
