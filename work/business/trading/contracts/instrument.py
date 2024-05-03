from abc import abstractmethod


class IInstrument:

    @abstractmethod
    def get_quote(self, **kwargs) -> dict:
        ...
