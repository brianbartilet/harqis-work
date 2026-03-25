# OpenAI

## Description

- [OpenAI API](https://platform.openai.com/docs/api-reference) integration using the native OpenAI Python SDK.
- Implements the **Assistants v2 API** — threads, messages, runs, and file uploads.
- Used in the `hud` workflow for log analysis (`get_desktop_logs`) and AI helper display (`show_ai_helper`).
- **Note:** This integration is planned for deprecation in favor of `apps/antropic` (Claude API).

## Supported Automations

- [X] webservices
- [ ] browser
- [ ] desktop
- [ ] mobile
- [ ] internet of things

## Directory Structure

```
apps/open_ai/
├── references/
│   ├── assistants/
│   │   └── base.py             # BaseServiceHarqisGPT — wraps OpenAI SDK client
│   ├── constants/
│   │   ├── http_headers.py
│   │   └── status.py           # Run status constants (completed, failed, etc.)
│   ├── contracts/
│   │   └── assistant.py        # Abstract interface for assistant services
│   ├── models/
│   │   └── assistants/
│   │       ├── assistant.py    # Assistant model
│   │       ├── common.py       # Shared model fields
│   │       ├── message.py      # Message model
│   │       ├── run.py          # Run model
│   │       └── thread.py       # Thread model
│   └── services/
│       ├── files.py            # ServiceFiles
│       └── assistants/
│           ├── assistant.py    # ServiceAssistants
│           ├── messages.py     # ServiceMessages
│           ├── runs.py         # ServiceRuns
│           └── threads.py      # ServiceThreads
└── tests/
```

## Services

### `ServiceAssistants`
| Method | Description |
|--------|-------------|
| `create_assistant()` | Create a new assistant |
| `get_assistants()` | List all assistants |
| `get_assistant(id)` | Get assistant by ID |
| `update_assistant(id, data)` | Update assistant configuration |
| `delete_assistant(id)` | Delete an assistant |
| `create_assistant_file(id, file_id)` | Attach file to assistant |
| `get_assistant_files(id)` | List files attached to assistant |
| `delete_assistant_file(id, file_id)` | Remove file from assistant |

### `ServiceThreads`
| Method | Description |
|--------|-------------|
| `create_thread()` | Create a new conversation thread |
| `get_thread(id)` | Get thread by ID |
| `update_thread(id, data)` | Update thread metadata |
| `delete_thread(id)` | Delete a thread |

### `ServiceMessages`
| Method | Description |
|--------|-------------|
| `create_message(thread_id, content)` | Add a message to a thread |
| `get_messages(thread_id)` | List messages in a thread |
| `get_message(thread_id, msg_id)` | Get a specific message |
| `update_message(thread_id, msg_id, data)` | Update a message |

### `ServiceRuns`
| Method | Description |
|--------|-------------|
| `create_run(thread_id, assistant_id)` | Start a run on a thread |
| `create_thread_and_run(assistant_id)` | Create thread + run in one call |
| `get_run(thread_id, run_id)` | Get run status |
| `get_run_steps(thread_id, run_id)` | Get step-by-step execution details |
| `update_run(thread_id, run_id, data)` | Update run metadata |
| `submit_tool_options(thread_id, run_id, data)` | Submit tool call outputs |
| `cancel_run(thread_id, run_id)` | Cancel a running run |

### `ServiceFiles`
| Method | Description |
|--------|-------------|
| `upload_file(path, purpose)` | Upload a file for use with assistants |
| `upload_files(directory, pattern)` | Upload all matching files in a directory |
| `get_files()` | List uploaded files |
| `get_file(id)` | Get file metadata |
| `get_file_content(id)` | Download file content |
| `delete_file(id)` | Delete an uploaded file |

## Configuration (`apps_config.yaml`)

```yaml
HARQIS_GPT:
  app_id: 'harqis_gpt'
  app_data:
    api_key: ${OPENAI_API_KEY}
    assistant_id: ${OPENAI_ASSISTANT_ID}
    assistant_desktop: ${OPENAI_ASSISTANT_DESKTOP}
    assistant_reporter: ${OPENAI_ASSISTANT_REPORTER}
```

`.env/apps.env`:

```env
OPENAI_API_KEY=
OPENAI_ASSISTANT_ID=        # Default assistant
OPENAI_ASSISTANT_DESKTOP=   # Desktop log analysis assistant
OPENAI_ASSISTANT_REPORTER=  # Report generation assistant
```

## How to Use

See `apps/open_ai/references/assistants/README.md` for the full Assistants workflow:

1. Upload files → `ServiceFiles.upload_files()`
2. Create thread → `ServiceThreads.create_thread()`
3. Add messages → `ServiceMessages.create_message()`
4. Create run → `ServiceRuns.create_run()`
5. Poll until complete → `ServiceRuns.get_run()`
6. Read output → `ServiceMessages.get_messages()`

## Notes

- This integration uses the native OpenAI SDK, not harqis-core's REST client.
- Planned for deprecation — prefer `apps/antropic` for new AI integrations.
- `ServiceFiles._safe_join()` validates file paths to prevent directory traversal.
- Run status constants are defined in `constants/status.py`: `completed`, `failed`, `requires_action`, `cancelled`, `expired`.
