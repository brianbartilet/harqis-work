"""External-system integrations for agents/projects.

Each module is opt-in:

  - `discord` — post agent output / artifacts to Discord channels via Bot API.
                Agent picks the channel by inference; profile allowlist
                enforces what's allowed.

  - `telemetry` — emit lifecycle events (claim, start, finish, fail) to
                  Elasticsearch via the harqis-core es_logging library.
                  No-op when ES is not configured.
"""
