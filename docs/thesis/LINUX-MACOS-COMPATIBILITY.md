# Linux / macOS Compatibility Audit

**Repository:** harqis-work  
**Date:** 2026-04-10  
**Scope:** Full codebase review for cross-platform portability

---

## Summary

The majority of harqis-work runs cleanly on Linux and macOS. The Windows-locked surface is limited to three display/hardware subsystems: Rainmeter HUD rendering, Corsair iCUE profile switching, and active window detection via Win32 APIs. All REST API integrations, the Kanban agent system, the frontend dashboard, and the MCP server are fully cross-platform.

---

## Critical — Won't run on Linux/macOS

### 1. Rainmeter HUD (`apps/rainmeter/`)

Rainmeter is Windows-only desktop gadget software. The entire subsystem uses Windows-only APIs.

| File | Issue |
|------|-------|
| `apps/rainmeter/references/helpers/bangs.py` | Hardcoded `C:\Program Files\Rainmeter\Rainmeter.exe`; uses `subprocess.STARTUPINFO`, `STARTF_USESHOWWINDOW` |
| `apps/rainmeter/references/helpers/config_builder.py` | `import winsound`; `ctypes.windll.user32` |
| `apps/rainmeter/references/helpers/smart_profiles.py` | `subprocess.CREATE_NO_WINDOW` with no fallback |

**Blocked features:** All `workflows/hud/` Rainmeter output tasks — calendar panel, TCG orders panel, YNAB budgets panel, forex panel, HUD profiles, desktop logs rendering.

> Note: the data-fetching tasks within `workflows/hud/` (YNAB, OANDA, Google Calendar, Trello) are fully cross-platform. Only the final Rainmeter write step is Windows-locked.

**Suggested fix:** Wrap all Rainmeter imports in a platform guard and provide no-op stubs on non-Windows. Linux alternative: Conky. macOS alternative: Übersicht.

```python
import sys
if sys.platform == "win32":
    from apps.rainmeter.references.helpers import bangs, config_builder
else:
    bangs = config_builder = None  # no-op on non-Windows
```

---

### 2. Win32 Window APIs (`workflows/hud/tasks/hud_utils.py`)

```python
import win32gui       # pywin32 — Windows-only
import win32process   # pywin32 — Windows-only

hwnd = win32gui.GetForegroundWindow()
pid = win32process.GetWindowThreadProcessId(hwnd)[1]
```

`pywin32` provides FFI bindings to Windows DLL functions. There is no equivalent on Linux (X11 uses python-xlib/ewmh) or macOS (Quartz uses PyObjC/AppKit).

**Blocked features:** `get_active_window_app()` → active window detection → `show_mouse_bindings()` HUD panel.

**Suggested fix:**

```python
import sys, platform

def get_active_window_app() -> str:
    if sys.platform == "win32":
        import win32gui, win32process
        hwnd = win32gui.GetForegroundWindow()
        pid = win32process.GetWindowThreadProcessId(hwnd)[1]
        # ... existing Windows logic
    elif sys.platform == "linux":
        # Use ewmh / python-xlib
        return ""
    else:
        return ""
```

---

### 3. Corsair iCUE (`apps/desktop/corsair/`, `workflows/hud/tasks/hud_utils.py`)

```python
# hud_utils.py
path = 'C:\Program Files\Corsair\Corsair iCUE5 Software\iCUE.exe'
```

iCUE is Windows-only hardware management software for Corsair peripherals. The `.cueprofiledata` and `.cueprofile` XML files it produces do not exist on other platforms.

**Blocked features:** `show_mouse_bindings()` HUD panel, `build_summary_mouse_bindings()` task.

**Suggested fix:** Add platform check; skip iCUE scan on non-Windows; document as Windows-only feature.

---

## Major — Feature broken, rest of app runs

### 4. Hardcoded paths (`workflows/desktop/tasks/commands.py`)

```python
# Line ~60 — username hardcoded
pull_list = ['C:/Users/brian/GIT/run/harqis-work']

# Line ~148 — absolute .bat paths
bat_list = [
    r"C:\Users\brian\GIT\harqis-work\workflows\n8n\deploy\backup.bat",
    r"C:\Users\brian\GIT\harqis-work\workflows\n8n\deploy\restore.bat",
]

# Rainmeter ini via %APPDATA% — Windows-only env var
rainmeter_ini = Path(os.environ["APPDATA"]) / "Rainmeter" / "Rainmeter.ini"
```

**Blocked features:** `git_pull_on_paths()` task, `run_n8n_sequence()` task, Rainmeter ini path resolution.

**Suggested fix:**
- Replace hardcoded paths with `pathlib.Path.home()` or env-var-backed config
- Use `.sh` scripts on Unix; detect platform to choose the right script
- Replace `%APPDATA%` with `Path.home() / ".config"` on Linux, `Path.home() / "Library/Application Support"` on macOS

---

### 5. Desktop assistant widget (`workflows/n8n/utilities/assistant_widget.py`)

The widget itself (PySide6) is cross-platform. However, the "pin to desktop background" feature uses Windows-specific WorkerW window parenting:

```python
if _is_windows:
    user32 = ctypes.windll.user32
    # EnumWindows, FindWindowW, SendMessageTimeoutW ...
```

The platform guard prevents crashes, but on Linux/macOS the widget appears as a regular floating window instead of a desktop gadget.

**Suggested fix:** Add Linux (GNOME/KDE) and macOS (NSWindow) desktop integration paths.

---

### 6. Missing Unix startup scripts (`scripts/`)

| Windows script | Unix equivalent |
|----------------|-----------------|
| `run_workflow_scheduler.bat` | Missing |
| `run_workflow_worker.bat` | Missing |
| `run_workflow_worker_hud.bat` | Missing |
| `run_workflow_worker_tcg.bat` | Missing |
| `set_env_workflows.bat` | Partial — `set_env.sh` exists |
| `workflows/n8n/deploy/backup.bat` | `backup.sh` exists ✓ |
| `workflows/n8n/deploy/restore.bat` | `restore.sh` exists ✓ |

**Suggested fix:** Create `.sh` equivalents for all missing `.bat` files.

---

## Minor — Degrades gracefully

### 7. Process name matching with `.exe` suffix

```python
# workflows/hud/tasks/hud_utils.py
if name in ("python.exe", "pythonw.exe"):
    ...
```

`psutil` is cross-platform, but process names never end in `.exe` on Linux/macOS — the check simply never matches. Feature is silently skipped rather than crashing.

**Suggested fix:**
```python
import platform
exe_suffix = ".exe" if platform.system() == "Windows" else ""
if name in (f"python{exe_suffix}", f"pythonw{exe_suffix}"):
    ...
```

---

## Already handled correctly

| Component | How |
|-----------|-----|
| `agents/kanban/agent/tools/filesystem.py` — `BashTool` | Uses `platform.system()` to switch between `cmd.exe` and `/bin/bash` |
| `frontend/main.py` — file open | `os.startfile` on Windows, `xdg-open` on Linux, `open` on macOS |
| `docker-compose.yml` | Uses only relative paths; no Windows-specific mounts |
| All `apps/` REST integrations | Pure `requests`/SDK — no OS dependencies |
| `agents/kanban/` | Fully cross-platform; tested on Windows, designed for Linux workers |

---

## What runs on Linux/macOS today

| Component | Status |
|-----------|--------|
| `agents/kanban/` — full orchestrator + agent loop | ✅ Fully cross-platform |
| `apps/` — all REST API integrations | ✅ Fully cross-platform |
| `frontend/` — FastAPI + HTMX dashboard | ✅ Fully cross-platform |
| `mcp/` — FastMCP server | ✅ Fully cross-platform |
| `workflows/hud/` — data-fetch tasks (YNAB, OANDA, Calendar, Trello) | ✅ Data layer works; Rainmeter output step fails |
| `workflows/purchases/` — MTG card pipeline | ✅ Fully cross-platform |
| `workflows/desktop/` — git pulls, file sync | ⚠️ Works except hardcoded paths and .bat calls |
| `apps/rainmeter/` — HUD rendering | ❌ Windows-only |
| `apps/desktop/corsair/` — iCUE profiles | ❌ Windows-only |
| `workflows/hud/tasks/hud_utils.py` — active window detection | ❌ Windows-only (pywin32) |

---

## Cross-platform alternatives

| Windows feature | Linux | macOS |
|-----------------|-------|-------|
| Rainmeter | Conky, Screenlets | Übersicht |
| iCUE (Corsair) | No equivalent | No equivalent |
| `win32gui` / active window | `python-xlib`, `ewmh` | `PyObjC`, `AppKit` |
| `%APPDATA%` | `$XDG_CONFIG_HOME` / `~/.config` | `~/Library/Application Support` |
| `winsound` | `sounddevice`, `pygame` | `simpleaudio`, `pygame` |
| `.bat` scripts | `.sh` scripts | `.sh` scripts |

---

## Recommended remediation

### Immediate (unblock Linux worker nodes)

1. Add platform guards to `apps/rainmeter/` so `import` doesn't crash on non-Windows
2. Wrap `win32gui` / `win32process` imports in `if sys.platform == "win32":` in `hud_utils.py`
3. Replace hardcoded `C:/Users/brian/...` paths in `commands.py` with env-var or `Path.home()`-based resolution

### Medium priority

4. Create `.sh` equivalents for all missing `scripts/*.bat` files
5. Add Linux/macOS desktop integration path to the assistant widget

### Nice to have

6. Normalize all `.exe` process name checks with a platform-aware suffix helper
7. Document Windows-only features clearly in each module's docstring
