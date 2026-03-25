# [App Name]

## Description

- Brief description of what this app integrates with and what it does.
- Link to the external service's API documentation.
- Note the authentication method (Bearer token, OAuth, username/password, etc.).

## Supported Automations

- [ ] webservices — REST API calls
- [ ] browser — Selenium page automation
- [ ] desktop — Local Windows automation
- [ ] mobile — Android/iOS automation
- [ ] internet of things — MQTT / hardware integration

## Directory Structure

```
apps/<app_name>/
├── config.py                   # Loads app config section from apps_config.yaml
├── references/
│   ├── base_api_service.py     # Extends BaseFixtureServiceRest (or BaseFixturePageObject)
│   ├── dto/                    # Dataclass-based data transfer objects
│   ├── models/                 # Data models (often extend DTOs)
│   ├── constants/              # Enums and static values
│   └── web/api/                # Concrete API service implementations
└── tests/
    └── test_<feature>.py       # Live integration tests (no mocking)
```

## Configuration

Add a section in `apps_config.yaml`:

```yaml
APP_NAME:
  app_id: '<app_name>'
  client: 'rest'
  parameters:
    base_url: 'https://api.example.com/v1/'
    response_encoding: 'utf-8'
    verify: True
    timeout: 60
    stream: True
  app_data:
    api_key: ${APP_API_KEY}
  return_data_only: True
```

Add required env vars to `.env/apps.env`:

```env
APP_API_KEY=your_key_here
```

## `config.py` Pattern

```python
from core.utilities.loaders import load_config
from core.web.services.fixtures.rest import AppConfigWSClient

APP_NAME = 'APP_NAME'
CONFIG = AppConfigWSClient(**load_config[APP_NAME])
```

## Base Service Pattern

```python
from core.web.services.fixtures.rest import BaseFixtureServiceRest
from apps.<app_name>.config import CONFIG

class BaseApiServiceAppName(BaseFixtureServiceRest):
    def __init__(self, **kwargs):
        super().__init__(CONFIG, **kwargs)
        self.client.session.headers.update({
            'Authorization': f'Bearer {CONFIG.app_data["api_key"]}'
        })
```

## API Service Pattern

```python
from core.web.services.fixtures.rest import deserialized
from apps.<app_name>.references.base_api_service import BaseApiServiceAppName
from apps.<app_name>.references.dto.example import DtoExample

class ApiServiceAppNameFeature(BaseApiServiceAppName):
    @deserialized(DtoExample)
    def get_something(self, param: str) -> DtoExample:
        return (self.client
                .get('endpoint/')
                .query_param('key', param)
                .execute())
```

## Tests

Tests use pytest with PyHamcrest assertions and require live credentials.

```python
import pytest
from hamcrest import assert_that, not_none
from apps.<app_name>.references.web.api.feature import ApiServiceAppNameFeature

@pytest.fixture
def service():
    return ApiServiceAppNameFeature()

def test_get_something(service):
    result = service.get_something('param')
    assert_that(result, not_none())
```

```sh
pytest apps/<app_name>/tests/
pytest apps/<app_name>/tests/ -m smoke
```

## How to Use

1. Add the config section to `apps_config.yaml`.
2. Set required env vars in `.env/apps.env`.
3. Import and use the service class directly or inside a workflow task.

## Notes

- All tests are live integration tests — no mocking.
- Credentials must be valid for tests to pass.
