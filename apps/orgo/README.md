# Orgo Integration

REST API client for [Orgo AI](https://orgo.ai) — cloud-hosted Linux VMs controllable by AI agents.

## What is Orgo?

Orgo provides **desktop infrastructure for AI agents**. Each computer is a cloud Linux VM that an agent can control autonomously:

- Take screenshots and analyze the screen
- Click, type, drag, scroll
- Run shell commands (`bash`)
- Transfer files to/from the VM
- Stream audio and desktop events via WebSocket

This lets Claude (or any AI) use a real desktop to browse the web, run code, fill forms, or interact with any GUI application — without requiring a local machine.

---

## Setup

### 1. Get an API Key

Sign in at [orgo.ai/workspaces](https://www.orgo.ai/workspaces) and generate an API key.

### 2. Configure `.env/apps.env`

```env
ORGO_API_KEY=sk_live_...
```

### 3. apps_config.yaml (already added)

```yaml
ORGO:
  app_id: 'orgo'
  client: 'rest'
  parameters:
    base_url: 'https://www.orgo.ai/api/'
  app_data:
    api_key: ${ORGO_API_KEY}
  return_data_only: True
```

---

## API Reference

Base URL: `https://www.orgo.ai/api/`
Authentication: `Authorization: Bearer sk_live_...`

### Workspaces

Resource hierarchy: **Account → Workspaces → Computers**

| Method | Service | Description |
|--------|---------|-------------|
| `list_workspaces()` | `ApiServiceOrgoWorkspaces` | List all workspaces |
| `get_workspace(id)` | `ApiServiceOrgoWorkspaces` | Get workspace by ID |
| `create_workspace(name)` | `ApiServiceOrgoWorkspaces` | Create a new workspace |
| `delete_workspace(id)` | `ApiServiceOrgoWorkspaces` | Delete workspace + all computers |

### Computers (VMs)

| Method | Service | Description |
|--------|---------|-------------|
| `create_computer(workspace_id, name, ...)` | `ApiServiceOrgoComputers` | Provision a new VM |
| `get_computer(id)` | `ApiServiceOrgoComputers` | Get status + details |
| `delete_computer(id)` | `ApiServiceOrgoComputers` | Terminate a VM |
| `start(id)` | `ApiServiceOrgoComputers` | Start a stopped VM |
| `stop(id)` | `ApiServiceOrgoComputers` | Stop a running VM |
| `restart(id)` | `ApiServiceOrgoComputers` | Restart a VM |
| `get_vnc_password(id)` | `ApiServiceOrgoComputers` | Get VNC/WebSocket token |

### Desktop Actions

| Method | Description |
|--------|-------------|
| `screenshot(id)` | Capture screen → base64 PNG |
| `click(id, x, y, button, double)` | Mouse click |
| `drag(id, x1, y1, x2, y2)` | Click-drag |
| `type_text(id, text)` | Type a string |
| `key(id, key)` | Send key/combo — e.g. `'ctrl+c'`, `'Enter'`, `'F5'` |
| `scroll(id, direction, amount)` | Scroll up/down |
| `bash(id, command)` | Run shell command → output + success |
| `wait(id, duration)` | Pause (max 60s) |

### Files

| Method | Description |
|--------|-------------|
| `list_files(workspace_id, computer_id)` | List uploaded files |
| `download_file(file_id)` | Get temporary download URL (1hr) |
| `delete_file(file_id)` | Delete a file |

---

## Usage Examples

### List workspaces and computers

```python
from apps.orgo.references.web.api.workspaces import ApiServiceOrgoWorkspaces
from apps.orgo.config import CONFIG

svc = ApiServiceOrgoWorkspaces(CONFIG)
workspaces = svc.list_workspaces()
for ws in workspaces:
    print(ws['name'], ws['computer_count'])
```

### Provision a computer and run a command

```python
from apps.orgo.references.web.api.computers import ApiServiceOrgoComputers
from apps.orgo.config import CONFIG

svc = ApiServiceOrgoComputers(CONFIG)

# Create a small VM
computer = svc.create_computer(
    workspace_id='your-workspace-uuid',
    name='my-agent-vm',
    ram=4,
    cpu=2,
    auto_stop_minutes=30
)
computer_id = computer['id']

# Wait for it to be running (poll get_computer status)
# ...

# Run a command
result = svc.bash(computer_id, 'echo "hello from orgo"')
print(result['output'])   # hello from orgo
print(result['success'])  # True

# Take a screenshot
screen = svc.screenshot(computer_id)
# screen['image'] contains base64 PNG
```

### Agent control loop (Claude + screenshot)

```python
import base64
from apps.orgo.references.web.api.computers import ApiServiceOrgoComputers
from apps.orgo.config import CONFIG

svc = ApiServiceOrgoComputers(CONFIG)
computer_id = 'your-computer-id'

# Screenshot → Claude analyzes → action → repeat
screen = svc.screenshot(computer_id)
# Pass screen['image'] to Claude vision for analysis
# Claude returns action: click(x, y) or type(text) or key(combo)

svc.click(computer_id, x=640, y=400)
svc.type_text(computer_id, "Hello World")
svc.key(computer_id, "Enter")
```

### WebSocket Access (terminal)

```
wss://{computer_id}.orgo.dev/terminal?token={vnc_password}&cols=80&rows=24
```

Get the VNC password first:
```python
vnc = svc.get_vnc_password(computer_id)
token = vnc['password']
```

---

## Computer Status Values

| Status | Meaning |
|--------|---------|
| `starting` | VM is booting (typically <500ms) |
| `running` | Ready to accept commands |
| `stopping` | Shutting down |
| `stopped` | Stopped, can be restarted |
| `suspended` | Suspended state |
| `error` | Error — check logs |

---

## VM Configuration Options

| Parameter | Options | Default |
|-----------|---------|---------|
| `ram` | 4, 8, 16, 32, 64 GB | 4 |
| `cpu` | 2, 4, 8, 16 cores | 2 |
| `gpu` | `none`, `a10`, `l40s`, `a100-40gb`, `a100-80gb` | `none` |
| `resolution` | `WxHxD` string | `1280x720x24` |
| `auto_stop_minutes` | Integer, 0 to disable | None |

---

## Tests

```bash
# Requires ORGO_API_KEY set in .env/apps.env
pytest apps/orgo/tests/ -m smoke    # connectivity check
pytest apps/orgo/tests/ -m sanity   # workspace details
```

---

## MCP Tools

Registered in `mcp/server.py`. Available to Claude via the HARQIS-Work MCP server.

| Tool | Description |
|------|-------------|
| `list_orgo_workspaces` | List all workspaces |
| `get_orgo_workspace` | Get workspace by ID |
| `get_orgo_computer` | Get computer status and details |
| `create_orgo_computer` | Provision a new cloud VM |
| `start_orgo_computer` | Start a stopped VM |
| `stop_orgo_computer` | Stop a running VM |
| `orgo_screenshot` | Capture the current screen |
| `orgo_bash` | Run a shell command on the VM |
| `orgo_type` | Type text on the VM |
| `orgo_click` | Click at screen coordinates |
| `orgo_key` | Send a key or key combination |
| `list_orgo_files` | List files in a workspace |
| `download_orgo_file` | Get a file download URL |

Example Claude prompts:
- *"List my Orgo workspaces"* → `list_orgo_workspaces()`
- *"Create a new VM called test-agent"* → `create_orgo_computer(...)`
- *"Run `ls -la` on my VM"* → `orgo_bash(computer_id, 'ls -la')`
- *"Take a screenshot of my VM"* → `orgo_screenshot(computer_id)`

---

## Further Reading

- [Orgo Documentation](https://docs.orgo.ai/introduction)
- [Orgo API Reference](https://docs.orgo.ai/api-reference/introduction)
- [Orgo Workspaces](https://www.orgo.ai/workspaces)
