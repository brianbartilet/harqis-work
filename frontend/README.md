# HARQIS Frontend Dashboard

A lightweight web dashboard for manually triggering HARQIS Celery workflow tasks, built with FastAPI, HTMX, Alpine.js, and Tailwind CSS.

![HARQIS Dashboard](../docs/dashboard-sample.png)

## Features

- **Login-protected** — username/password via a signed session cookie
- **Three workflow tabs** — HUD, Purchases, Desktop (one tab per workflow module)
- **One-click task triggering** — dispatches to the Celery broker directly
- **Live status polling** — HTMX polls every 2s and stops automatically on task completion
- **Rich output panel** — shows state, worker, queue, elapsed time, result, exception, and traceback
- **Run history** — last 20 runs per task stored in browser localStorage
- **Customizable layout** — drag-and-drop tab and card reordering via SortableJS, persisted across sessions
- **Flower link** — header links to the Flower monitoring UI if configured
- **No build step** — Tailwind, HTMX, Alpine.js, and SortableJS all load from CDN

## Requirements

- Python 3.12+
- RabbitMQ running (same broker as the Celery workers)
- [Flower](https://flower.readthedocs.io/) running for task status (optional but recommended)

## Setup

```sh
cd frontend

# 1. Create virtual env (or reuse the repo venv)
python -m venv venv
source venv/bin/activate    # Windows: venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure environment
cp .env.example .env
# Edit .env — set APP_USERNAME, APP_PASSWORD, SECRET_KEY, CELERY_BROKER, FLOWER_URL
```

## Running

```sh
# From the frontend/ directory
python main.py

# Or with uvicorn directly
uvicorn main:app --host 0.0.0.0 --port 8080 --reload
```

Open: **http://localhost:8080**

## Starting Flower (recommended)

Flower must be running for task status tracking to work. From the repo root:

```sh
# Using the existing scripts
scripts\flower.bat

# Or manually
celery -A workflows.config flower --port=5555
```

Then set `FLOWER_URL=http://localhost:5555` in `frontend/.env`.

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `APP_USERNAME` | `admin` | Dashboard login username |
| `APP_PASSWORD` | `changeme` | Dashboard login password |
| `SECRET_KEY` | — | Secret for signing session cookies (change this!) |
| `CELERY_BROKER` | `amqp://guest:guest@localhost:5672/` | RabbitMQ broker URL |
| `FLOWER_URL` | `http://localhost:5555` | Flower monitoring URL |
| `HOST` | `0.0.0.0` | Bind address |
| `PORT` | `8080` | Bind port |
| `SESSION_MAX_AGE` | `28800` | Session lifetime in seconds (default: 8 hours) |

## Keeping the Registry in Sync

`frontend/registry.py` is the task registry that powers the dashboard. It is **generated** from `workflows/*/tasks_config.py` — run the generator whenever you add, remove, or change a task:

```sh
# From the repo root, with venv active
python frontend/generate_registry.py
```

**What gets synced automatically:**

| Field | Source |
|---|---|
| `task_path` | `tasks_config.py` — always overwritten |
| `queue` | `tasks_config.py` — always overwritten |
| `kwargs` | `tasks_config.py` — always overwritten |
| `schedule` | `tasks_config.py` on first seen; preserved after that |
| `label` | Preserved from existing `registry.py`; auto-generated for new tasks |
| `description` | Preserved from existing `registry.py`; empty for new tasks |
| `manual_only` | Preserved from existing `registry.py`; `False` for new tasks |

**Manual-only tasks** (tasks in `registry.py` that have no beat schedule entry) are always preserved as-is.

After running the generator, review the output for any new tasks and fill in their `label`, `description`, and `manual_only` fields directly in `registry.py` — those edits will be preserved on the next run.

## Architecture

```
frontend/
├── main.py             # FastAPI routes
├── config.py           # Pydantic settings from .env
├── auth.py             # Session token create/verify (itsdangerous)
├── registry.py         # Static task registry (all 24 tasks across 3 workflows)
├── celery_client.py    # Task dispatch (bare Celery) + Flower API polling
├── requirements.txt
├── .env.example
└── templates/
    ├── base.html                    # Layout: Tailwind + HTMX + Alpine.js
    ├── login.html                   # Login card
    ├── dashboard.html               # Tabbed task grid
    └── partials/
        └── status_panel.html        # HTMX polling panel (auto-stops on terminal state)
```

## How Task Triggering Works

1. User clicks **Run now** on a task card.
2. HTMX POSTs to `/tasks/{workflow}/{task_key}/trigger`.
3. FastAPI dispatches the task via `celery.send_task()` using the same broker as the workers.
4. The response is a `status_panel.html` partial with `hx-trigger="every 2s"`.
5. HTMX polls `/tasks/status/{task_id}` every 2 seconds.
6. Each poll queries the Flower REST API for the current task state.
7. When the state reaches `SUCCESS`, `FAILURE`, or `REVOKED`, the poll trigger is omitted from the response — polling stops automatically.

## Task Status States

| State | Meaning |
|-------|---------|
| `PENDING` | Dispatched, waiting for a worker |
| `RECEIVED` | Worker received the task |
| `STARTED` | Worker started executing |
| `SUCCESS` | Completed successfully — result shown |
| `FAILURE` | Failed — exception and traceback shown |
| `REVOKED` | Task was cancelled |
| `UNKNOWN` | Flower not reachable or task not yet tracked |

## Without Flower

If Flower is not running, task dispatch still works — you'll see `PENDING` status and a note that Flower is unreachable. The task runs on the worker normally; you just won't see the result in the dashboard.

## Security Notes

### Before exposing to the network

1. **Generate a strong `SECRET_KEY`:**
   ```sh
   python -c "import secrets; print(secrets.token_hex(32))"
   ```
   Set it in `frontend/.env` as `SECRET_KEY=<output>`.

2. **Change `APP_PASSWORD`** from the default `changeme` to something strong.

3. **Set `BEHIND_PROXY=true`** in `.env` when running behind Cloudflare Tunnel or any HTTPS reverse proxy. This enables the `Secure` flag on session cookies so they are never sent over plain HTTP.

### What's enforced at runtime

| Protection | Detail |
|---|---|
| Startup warnings | Logs a warning on boot if `SECRET_KEY` or `APP_PASSWORD` are still set to defaults |
| Login rate limiting | Max 5 failed attempts per IP in a 15-minute window — returns HTTP 429 and blocks further attempts until the window expires |
| Failed login logging | Every failed attempt logs the username and source IP |
| Security headers | `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy`, `Permissions-Policy` on every response |
| Session cookies | `httponly=True`, `samesite=lax`, `secure=True` when `BEHIND_PROXY=true` |

### Additional recommendations

- Run behind Cloudflare Tunnel (or Nginx + Let's Encrypt) — never expose port 8080 directly to the internet.
- Session cookies are `httponly` and `samesite=lax` — not accessible from JavaScript.
