# OS Compatibility

**Repository:** harqis-work  
**Date:** 2026-04-10

---

## Overview

harqis-work is a multi-platform codebase. Most components are fully cross-platform (Linux, macOS, Windows). Certain subsystems are intentionally Windows-specific, as they integrate with Windows-only hardware and desktop software that is part of the design.

---

## Platform Support by Component

| Component                                                      | Windows | Linux | macOS | Notes |
|----------------------------------------------------------------|:-------:|:-----:|:-----:|-------|
| `agents/projects/` — Kanban orchestrator + agent loop            | ✅ | ✅ | ✅ | Fully cross-platform by design; intended to run on Linux worker nodes |
| `apps/` — REST API integrations (20+ apps)                     | ✅ | ✅ | ✅ | Pure HTTP/SDK; no OS dependencies |
| `frontend/` — FastAPI + HTMX dashboard                         | ✅ | ✅ | ✅ | Cross-platform |
| `mcp/` — FastMCP server                                        | ✅ | ✅ | ✅ | Cross-platform |
| `workflows/hud/` — some integrations with rainmeter             | ✅ | ⚠️ | ⚠️ | Partial — see Windows-specific section |
| `workflows/purchases/` — MTG card pipeline                     | ✅ | ✅ | ✅ | Cross-platform |
| `workflows/desktop/` — git pulls, file sync, window management | ✅ | ⚠️ | ⚠️ | Partial — see Windows-specific section |
| `apps/rainmeter/` — HUD desktop rendering                      | ✅ | — | — | Windows-only by design |
| `apps/desktop/corsair/` — iCUE hardware profiles               | ✅ | — | — | Windows-only by design |
| Active window detection (`hud_utils.py`)                       | ✅ | — | — | Windows-only by design (Win32 API) |

---

## Windows-Specific Subsystems

These components target Windows exclusively. This is by design — they integrate with Windows desktop software and hardware that does not exist on other platforms.

### Rainmeter HUD (`apps/rainmeter/`)

Drives a live heads-up display on the Windows desktop using [Rainmeter](https://www.rainmeter.net/). Celery tasks in `workflows/hud/` write data into Rainmeter skin files which render as always-on overlay panels.

Uses:
- `Rainmeter.exe` to apply skin changes via command-line bangs
- `winsound` for audio feedback
- `ctypes.windll` for window messaging
- `subprocess.STARTUPINFO` / `STARTF_USESHOWWINDOW` for hidden process launch

All Rainmeter-dependent tasks in `workflows/hud/` are expected to be run on a Windows machine. The data-fetching portions of those same tasks (API calls to YNAB, OANDA, Google Calendar, etc.) are cross-platform.

### Corsair iCUE Hardware Profiles (`apps/desktop/corsair/`)

Reads Corsair iCUE peripheral profile files (`.cueprofiledata`, `.cueprofile`) to display active mouse macro bindings in the HUD. Requires [Corsair iCUE](https://www.corsair.com/icue) installed on Windows.

Hardcoded default path: `C:\Program Files\Corsair\Corsair iCUE5 Software\iCUE.exe`  
Overridable via `DESKTOP_PATH_I_CUE_PROFILES` environment variable.

### Active Window Detection (`workflows/hud/tasks/hud_utils.py`)

Uses `win32gui` and `win32process` (from the `pywin32` package) to detect the currently focused application. This drives HUD profile switching based on which app is in the foreground.

### Desktop Widget (`workflows/n8n/utilities/assistant_widget.py`)

A PySide6 floating widget for the ElevenLabs voice assistant. On Windows, it uses `ctypes.windll` to parent itself to the WorkerW desktop background layer (Windows 10+ feature), making it appear as a desktop gadget. The platform guard (`if _is_windows:`) is in place — on other platforms it runs as a regular window.

### Startup Scripts (`scripts/`)

Batch files (`.bat`) are provided for Windows. The n8n deployment scripts have both `.bat` and `.sh` equivalents. General workflow startup scripts are Windows-only.

| Script | Platform |
|--------|----------|
| `scripts/run_workflow_scheduler.bat` | Windows |
| `scripts/run_workflow_worker.bat` | Windows |
| `scripts/run_workflow_worker_hud.bat` | Windows |
| `scripts/set_env_workflows.bat` | Windows |
| `scripts/set_env.sh` | Linux / macOS |
| `workflows/n8n/deploy/backup.bat` | Windows |
| `workflows/n8n/deploy/backup.sh` | Linux / macOS |
| `workflows/n8n/deploy/restore.bat` | Windows |
| `workflows/n8n/deploy/restore.sh` | Linux / macOS |

---

## Cross-Platform Notes

### Bash Tool (`agents/projects/agent/tools/filesystem.py`)

The `BashTool` used by Kanban agents detects the platform at runtime:

```python
_IS_WINDOWS = platform.system() == "Windows"
# Uses cmd.exe on Windows, /bin/bash on Linux/macOS
```

### File Opening (`frontend/main.py`)

Platform-aware file open:

```python
if sys.platform == "win32":
    os.startfile(p)
elif sys.platform == "darwin":
    subprocess.run(["open", p])
else:
    subprocess.run(["xdg-open", p])
```

### Docker

`docker-compose.yml` uses only relative paths. All container definitions are cross-platform compatible.

---

## Deployment Model

The intended deployment topology separates Windows-specific workloads from cross-platform ones:

| Node | OS | Runs |
|------|----|------|
| Orchestrator / dev machine | Windows | Rainmeter HUD, iCUE profiles, active window detection, Kanban orchestrator, frontend |
| Worker nodes | Linux (e.g. N100 mini PCs) | Kanban agents, REST workflow tasks, MCP server |
| Shared | Any | All `apps/` integrations, `agents/projects/`, `frontend/`, `mcp/` |

This means Windows-specific subsystems are always co-located on the primary Windows machine, while compute-heavy or headless agent workloads can be offloaded to Linux nodes.
