from enum import Enum


class SidebarNavigationLinks(Enum):
    MARKET = 'Market'
    TRADE = 'Trade'
    QUOTE = 'Quote'
    TOP_STOCKS = 'Top Stocks'
    HEAT_MAP = 'Heat Map'
    NEWS = 'News'
    CHART = 'Chart'
    BROKER = 'Broker'


class AccountWidgetLinks(Enum):
    ORDER_LIST = 'Order List'
    PORTFOLIO = 'Portfolio'
    ACCOUNT_SUMMARY = 'Account Summary'
    ORDER_SEARCH = 'Order Search'
