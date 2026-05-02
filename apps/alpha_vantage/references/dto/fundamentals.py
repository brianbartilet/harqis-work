from dataclasses import dataclass
from typing import Optional


@dataclass
class DtoAlphaVantageCompanyOverview:
    """Company overview & ratios (function=OVERVIEW)."""
    Symbol: Optional[str] = None
    AssetType: Optional[str] = None
    Name: Optional[str] = None
    Description: Optional[str] = None
    CIK: Optional[str] = None
    Exchange: Optional[str] = None
    Currency: Optional[str] = None
    Country: Optional[str] = None
    Sector: Optional[str] = None
    Industry: Optional[str] = None
    Address: Optional[str] = None
    FiscalYearEnd: Optional[str] = None
    LatestQuarter: Optional[str] = None
    MarketCapitalization: Optional[str] = None
    EBITDA: Optional[str] = None
    PERatio: Optional[str] = None
    PEGRatio: Optional[str] = None
    BookValue: Optional[str] = None
    DividendPerShare: Optional[str] = None
    DividendYield: Optional[str] = None
    EPS: Optional[str] = None
    RevenuePerShareTTM: Optional[str] = None
    ProfitMargin: Optional[str] = None
    OperatingMarginTTM: Optional[str] = None
    ReturnOnAssetsTTM: Optional[str] = None
    ReturnOnEquityTTM: Optional[str] = None
    RevenueTTM: Optional[str] = None
    GrossProfitTTM: Optional[str] = None
    DilutedEPSTTM: Optional[str] = None
    QuarterlyEarningsGrowthYOY: Optional[str] = None
    QuarterlyRevenueGrowthYOY: Optional[str] = None
    AnalystTargetPrice: Optional[str] = None
    TrailingPE: Optional[str] = None
    ForwardPE: Optional[str] = None
    PriceToSalesRatioTTM: Optional[str] = None
    PriceToBookRatio: Optional[str] = None
    EVToRevenue: Optional[str] = None
    EVToEBITDA: Optional[str] = None
    Beta: Optional[str] = None
    SharesOutstanding: Optional[str] = None
    DividendDate: Optional[str] = None
    ExDividendDate: Optional[str] = None
    # 52-week range metrics use camelCase like '52WeekHigh', not valid Python attrs;
    # those are read directly off the dict response.
