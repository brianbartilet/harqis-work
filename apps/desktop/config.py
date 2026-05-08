"""
This module is responsible for loading configuration settings for a specific application
from a YAML configuration file and initializing an application-specific web service client configuration.

It leverages a configuration loader to read settings and dynamically assigns these settings
based on the application's directory name. This allows for flexible configuration management
that adapts to the application's deployment environment.

Attributes:
    APP_NAME (str): The name of the application, derived from the directory name of the current file.
                    This is used to select the appropriate configuration section from the YAML file.
    CONFIG (AppConfigWSClient): A configured instance of AppConfigWSClient containing web service
                                connection settings specific to the application determined by APP_NAME.
"""
import os
from core.web.services.core.config.webservice import AppConfigWSClient

from apps.apps_config import CONFIG_MANAGER

APP_NAME = str(os.path.basename(os.path.dirname(os.path.abspath(__file__)))).upper()
CONFIG = CONFIG_MANAGER.get(APP_NAME)

