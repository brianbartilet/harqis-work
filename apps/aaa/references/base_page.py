from core.web.browser.fixtures.base_page import *
from core.utilities.data.qlist import QList

from .constants.links import SidebarNavigationLinks, AccountWidgetLinks


class BasePageAAAEquities(BaseFixturePageObject):

    def __init__(self, driver, **kwargs):
        super().__init__(driver, **kwargs)

    @property
    def sidebar_navigation_links(self):
        return self.driver.find_elements(By.XPATH, "//li[@data-ember-action]//a")

    @property
    def button_logout(self):
        return self.driver.find_element(By.XPATH, "//a[contains(@class, 'cursor-pointer') "
                                                  "and @data-hint='Log Out']")

    @property
    def container_widget_account_controls(self):
        xpath = "//div[@data-id='inner-widget']//div[contains(@class, 'wdgttl-tab-item ')]"
        return self.driver.find_elements(By.XPATH, xpath)

    @property
    def modal_popup_links(self):
        return self.driver.find_elements(By.XPATH, "//div[contains(@id, 'popupId')]//a")

    def get_table_text_value(self, key):
        pass

    def get_table_text_indexed_column_value(self, key, index=2):
        pass

    def wait_page_to_load(self, *args):
        super().wait_page_to_load(*args)

    def did_page_load(self, *args):
        pass

    def login(self, *args):
        pass

    def navigate_to_page(self, module_name: SidebarNavigationLinks):
        link = QList(self.sidebar_navigation_links).where(lambda x: x.text == module_name.value).first()
        link.click()
        self.wait_page_to_load()

    def navigate_to_account_widget(self, widget_link: AccountWidgetLinks):
        self.wait_page_to_load()
        link = QList(self.container_widget_account_controls).where(lambda x: widget_link.value == x.text).first()
        link.click()
        self.wait_page_to_load()

    def logout(self):
        self.button_logout.click()
