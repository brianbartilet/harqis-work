import os
from work.apps.apps_config import CONFIG_MANAGER

from core.web.browser.core.config.web_driver import AppConfigWebDriver

APP_NAME = os.path.basename(os.path.dirname(os.path.abspath(__file__)))
CONFIG_MANAGER.load(APP_NAME)

# Initialize the application configuration for a web driver using settings from the loaded configuration.
CONFIG = CONFIG_MANAGER.get(AppConfigWebDriver, 'aaa_headless')