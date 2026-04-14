from apps.apps_config import CONFIG_MANAGER

# Directory is 'antropic' (legacy typo), config key is 'ANTHROPIC'
APP_NAME = 'ANTHROPIC'


def get_config(cfg_id: str = APP_NAME):
    """
    Return an AppConfigWSClient for the given Anthropic config key.

    Supported keys in apps_config.yaml:
        ANTHROPIC          — default Sonnet 4.6, general purpose
        ANTHROPIC_AGENT_X  — Opus 4.6, higher token budget, more retries
        ANTHROPIC_AGENT_Y  — Haiku 4.5, low-latency / low-cost tasks

    Args:
        cfg_id: apps_config.yaml section key (default 'ANTHROPIC').

    Returns:
        AppConfigWSClient instance configured for the requested key.
    """
    return CONFIG_MANAGER.get(cfg_id)


# Kept for backward compatibility — callers that import CONFIG directly
# still work without changes.
CONFIG = get_config()
