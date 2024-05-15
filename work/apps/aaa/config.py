import os
from work.apps.apps_config import CONFIG_MANAGER

APP_NAME = os.path.basename(os.path.dirname(os.path.abspath(__file__)))
CONFIG_MANAGER.load(APP_NAME)
