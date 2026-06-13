from apps.config_loader import app_name_for, get_section

APP_NAME = app_name_for(__file__)
CONFIG = get_section(__file__)
