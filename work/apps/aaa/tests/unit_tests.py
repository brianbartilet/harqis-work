import unittest

from core.web.browser.fixtures.web_driver import BaseFixtureWebDriver
from work.apps.aaa.config import load
from work.apps.aaa.references.pages import *
from work.apps.aaa.references.constants.links import SidebarNavigationLinks
from work.apps.aaa.references.models.orders import *
from work.apps.aaa.references.models.orders import ModelOrderAAA

from hamcrest import equal_to, greater_than_or_equal_to

from core.config.env_variables import Environment, ENV


class TestAAAEquities(unittest.TestCase):

    def setUp(self):
        self.config = load('aaa_headless')
        self.driver = BaseFixtureWebDriver(self.config).driver

    def test_login(self):
        pl = PageAAALogin(self.driver)
        pl.login()
        pl.driver.close()

    def test_navigate(self):
        pl = PageAAALogin(self.driver)
        pl.login()

        pt = PageAAATradingDeskMarket(self.driver)
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
        pl = PageAAALogin(self.driver)
        pl.login()

        pt = PageAAATradingDeskMarket(self.driver)
        obj = pt.get_instrument_market_info('APX')
        pl.verify.common.assert_that(obj.symbol, equal_to('APX'))
        pl.logout()
        pl.driver.close()

    def test_get_portfolio(self):
        pl = PageAAALogin(self.driver)
        pl.login()

        pt = PageAAATradingDeskPortfolio(self.driver)
        data = pt.get_portfolio_information()
        pl.verify.common.assert_that(len(data), greater_than_or_equal_to(0))
        pl.logout()
        pl.driver.close()

    def test_get_orders(self):
        pl = PageAAALogin(self.driver)
        pl.login()

        pt = PageAAATradingDeskOrders(self.driver)
        data = pt.get_orders()
        pl.verify.common.assert_that(len(data), greater_than_or_equal_to(0))
        pl.logout()
        pl.driver.close()

    def test_get_account_info(self):
        pl = PageAAALogin(self.driver)
        pl.login()

        pt = PageAAATradingDeskAccount(self.driver)
        data = pt.get_account_information()
        pl.verify.common.assert_that(data.cash_balance, greater_than_or_equal_to(0))
        pl.logout()
        pl.driver.close()

    @unittest.skipIf(ENV != Environment.DEV.value, "Skipping tests for non-development environment.")
    def test_create_order(self):
        pl = PageAAALogin(self.driver)
        pl.login()

        order_dto = ModelOrderAAA(
            stock_name='APX',
            transaction=Order.BUY,
            order_type=OrderType.LIMIT,
            quantity=1000,
            price=1.2,
            good_until=OrderValidUntil.GTC,
            condition_field=ConditionsOrderFieldAAA.LAST_PRICE,
            condition_price=1.2,
            condition_trigger=ConditionsOrderTriggerAAA.GREATER_THAN_OR_EQUAL_TO,
            condition_expiry_date='12/22/2020'
        )
        pt = PageAAATradingDeskOrders(self.driver)
        data = pt.create_order(order_dto)
        pl.verify.common.assert_that(data, equal_to(True))
        pl.logout()
        pl.driver.close()
