from abc import abstractmethod


class IOrders:

    @abstractmethod
    def execute_order(self, **kwargs):
        ...

    @abstractmethod
    def cancel_order(self, **kwargs):
        ...

    @abstractmethod
    def get_orders(self, **kwargs):
        ...

