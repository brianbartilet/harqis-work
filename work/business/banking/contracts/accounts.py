from abc import abstractmethod


class IBankAccounts:

    @abstractmethod
    def get_customer_information(self, **kwargs):
        ...

    @abstractmethod
    def get_account_information(self, **kwargs):
        ...

    @abstractmethod
    def get_account_transactions(self, **kwargs):
        ...

