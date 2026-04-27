# apps/open_ai — OpenAI Integration

## Description

Integrates with the [OpenAI API](https://platform.openai.com/docs/api-reference) using the official `openai` Python SDK.

**Auth:** Bearer token via `OPENAI_API_KEY`.

The integration has two generations:

| Layer | Status | Location |
|---|---|---|
| **Responses API** (current) | Active | `references/web/api/responses.py` |
| **Code Interpreter** (current) | Active | `references/web/api/code_interpreter.py` |
| Assistants v2 REST fixtures | **Deprecated** | `references/services/assistants/` |

The Assistants v2 layer is preserved to avoid breaking existing `hud/` workflow tasks
(`assistant_id_desktop`, `assistant_id_reporter`). Do not use for new integrations.

---

## Supported Automations

- [x] webservices (REST via native SDK)
- [ ] browser
- [ ] desktop
- [ ] mobile
- [ ] iot

---

## Directory Structure

```
apps/open_ai/
├── __init__.py
├── config.py                         # Standard config loader — OPEN_AI key
├── mcp.py                            # MCP tool registrations
├── base_service.py                   # DEPRECATED — BaseServiceHarqisGPT
├── references/
│   ├── dto/
│   │   ├── response.py               # Responses API DTOs
│   │   └── file.py                   # File API DTOs
│   ├── web/
│   │   ├── base_api_service.py       # BaseApiServiceOpenAi (current base)
│   │   └── api/
│   │       ├── responses.py          # ApiServiceOpenAiResponses
│   │       └── code_interpreter.py   # ApiServiceOpenAiCodeInterpreter
│   ├── assistants/                   # DEPRECATED — Assistants v2 orchestration layer
│   │   └── base.py                   # BaseAssistant
│   ├── constants/                    # DEPRECATED — RunStatus, HttpHeadersGPT
│   ├── contracts/                    # DEPRECATED — IAssistant abstract interface
│   ├── models/                       # DEPRECATED — Assistant, Thread, Message, Run DTOs
│   └── services/                     # DEPRECATED — Assistants v2 CRUD services
│       ├── files.py
│       └── assistants/
│           ├── assistant.py
│           ├── threads.py
│           ├── messages.py
│           └── runs.py
└── tests/
    ├── test_responses.py             # Smoke + sanity tests for Responses API
    ├── test_code_interpreter.py      # Smoke + sanity tests for Code Interpreter
    ├── test_assistants.py            # DEPRECATED (skip)
    ├── test_base_assistant.py        # DEPRECATED (skip)
    └── test_files.py                 # DEPRECATED (skip)
```

---

## Configuration

### `apps_config.yaml`

```yaml
OPEN_AI:
  app_id: 'open_ai'
  client: 'rest'
  parameters:
    base_url: 'https://api.openai.com/v1/'
    response_encoding: 'utf-8'
    verify: True
    timeout: 120
    stream: True
  app_data:
    api_key: ${OPENAI_API_KEY}
    model: 'gpt-4.1'
    default_assistant_id: ${OPENAI_ASSISTANT_ID}
    assistant_id_desktop: ${OPENAI_ASSISTANT_DESKTOP}
    assistant_id_reporter: ${OPENAI_ASSISTANT_REPORTER}
  return_data_only: True
```

### Environment Variables (`.env/apps.env`)

```env
# OpenAI
OPENAI_API_KEY=
OPENAI_ASSISTANT_ID=
OPENAI_ASSISTANT_DESKTOP=
OPENAI_ASSISTANT_REPORTER=
```

---

## Available Services

### Current

| Class | Module | Methods |
|---|---|---|
| `ApiServiceOpenAiResponses` | `references/web/api/responses.py` | `create_response`, `get_response`, `delete_response`, `list_input_items` |
| `ApiServiceOpenAiCodeInterpreter` | `references/web/api/code_interpreter.py` | `execute_code`, `execute_code_with_files`, `parse_code_calls` (inherits all Responses methods) |

### Deprecated

| Class | Module | Status |
|---|---|---|
| `BaseServiceHarqisGPT` | `base_service.py` | Issues `DeprecationWarning` on init |
| `ApiServiceAssistants` | `references/services/assistants/assistant.py` | Kept for hud/ workflow compatibility |
| `ApiServiceThreads` | `references/services/assistants/threads.py` | Kept for hud/ workflow compatibility |
| `ApiServiceMessages` | `references/services/assistants/messages.py` | Kept for hud/ workflow compatibility |
| `ApiServiceRuns` | `references/services/assistants/runs.py` | Kept for hud/ workflow compatibility |
| `ApiServiceFiles` | `references/services/files.py` | Kept for hud/ workflow compatibility |

---

## MCP Tools

| Tool | Args | Description |
|---|---|---|
| `openai_generate` | `prompt`, `model`, `instructions`, `previous_response_id`, `temperature`, `max_output_tokens` | Generate text via the Responses API |
| `openai_get_response` | `response_id` | Retrieve a stored response by ID |
| `openai_delete_response` | `response_id` | Delete a stored response |
| `openai_execute_code` | `prompt`, `model`, `instructions`, `previous_response_id` | Run Python code via Code Interpreter |
| `openai_execute_code_with_files` | `prompt`, `file_ids`, `model`, `instructions` | Run code with uploaded files available |

---

## Responses API — Key Concepts

The Responses API (`POST /v1/responses`) is the current recommended interface.
It supersedes Chat Completions and the Assistants API for most agentic use cases.

**Multi-turn without history resending:**
```python
first = svc.create_response(input="My name is HARQIS.", store=True)
second = svc.create_response(input="What is my name?", previous_response_id=first.id)
```

**Built-in tools:**
```python
# Code Interpreter
svc.create_response(input="...", tools=[{"type": "code_interpreter", "container": {"type": "auto"}}])

# Web search
svc.create_response(input="...", tools=[{"type": "web_search_preview"}])

# File search (requires a vector store)
svc.create_response(input="...", tools=[{"type": "file_search", "vector_store_ids": ["vs_..."]}])
```

---

## Code Interpreter — Key Concepts

Code Interpreter runs sandboxed Python in an OpenAI-managed container.

```python
from apps.open_ai.config import CONFIG
from apps.open_ai.references.web.api.code_interpreter import ApiServiceOpenAiCodeInterpreter

svc = ApiServiceOpenAiCodeInterpreter(CONFIG)

# Single turn
result = svc.execute_code("Plot a sine wave and save it as a PNG.")
calls = svc.parse_code_calls(result)
for call in calls:
    print(call.code)
    for out in call.outputs:
        if out.type == "logs":
            print(out.logs)

# Multi-turn (variables persist across turns via previous_response_id)
r1 = svc.execute_code("Set x = [1, 2, 3, 4, 5].")
r2 = svc.execute_code("Print the mean of x.", previous_response_id=r1.id)
```

---

## Tests

```sh
# Responses API (live, requires OPENAI_API_KEY)
pytest apps/open_ai/tests/test_responses.py -m smoke
pytest apps/open_ai/tests/test_responses.py -m sanity

# Code Interpreter (live)
pytest apps/open_ai/tests/test_code_interpreter.py -m smoke
pytest apps/open_ai/tests/test_code_interpreter.py -m sanity
```

---

## Notes

- **Rate limits:** Responses API and Code Interpreter share the same token-per-minute limit as your OpenAI tier.
- **Storage:** `store=True` (default) keeps the response retrievable by ID. Set `store=False` for ephemeral responses.
- **Code Interpreter timeout:** Container spins up on first call; warm-up adds ~2–5 s to the first request per session.
- **File uploads for code:** Upload files via `client.files.create(file=..., purpose="assistants")` then pass the returned IDs to `execute_code_with_files`.
- **Deprecated Assistants tests:** All tests in `test_assistants.py`, `test_base_assistant.py`, and `test_files.py` are marked `@pytest.mark.skip("deprecated")`.
- **Known issue (messages.py:147):** `update_message()` in the deprecated layer uses `HttpMethod.GET` instead of `HttpMethod.POST`. Not fixed as the method is unused in active workflows.
