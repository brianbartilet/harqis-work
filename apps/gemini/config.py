import os
from core.config.loader import ConfigLoaderService
from core.web.services.core.config.webservice import AppConfigWSClient
from core.config.env_variables import ENV_APP_CONFIG_FILE

load_config = ConfigLoaderService(file_name=ENV_APP_CONFIG_FILE).config
APP_NAME = str(os.path.basename(os.path.dirname(os.path.abspath(__file__)))).upper()
CONFIG = AppConfigWSClient(**load_config[APP_NAME])
