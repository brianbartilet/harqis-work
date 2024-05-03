import os
from core.config.loader import ConfigLoaderService
from core.web.browser.core.config.web_driver import AppConfigWebDriver

from core.config.env_variables import ENV


# Load configurations from a specified YAML file.
load_config = ConfigLoaderService(file_name='sample_config.yaml').config


