from work.apps.aaa.references.base_page import BasePageAAAEquities, By
from work.apps.aaa.references.constants.links import SidebarNavigationLinks
from work.apps.aaa.references.constants.strings import APPEND_NORMAL_LOTS
from work.apps.aaa.references.models.stock import ModelStockAAA


class PageAAATradingDeskMarket(BasePageAAAEquities):

    @property
    def input_filter_stock(self):
        return self.driver.find_element(By.XPATH,
                                        "//input[contains(@id, 'ember') "
                                        "and contains(@class, 'search-query search-ctrl')]")

    @property
    def container_table_left_market_watch(self):
        return self.driver.find_element(By.XPATH,
                                        "//div[contains(@id, 'ember') "
                                        "and contains(@class, 'ember-view lazy-list-container "
                                        "ember-table-table-block ember-table-left-table-block')]")

    @property
    def container_table_right_market_watch(self):
        return self.driver.find_element(By.XPATH,
                                        "//div[contains(@id, 'ember') "
                                        "and contains(@class, 'ember-view lazy-list-container "
                                        "ember-table-table-block ember-table-right-table-block')]")

    def get_instrument_market_info(self, stock_name: str):
        text_stock = '{0}{1}'.format(stock_name, APPEND_NORMAL_LOTS)
        self.navigate_to_page(SidebarNavigationLinks.MARKET)
        self.input_filter_stock.send_keys(text_stock)

        stock_values_container = self.container_table_right_market_watch
        stock_values = stock_values_container.find_elements(By.XPATH,
                                                            "//div[contains(@class, 'ember-table-table-row')]")
        target_stock = stock_values[5]
        values = [x.text for x in target_stock.find_elements(By.XPATH, ".//span")]
        values.insert(0, stock_name)
        values.remove('')

        headers = ['symbol', 'description', 'last_traded', 'bid_qty', 'bid', 'offer',
                   'offer_qty', 'volume', 'value', 'change', 'change_percent', 'prev_close',
                   'open', 'high', 'low', 'trades', 'wk_52_hi', 'wk_52_lo']

        return ModelStockAAA(**dict(zip(headers, values)))
