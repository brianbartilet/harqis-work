import os
from core.config.loader import ConfigLoaderService
from core.web.services.core.config.webservice import AppConfigWSClient
from core.config.env_variables import ENV_APP_CONFIG_FILE

load_config = ConfigLoaderService(file_name=ENV_APP_CONFIG_FILE).config

# Directory is 'antropic' (legacy typo), config key is 'ANTHROPIC'
APP_NAME = 'ANTHROPIC'

CONFIG = AppConfigWSClient(**load_config[APP_NAME])
