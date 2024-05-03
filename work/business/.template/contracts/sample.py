from abc import abstractmethod


class ISampleInterface:

    @abstractmethod
    def get_sample(self, **kwargs):
        ...



