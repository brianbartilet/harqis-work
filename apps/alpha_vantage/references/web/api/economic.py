"""
Economic Indicator APIs.

Reference: https://www.alphavantage.co/documentation/#economic-indicators
"""
from apps.alpha_vantage.references.web.base_api_service import BaseApiServiceAlphaVantage
from core.web.services.core.decorators.deserializer import deserialized


class ApiServiceAlphaVantageEconomic(BaseApiServiceAlphaVantage):
    """US economic indicators — GDP, rates, inflation, employment."""

    def __init__(self, config, **kwargs):
        super(ApiServiceAlphaVantageEconomic, self).__init__(config, **kwargs)

    @deserialized(dict)
    def get_real_gdp(self, interval='annual', datatype=None):
        """function=REAL_GDP — real GDP. Interval: 'annual' or 'quarterly'."""
        return self._query('REAL_GDP', interval=interval, datatype=datatype)

    @deserialized(dict)
    def get_real_gdp_per_capita(self, datatype=None):
        """function=REAL_GDP_PER_CAPITA — real GDP per capita (annual)."""
        return self._query('REAL_GDP_PER_CAPITA', datatype=datatype)

    @deserialized(dict)
    def get_treasury_yield(self, interval='monthly', maturity='10year', datatype=None):
        """function=TREASURY_YIELD — Treasury yield curve.

        Args:
            interval: 'daily', 'weekly', 'monthly'.
            maturity: '3month', '2year', '5year', '7year', '10year', '30year'.
        """
        return self._query('TREASURY_YIELD',
                           interval=interval, maturity=maturity, datatype=datatype)

    @deserialized(dict)
    def get_federal_funds_rate(self, interval='monthly', datatype=None):
        """function=FEDERAL_FUNDS_RATE — effective Federal Funds rate."""
        return self._query('FEDERAL_FUNDS_RATE', interval=interval, datatype=datatype)

    @deserialized(dict)
    def get_cpi(self, interval='monthly', datatype=None):
        """function=CPI — Consumer Price Index. Interval: 'monthly' or 'semiannual'."""
        return self._query('CPI', interval=interval, datatype=datatype)

    @deserialized(dict)
    def get_inflation(self, datatype=None):
        """function=INFLATION — annual inflation rate."""
        return self._query('INFLATION', datatype=datatype)

    @deserialized(dict)
    def get_retail_sales(self, datatype=None):
        """function=RETAIL_SALES — monthly retail sales."""
        return self._query('RETAIL_SALES', datatype=datatype)

    @deserialized(dict)
    def get_durables(self, datatype=None):
        """function=DURABLES — durable goods orders."""
        return self._query('DURABLES', datatype=datatype)

    @deserialized(dict)
    def get_unemployment(self, datatype=None):
        """function=UNEMPLOYMENT — unemployment rate."""
        return self._query('UNEMPLOYMENT', datatype=datatype)

    @deserialized(dict)
    def get_nonfarm_payroll(self, datatype=None):
        """function=NONFARM_PAYROLL — nonfarm employment change."""
        return self._query('NONFARM_PAYROLL', datatype=datatype)
