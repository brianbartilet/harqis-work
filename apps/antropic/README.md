# Anthropic (Claude API)

## Description

- [Anthropic Claude API](https://docs.anthropic.com/en/api/) integration using the native Anthropic Python SDK.
- Supports synchronous and asynchronous message sending, token counting, and exponential backoff retry logic.
- Also integrates with the **Files API** (beta) and **Skills API** (beta) for advanced Claude capabilities.
- The directory is named `antropic` (legacy typo) but the config key is `ANTHROPIC`.

## Supported Automations

- [X] webservices
- [ ] browser
- [ ] desktop
- [ ] mobile
- [ ] internet of things

## Directory Structure

```
apps/antropic/
├── config.py                   # APP_NAME = 'ANTHROPIC'
├── references/
│   ├── dto/
│   │   ├── file.py             # File upload response DTO
│   │   └── skill.py            # Skill definition DTO
│   └── web/
│       ├── base_api_service.py # BaseApiServiceAnthropic — SDK wrapper with backoff
│       └── api/
│           ├── files.py        # ApiServiceAnthropicFiles
│           └── skills.py       # ApiServiceAnthropicSkills
└── tests/
```

## Base Service

`BaseApiServiceAnthropic` wraps the Anthropic SDK client and provides:

| Method | Description |
|--------|-------------|
| `send_message(prompt, model, max_tokens)` | Synchronous message to Claude |
| `send_message_async(prompt, model, max_tokens)` | Async message to Claude |
| `count_tokens(prompt, model)` | Count tokens before sending (cost estimation) |
| `_with_backoff(fn, *args)` | Run sync function with exponential backoff |
| `_with_backoff_async(fn, *args)` | Run async function with exponential backoff |
| `_httpx_with_backoff(fn, *args)` | Run httpx request with exponential backoff |

## API Services

### `ApiServiceAnthropicFiles` (beta: `files-api-2025-04-14`)

| Method | Description |
|--------|-------------|
| `upload_file(path, media_type)` | Upload a file to Anthropic's Files API |
| `list_files()` | List all uploaded files |
| `retrieve_file_metadata(file_id)` | Get metadata for a specific file |
| `delete_file(file_id)` | Delete a file by ID |

### `ApiServiceAnthropicSkills` (beta: `skills-2025-10-02`)

| Method | Description |
|--------|-------------|
| `create_skill(name, description, instructions)` | Package and upload a new skill as a ZIP |
| `list_skills()` | List all skills (custom and Anthropic-provided) |
| `retrieve_skill(skill_id)` | Get skill details by ID |

Skills are uploaded as in-memory ZIP archives containing a `SKILL.md` instructions file.

## Configuration (`apps_config.yaml`)

```yaml
ANTHROPIC:
  app_id: 'anthropic'
  app_data:
    api_key: ${ANTHROPIC_API_KEY}
    default_model: 'claude-sonnet-4-6'
    max_tokens: 8096
```

`.env/apps.env`:

```env
ANTHROPIC_API_KEY=    # console.anthropic.com → API Keys
```

## How to Use

```python
from apps.antropic.references.web.base_api_service import BaseApiServiceAnthropic
from apps.antropic.config import CONFIG

svc = BaseApiServiceAnthropic(CONFIG)

# Send a message
response = svc.send_message(
    prompt='Summarize the following logs: ...',
    model='claude-sonnet-4-6',
    max_tokens=1024
)
print(response.content[0].text)
```

```python
from apps.antropic.references.web.api.files import ApiServiceAnthropicFiles
from apps.antropic.config import CONFIG

files = ApiServiceAnthropicFiles(CONFIG)
uploaded = files.upload_file('/path/to/document.pdf', 'application/pdf')
print(uploaded.id)   # Use this file_id in Claude messages
```

## Notes

- Directory is named `antropic` (legacy typo) — do not rename without updating all imports.
- The Files API and Skills API are in **beta** and require specific `anthropic-beta` headers.
- Exponential backoff handles rate limit (`429`) and server error (`5xx`) responses automatically.
- Prefer this integration over `apps/open_ai` for new AI-driven workflow tasks.
