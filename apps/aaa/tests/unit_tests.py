import unittest

from core.web.browser.fixtures.web_driver import BaseFixtureWebDriverLoader
from core.web.browser.core.config.web_driver import AppConfigWebDriver

from apps.aaa.config import CONFIG
from apps.aaa.references.pages import *
from apps.aaa.references.constants.strings import CLEAN_CHARS
from apps.aaa.references.constants.links import SidebarNavigationLinks
from apps.aaa.references.models.orders import *
from apps.aaa.references.models.orders import ModelOrderAAA

from hamcrest import equal_to, greater_than_or_equal_to

from core.config.env_variables import Environment, ENV


class TestAAAEquities(unittest.TestCase):

    def setUp(self):
        self.config = CONFIG
        self.driver_loader = BaseFixtureWebDriverLoader(self.config)
        self.driver_properties = self.driver_loader.properties

        self.driver_loader.driver.get(self.config.parameters['url'])

    def test_login(self):
        pl = PageAAALogin(**self.driver_properties)
        pl.login()
        pl.driver.close()

    def test_navigate(self):
        pl = PageAAALogin(**self.driver_properties)
        pl.login()

        pt = PageAAATradingDeskMarket(**self.driver_properties)
        pt.navigate_to_page(SidebarNavigationLinks.MARKET)
        pt.navigate_to_page(SidebarNavigationLinks.QUOTE)
        pt.navigate_to_page(SidebarNavigationLinks.TOP_STOCKS)
        pt.navigate_to_page(SidebarNavigationLinks.HEAT_MAP)
        pt.navigate_to_page(SidebarNavigationLinks.NEWS)
        pt.navigate_to_page(SidebarNavigationLinks.CHART)
        pt.navigate_to_page(SidebarNavigationLinks.BROKER)

        pl.logout()
        pl.driver.close()

    def test_get_market_info(self):
        pl = PageAAALogin(**self.driver_properties)
        pl.login()

        pt = PageAAATradingDeskMarket(**self.driver_properties)
        obj = pt.get_instrument_market_info('APX')
        pl.verify.common.assert_that(obj.symbol, equal_to('APX'))
        pl.logout()
        pl.driver.close()

    def test_get_portfolio(self):
        pl = PageAAALogin(**self.driver_properties)
        pl.login()

        pt = PageAAATradingDeskPortfolio(**self.driver_properties)
        data = pt.get_portfolio_information()
        pl.verify.common.assert_that(len(data), greater_than_or_equal_to(0))
        pl.logout()
        pl.driver.close()

    def test_get_orders(self):
        pl = PageAAALogin(**self.driver_properties)
        pl.login()

        pt = PageAAATradingDeskOrders(**self.driver_properties)
        data = pt.get_orders()
        pl.verify.common.assert_that(len(data), greater_than_or_equal_to(0))
        pl.logout()
        pl.driver.close()

    def test_get_account_info(self):
        pl = PageAAALogin(**self.driver_properties)
        pl.login()

        pt = PageAAATradingDeskAccount(**self.driver_properties)
        data = pt.get_account_information()
        data.sanitize(remove_characters=CLEAN_CHARS)

        pl.verify.common.assert_that(data.cash_balance, greater_than_or_equal_to(0))
        pl.logout()
        pl.driver.close()

    @unittest.skipIf(ENV != Environment.DEV.value, "Skipping tests for non-development environment.")
    def test_create_order(self):
        pl = PageAAALogin(**self.driver_properties)
        pl.login()

        order_dto = ModelOrderAAA(
            stock_name='APX',
            transaction='BUY',
            order_type='LIMIT',
            quantity=1000,
            price=1.2,
            good_until='GTC',
            condition_field=ConditionsOrderFieldAAA.LAST_PRICE.value,
            condition_price=1.2,
            condition_trigger=ConditionsOrderTriggerAAA.GREATER_THAN_OR_EQUAL_TO.value,
            condition_expiry_date='12/22/2024'
        )
        pt = PageAAATradingDeskOrders(**self.driver_properties)
        pt.create_order(order_dto)
        pl.logout()
        pl.driver.close()
