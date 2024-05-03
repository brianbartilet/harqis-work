from work.apps.aaa.references.base_page import *
from work.apps.aaa.references.models.orders import ModelCreateOrderAAA, ConditionsOrderFieldAAA
from work.apps.aaa.references.constants.links import SidebarNavigationLinks, AccountWidgetLinks
from work.apps.aaa.references.constants.strings import APPEND_NORMAL_LOTS, APPEND_ODD_LOTS

from work.business.trading.models.order import Order
from core.utilities.data.qlist import QList


class PageAAATradingDeskOrders(BasePageAAAEquities):

    #  region New Order
    @property
    def container_new_order(self):
        return self.driver.find_element(By.XPATH, "//div[@container-id='orderTicket']")

    @property
    def button_toggle_order(self):
        return self.driver.find_element(By.XPATH, "//div[@container-id='orderTicket']"
                                                  "//label[contains(@for, 'orderSideToggleSwitch')]")

    @property
    def input_stock_search(self):
        return self.driver.find_element(By.XPATH, "//div[@container-id='orderTicket']"
                                                  "//input[contains(@id, 'searchField')]")

    @property
    def input_stock_search_top_result(self):
        return self.driver.find_element(By.XPATH, "//div[@container-id='orderTicket']"
                                                  "//div[@class='layout-container search-row full-width "
                                                  "search-row-hover']")

    @property
    def tab_order(self):
        return self.driver.find_element(By.XPATH, "//div[@container-id='orderTicket']//a[text()='General']")

    @property
    def tab_order_conditional(self):
        return self.driver.find_element(By.XPATH, "//div[@container-id='orderTicket']"
                                                  "//a[text()='Conditional Orders']")

    #  region  General
    @property
    def dropdown_order_type(self):
        return self.driver.find_element(By.XPATH, "//div[@container-id='orderTicket']"
                                                  "//form//button[@class='btn btn-dropdown h-left btn-default "
                                                  "dropdown-solid-back-color']")

    @property
    def dropdown_good_till(self):
        return self.driver.find_element(By.XPATH, "//div[@container-id='orderTicket']//form"
                                                  "//button[@class='btn btn-dropdown h-left btn-default "
                                                  "btn-order-tif dropdown-solid-back-color']")

    @property
    def input_quantity(self):
        return self.driver.find_element(By.XPATH, "//div[@container-id='orderTicket']//form"
                                                  "//input[contains(@id, 'qtyField')]")

    @property
    def input_price(self):
        return self.driver.find_element(By.XPATH, "//div[@container-id='orderTicket']//form"
                                                  "//input[contains(@id, 'orderPriceId')]")

    @property
    def button_submit_order(self):
        return self.driver.find_element(By.XPATH, "//div[@container-id='orderTicket']//button[@type='submit']")

    #  endregion

    #  region Conditional

    @property
    def dropdown_conditional_field(self):
        return self.driver.find_element(By.XPATH, "//div[@container-id='orderTicket']//form"
                                                  "//button[contains(.,'None') and @class='btn btn-dropdown "
                                                  "h-left btn-default dropdown-solid-back-color']")

    @property
    def dropdown_conditional_trigger(self):
        return self.driver.find_element(By.XPATH, "//div[@container-id='orderTicket']//form"
                                                  "//button[contains(.,'Greater') and @class='btn btn-dropdown "
                                                  "h-left btn-default dropdown-solid-back-color']")

    @property
    def input_conditional_price(self):
        return self.driver.find_element(By.XPATH, "//div[@container-id='orderTicket']//form"
                                                  "//input[@id='conditionPriceId']")

    @property
    def input_conditional_expiry_date(self):
        return self.driver.find_element(By.XPATH, "//div[@container-id='orderTicket']//form"
                                                  "//input[@class='ember-view ember-text-field "
                                                  "search-query form-control']")

    @property
    def div_invalid_order(self):
        return self.driver.find_elements(By.XPATH, "//div[@class='message-box-frame messege-box-inner "
                                                   "message-box-border' and contains(., 'Invalid Order')]")
    #  endregion

    #  region Confirm Order

    @property
    def button_confirm_order(self):
        return self.driver.find_element(By.XPATH, "//div[@container-id='orderConfirmation']"
                                                  "//button[@data-id='orderConfirmationBtn']")

    @property
    def div_order_values(self):
        return self.driver.find_elements(By.XPATH, "//div[@id='detail-order-execute']"
                                                   "//div[@class='font-m fore-color bold']")

    #  endregion

    #  endregion

    @property
    def container_rows_orders(self):
        return self.driver.find_element(By.XPATH, "//div[@container-id='orderList']"
                                                  "//div[@class='ember-table-table-scrollable-wrapper']")

    def select_year(self, year: str):
        xpath = "//span[contains(@class, 'year') and text()={0}]".format(year)
        self.driver.find_element(By.XPATH, xpath).click()

    def select_month(self, month: str):
        xpath = "//span[contains(@class, 'month')]"
        months = self.driver.find_elements(By.XPATH, xpath)
        index = int(month)
        months[index - 1].click()

    def select_day(self, day: str):
        #  cannot select date today
        index = int(day)
        xpath = "//td[@class='day' and text()={0}]".format(index)
        day = self.driver.find_element(By.XPATH, xpath)
        day.click()

    def set_date_picker(self, date_mm_dd_yyyy: str):
        self.input_conditional_expiry_date.click()
        date = date_mm_dd_yyyy.split('/')
        mm = date[0]
        dd = date[1]
        yyyy = date[2]

        xpath = "//th[@class='datepicker-switch']"
        date_picker = self.driver.find_elements(By.XPATH, xpath)
        self.wait_page_to_load()
        date_picker[0].click()
        self.wait_page_to_load()
        date_picker[1].click()

        self.select_year(yyyy)
        self.select_month(mm)
        self.select_day(dd)

    def create_order(self, order_dto: ModelCreateOrderAAA, lot_type=APPEND_NORMAL_LOTS):
        self.navigate_to_page(SidebarNavigationLinks.TRADE)
        self.wait_page_to_load()
        self.driver.wait_for_element_to_be_visible(self.button_toggle_order)

        if order_dto.transaction == Order.SELL.value:
            self.button_toggle_order.click()

        self.tab_order.click()

        self.driver.wait_for_element_to_be_visible(self.input_stock_search)
        self.input_stock_search.clear()
        self.input_stock_search.send_keys('{0}{1}'.format(order_dto.stock_name, lot_type))
        self.input_stock_search_top_result.click()
        self.tab_order.click()

        self.dropdown_order_type.click()
        self.wait_page_to_load()
        QList(self.modal_popup_links)\
            .first(lambda x: str(x.text).lower() == order_dto.order_type.lower())\
            .click()

        self.dropdown_good_till.click()
        self.wait_page_to_load()
        QList(self.modal_popup_links)\
            .first(lambda x: x.text.lower() == str(order_dto.good_until).lower())\
            .click()

        self.input_price.clear()
        self.input_price.send_keys(Keys.CONTROL, 'a')
        self.input_price.send_keys(Keys.BACKSPACE)
        self.input_price.send_keys('{0}'.format(order_dto.price))

        self.input_quantity.clear()

        self.input_quantity.send_keys(Keys.CONTROL, 'a')
        self.input_quantity.send_keys(Keys.BACKSPACE)
        self.input_quantity.send_keys('{0}'.format(order_dto.quantity))

        if order_dto.condition_field is not ConditionsOrderFieldAAA.NONE.value:
            self.tab_order_conditional.click()

            self.dropdown_conditional_field.click()
            QList(self.modal_popup_links) \
                .first(lambda x: str(x.text).lower() == order_dto.condition_field.lower()) \
                .click()

            self.dropdown_conditional_trigger.click()
            QList(self.modal_popup_links) \
                .first(lambda x: str(x.text).lower() == order_dto.condition_trigger.lower()) \
                .click()

            self.driver.wait_for_element_to_be_visible(self.input_conditional_price)
            self.input_conditional_price.clear()
            self.input_conditional_price.send_keys(Keys.CONTROL, 'a')
            self.input_conditional_price.send_keys(Keys.BACKSPACE)
            self.input_conditional_price.send_keys('{0}'.format(order_dto.condition_price))

            if order_dto.condition_expiry_date is not None:
                self.input_conditional_expiry_date.clear()
                self.wait_page_to_load()
                self.set_date_picker(order_dto.condition_expiry_date)

        self.wait_page_to_load()
        self.tab_order.click()

        values = self.div_order_values
        order_dto.order_value = float(values[0].text.replace(',', ''))
        order_dto.total_fees = float(values[1].text.replace(',', ''))
        order_dto.net_value = float(values[2].text.replace(',', ''))

        if self.app_data['enable_submit']:
            self.button_submit_order.click()

            if len(self.div_invalid_order) > 0:
                self.button_submit_order.send_keys(Keys.ESCAPE)
            try:
                self.wait_page_to_load()
                self.button_confirm_order.click()
                order_dto.created = True
            except WebDriverError.NoSuchElementException:
                self.log.warning("Order was not created.")

        return order_dto

    def get_orders(self):
        container_table_left = ".//div[contains(@id, 'ember') and contains(@class, 'ember-view lazy-list-container " \
                               "ember-table-table-block ember-table-left-table-block')]"
        container_table_right = ".//div[contains(@id, 'ember') and contains(@class, 'ember-view lazy-list-container " \
                                "ember-table-table-block ember-table-right-table-block')]"
        self.navigate_to_page(SidebarNavigationLinks.TRADE)
        self.navigate_to_account_widget(AccountWidgetLinks.ORDER_LIST)
        self.wait_page_to_load(5)

        current_orders = []

        filter_mapping = {}
        last_keys_size = 0
        while True:
            self.wait_page_to_load()
            stock_basic = self.container_rows_orders.find_element(By.XPATH, container_table_left)
            filtered_basic = (
                QList(stock_basic.find_elements(By.XPATH, ".//div[contains(@class, 'panel-table-row')]"))
                .where(lambda x: x.text != ''))

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
                row_i = filter_mapping[key]
                span = row_i.find_elements(By.XPATH, ".//span")
                self.driver.scroll_to_element(row_i)
                self.driver.high_light_element(row_i)

                stock_name = str(span[2].text)\
                    .replace(APPEND_NORMAL_LOTS, '')\
                    .replace(APPEND_ODD_LOTS, '')

                stock_detailed = self.container_rows_orders.find_element(By.XPATH, container_table_right)
                values = []
                filtered_detailed = (QList(stock_detailed.find_elements(
                    By.XPATH, ".//div[contains(@class, 'panel-table-row')]"))
                    .where(lambda x: x.text != '').to_list())

                for j, row_j in enumerate(filtered_detailed):
                    if i == j:
                        for element in row_j.find_elements(By.XPATH, ".//span"):
                            self.driver.scroll_to_element(element)
                            self.driver.high_light_element(element)

                            values.append(element.text)
                        break
                    else:
                        continue
                values.insert(0, stock_name)

                headers = ['stock_name', 'id', 'status', 'transaction', 'quantity', 'price', 'exchange',
                           'filled_quantity', 'pending_quantity', 'average_price', 'order_value', 'net_value',
                           'order_type', 'order_date', 'condition_expiry', 'good_until', 'condition',
                           'condition_expiry', 'condition_order_id']

                data = ModelCreateOrderAAA(**dict(zip(headers, values)))
                current_orders.append(data)

        return current_orders
