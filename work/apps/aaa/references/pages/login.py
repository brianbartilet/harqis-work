from work.apps.aaa.references.base_page import BasePageAAAEquities, Keys, By, WebDriverError


class PageAAALogin(BasePageAAAEquities):

    @property
    def textbox_username(self):
        return self.driver.find_element(By.ID, 'txtUsername')

    @property
    def textbox_password(self):
        return self.driver.find_element(By.ID, 'txtPassword')

    @property
    def button_login(self):
        return self.driver.find_element(By.ID, 'btnLogin')

    @property
    def dialog_password(self):
        return self.driver.find_elements(By.ID, 'message-box')

    @property
    def button_dialog_password_ok(self):
        return self.driver.find_element(By.XPATH, "//div[@id='message-box']//button[text()='OK']")

    def login(self, **kwargs):
        username = kwargs.get('username', self.app_data['username'])
        password = kwargs.get('password', self.app_data['password'])

        self.wait_page_to_load()
        self.textbox_username.clear()
        self.textbox_username.send_keys(Keys.CONTROL + 'A' + Keys.BACKSPACE)
        self.textbox_username.send_keys(username)
        self.wait_page_to_load()
        self.textbox_password.clear()
        self.textbox_password.send_keys(Keys.CONTROL + 'A' + Keys.BACKSPACE)
        self.textbox_password.send_keys(password)
        self.wait_page_to_load()
        self.button_login.click()
        self.wait_page_to_load()

        try:
            if self.button_dialog_password_ok.is_displayed():
                self.button_dialog_password_ok.click()
        except WebDriverError.NoSuchElementException:
            self.log.error('Password dialog not found')

        self.wait_page_to_load()
