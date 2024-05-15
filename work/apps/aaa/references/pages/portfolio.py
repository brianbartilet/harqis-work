from work.apps.aaa.references.base_page import *
from work.apps.aaa.references.models.portfolio import ModelPortfolioItemAAA
from work.apps.aaa.references.constants.strings import *

CLEAN_CHARS = ['%', '(', ')', ',']


class PageAAATradingDeskPortfolio(BasePageAAAEquities):

    @property
    def container_rows_portfolio(self):
        return self.driver.find_element(By.XPATH, "//div[@container-id='portfolio']"
                                                  "//div[@class='ember-table-table-scrollable-wrapper']")

    def get_portfolio_information(self):
        container_table_left = ".//div[contains(@id, 'ember') and contains(@class, 'ember-view lazy-list-container " \
                               "ember-table-table-block ember-table-left-table-block')]"
        container_table_right = ".//div[contains(@id, 'ember') and contains(@class, 'ember-view lazy-list-container " \
                                "ember-table-table-block ember-table-right-table-block')]"
        self.navigate_to_page(SidebarNavigationLinks.TRADE)
        self.navigate_to_account_widget(AccountWidgetLinks.PORTFOLIO)

        portfolio = []
        self.driver.wait_page_to_load()

        filter_mapping = {}
        last_keys_size = 0
        while True:
            self.driver.wait_page_to_load()
            stock_basic = self.container_rows_portfolio.find_element(By.XPATH, container_table_left)
            filtered_basic = QList(stock_basic.find_elements(By.XPATH, ".//div[contains(@class, 'panel-table-row')]")) \
                .where(lambda x: x.text != '')

            for item in filtered_basic:
                filter_mapping[item.text] = item

            cur_size = len(filter_mapping.keys())

            last = filtered_basic[-1]
            self.driver.scroll_to_element(last)

            # check if size of keys does not change exit
            if cur_size == last_keys_size:
                break
            else:
                last_keys_size = cur_size

        for i, key in enumerate(filter_mapping.keys()):
            span = filter_mapping[key].find_elements(By.XPATH, ".//span")
            stock_name = str(span[2].text) \
                .replace(APPEND_NORMAL_LOTS, '') \
                .replace(APPEND_ODD_LOTS, '')
            stock_description = span[3].text

            stock_detailed = self.container_rows_portfolio.find_element(By.XPATH, container_table_right)
            values = []
            filtered_detailed = (QList(stock_detailed
                                      .find_elements(By.XPATH, ".//div[contains(@class, 'panel-table-row')]"))
                                 .where(lambda x: x.text != ''))
            for j, row_j in enumerate(list(filtered_detailed)):
                self.driver.scroll_to_element(row_j)
                if i == j:
                    for element in row_j.find_elements(By.XPATH, ".//span"):
                        self.driver.scroll_to_element(element)
                        values.append(element.text)
                    break
                else:
                    continue
            values.insert(0, stock_name)
            values.insert(1, stock_description)

            headers = ['symbol', 'description', 'id', 'quantity', 'sell_pending', 'buy_pending', 'available_quantity',
                       'market_price', 'average_cost', 'cost_value', 'market_value', 'gain_loss_value',
                       'gain_loss_percentage', 'portfolio_percentage', 'exchange']

            portfolio.append(ModelPortfolioItemAAA(**dict(zip(headers, values))))

        return portfolio
