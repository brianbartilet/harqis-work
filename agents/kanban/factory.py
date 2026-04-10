"""
Provider factory — create a KanbanProvider from config dict.

Config example (from env or YAML):
    provider: trello
    api_key: ${TRELLO_API_KEY}
    token:   ${TRELLO_API_TOKEN}
"""

from agents.kanban.interface import KanbanProvider


def create_provider(config: dict) -> KanbanProvider:
    """
    Instantiate a KanbanProvider from a config dictionary.

    Args:
        config: Must contain "provider" key.
                Remaining keys are passed as kwargs to the provider class.
    """
    from agents.kanban.adapters.trello import TrelloProvider
    from agents.kanban.adapters.jira import JiraProvider

    providers: dict[str, type[KanbanProvider]] = {
        "trello": TrelloProvider,
        "jira": JiraProvider,
    }

    kind = config.get("provider", "trello").lower()
    cls = providers.get(kind)
    if cls is None:
        raise ValueError(
            f"Unknown provider '{kind}'. Available: {list(providers.keys())}"
        )

    kwargs = {k: v for k, v in config.items() if k != "provider"}
    return cls(**kwargs)
