from core.config.env_variables import ENV_APP_CONFIG, ENV_APP_CONFIG_FILE
from core.config.loader import ConfigLoaderService
from core.config.app_config import AppConfigManager

# ENV_APP_CONFIG and ENV_APP_CONFIG_FILE:
# These variables are imported from core.config.env_variables module. They are expected to contain
# environment-specific settings:
#   ENV_APP_CONFIG - The base path to the configuration directory.
#   ENV_APP_CONFIG_FILE - The name of the YAML file containing the application's configuration.

# ConfigLoaderService:
# This class is responsible for loading configuration files. It is initialized here with parameters
# that specify the name and location of the configuration file. The ConfigLoaderService is designed
# to parse the YAML file specified by `ENV_APP_CONFIG_FILE` located in the directory specified by
# `ENV_APP_CONFIG`.

CONFIG_SERVICE = ConfigLoaderService(file_name=ENV_APP_CONFIG_FILE, base_path=ENV_APP_CONFIG)
"""
CONFIG_SERVICE is an instance of ConfigLoaderService, initialized with environment-specific
file name and base path. This service loads the configuration data from a YAML file located
at the path specified by ENV_APP_CONFIG and named ENV_APP_CONFIG_FILE.
"""

# AppConfigManager:
# This class is designed to manage the application configuration. It uses an instance of
# ConfigLoaderService to load and handle the configuration data effectively.

CONFIG_MANAGER = AppConfigManager(CONFIG_SERVICE)
"""
CONFIG_MANAGER is an instance of AppConfigManager. It is responsible for managing the application
configuration using the CONFIG_SERVICE. This manager facilitates access to configuration data,
allowing for structured and centralized configuration management within the application.
"""

# Usage:
# This script sets up the configuration management for the application by initializing the necessary
# services and managers with appropriate environment settings. It is typically used at the startup
# of the application to ensure all components have access to the configured settings.
