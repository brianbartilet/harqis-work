import os
from work.apps.apps_config import CONFIG_MANAGER
from core.web.browser.core.config.web_driver import AppConfigWebDriver

# Get the application name from the directory of the current file
APP_NAME = os.path.basename(os.path.dirname(os.path.abspath(__file__)))


def load(config_id: str):
    """
    Load and retrieve the web driver configuration for the specified application.

    This function first uses the global CONFIG_MANAGER to load configurations specific
    to the application determined by the APP_NAME. It then retrieves the web driver
    configuration using the provided configuration identifier.

    Args:
        config_id: The identifier for the specific configuration to be retrieved.

    Returns:
        AppConfigWebDriver: An instance of the AppConfigWebDriver containing the
                            configuration details for the web driver.
    """
    CONFIG_MANAGER.load(APP_NAME)
    return CONFIG_MANAGER.get(AppConfigWebDriver, config_id)
