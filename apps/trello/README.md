# Trello

## Description

- [Trello](https://trello.com/) is a web-based Kanban board application (Atlassian).
- REST API documentation: [Trello REST API](https://developer.atlassian.com/cloud/trello/rest/api-group-actions/).
- Intended to organize and manage tasks from various HARQIS data sources into Trello boards.
- Currently **references only** — API service implementations are not built out.

## Supported Automations

- [X] webservices
- [ ] browser
- [ ] desktop
- [ ] mobile
- [ ] internet of things

## Directory Structure

```
apps/trello/
├── references/
│   └── __init__.py             # Empty — no implementation yet
└── tests/
    └── __init__.py
```

## Status

This app contains only the directory scaffolding. No base service, API services, or DTOs are implemented.

## Configuration (`apps_config.yaml`)

When implemented, the config section should look like:

```yaml
TRELLO:
  app_id: 'trello'
  client: 'rest'
  parameters:
    base_url: 'https://api.trello.com/1/'
    response_encoding: 'utf-8'
    verify: True
    timeout: 60
  app_data:
    api_key: ${TRELLO_API_KEY}
    token: ${TRELLO_TOKEN}
  return_data_only: True
```

## Notes

- Trello uses API Key + Token authentication (OAuth 1.0a).
- Generate credentials at: `https://trello.com/app-key`
- No workflow tasks consume this app.
