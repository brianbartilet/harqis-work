"""
Commodities APIs.

Reference: https://www.alphavantage.co/documentation/#commodities

All commodity functions take an optional `interval` of 'daily', 'weekly',
or 'monthly' (some default differently per indicator — see docs).
"""
from apps.alpha_vantage.references.web.base_api_service import BaseApiServiceAlphaVantage
from core.web.services.core.decorators.deserializer import deserialized


class ApiServiceAlphaVantageCommodities(BaseApiServiceAlphaVantage):
    """Commodities — energy, metals, agricultural products, global index."""

    def __init__(self, config, **kwargs):
        super(ApiServiceAlphaVantageCommodities, self).__init__(config, **kwargs)

    def _commodity(self, function, interval=None, datatype=None):
        return self._query(function, interval=interval, datatype=datatype)

    @deserialized(dict)
    def get_wti(self, interval='monthly', datatype=None):
        """function=WTI — West Texas Intermediate crude oil."""
        return self._commodity('WTI', interval=interval, datatype=datatype)

    @deserialized(dict)
    def get_brent(self, interval='monthly', datatype=None):
        """function=BRENT — Brent crude oil."""
        return self._commodity('BRENT', interval=interval, datatype=datatype)

    @deserialized(dict)
    def get_natural_gas(self, interval='monthly', datatype=None):
        """function=NATURAL_GAS — natural gas spot price."""
        return self._commodity('NATURAL_GAS', interval=interval, datatype=datatype)

    @deserialized(dict)
    def get_copper(self, interval='monthly', datatype=None):
        """function=COPPER — copper price."""
        return self._commodity('COPPER', interval=interval, datatype=datatype)

    @deserialized(dict)
    def get_aluminum(self, interval='monthly', datatype=None):
        """function=ALUMINUM — aluminum price."""
        return self._commodity('ALUMINUM', interval=interval, datatype=datatype)

    @deserialized(dict)
    def get_wheat(self, interval='monthly', datatype=None):
        """function=WHEAT — wheat price."""
        return self._commodity('WHEAT', interval=interval, datatype=datatype)

    @deserialized(dict)
    def get_corn(self, interval='monthly', datatype=None):
        """function=CORN — corn price."""
        return self._commodity('CORN', interval=interval, datatype=datatype)

    @deserialized(dict)
    def get_cotton(self, interval='monthly', datatype=None):
        """function=COTTON — cotton price."""
        return self._commodity('COTTON', interval=interval, datatype=datatype)

    @deserialized(dict)
    def get_sugar(self, interval='monthly', datatype=None):
        """function=SUGAR — sugar price."""
        return self._commodity('SUGAR', interval=interval, datatype=datatype)

    @deserialized(dict)
    def get_coffee(self, interval='monthly', datatype=None):
        """function=COFFEE — coffee price."""
        return self._commodity('COFFEE', interval=interval, datatype=datatype)

    @deserialized(dict)
    def get_all_commodities(self, interval='monthly', datatype=None):
        """function=ALL_COMMODITIES — global commodities index."""
        return self._commodity('ALL_COMMODITIES', interval=interval, datatype=datatype)
