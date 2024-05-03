from work.apps.aaa.references.base_page import *
from work.apps.aaa.references.constants.links import SidebarNavigationLinks, AccountWidgetLinks
from work.apps.aaa.references.models.account import ModelAccountAAA


class PageAAATradingDeskAccount(BasePageAAAEquities):

    @property
    def container_rows_account_details(self):
        return self.driver.find_element(By.XPATH, "//div[@container-id='accountSummary']")

    def get_account_information(self):

        self.navigate_to_page(SidebarNavigationLinks.TRADE)
        self.navigate_to_account_widget(AccountWidgetLinks.ACCOUNT_SUMMARY)

        account_details = []
        rows = self.container_rows_account_details\
            .find_elements(By.XPATH, ".//div[@class='layout-container pad-s-tb border-bottom']")

        for row in rows:
            span_values = row.find_elements(By.XPATH, ".//span")
            element = span_values[1]
            account_details.append(element.text)

        headers = ['cash_balance', 'available_cash', 'pending_cash', 'available_to_withdraw', 'unsettled_sales',
                   'payable_amount', 'od_limit', 'portfolio_value', 'total_portfolio_value']

        dto = ModelAccountAAA(convert_kwargs=True, clean_chars=[','], **dict(zip(headers, account_details)))

        return dto

