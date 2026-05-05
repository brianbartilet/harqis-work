"""
HARQIS Dashboard — FastAPI entry point.

Routes
------
GET  /                              → redirect to /dashboard
GET  /login                         → login page
POST /login                         → authenticate and set session cookie
GET  /logout                        → clear session, redirect to /login
GET  /dashboard                     → main dashboard (requires auth)
POST /tasks/{workflow}/{key}/trigger → dispatch Celery task, return status HTML
GET  /tasks/status/{task_id}        → poll task status (HTMX partial)
GET  /health                        → simple health check
"""
from pathlib import Path
from typing import Optional

import hmac
import logging
import os
import subprocess
import sys

import uvicorn
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import celery_client
from auth import (
    create_session_token,
    get_current_user,
    is_rate_limited,
    record_failed_login,
    clear_failed_logins,
)
from config import get_settings, warn_insecure_defaults
from registry import TASK_REGISTRY

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── Auto-regenerate registry from tasks_config.py on every startup ────────────
try:
    import generate_registry
    generate_registry.main()
except Exception as _regen_err:
    logger.warning("Registry regeneration failed: %s", _regen_err)

# ── App setup ─────────────────────────────────────────────────────────────────
settings = get_settings()
warn_insecure_defaults(settings)

app = FastAPI(title="HARQIS Dashboard", docs_url=None, redoc_url=None)


# ── Security headers ──────────────────────────────────────────────────────────
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Frame-Options"]        = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"]        = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"]     = "geolocation=(), microphone=(), camera=()"
    return response

_here = Path(__file__).parent
templates = Jinja2Templates(directory=str(_here / "templates"))

static_dir = _here / "static"
static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _find_task(workflow: str, task_key: str) -> Optional[dict]:
    wf = TASK_REGISTRY.get(workflow)
    if not wf:
        return None
    return next((t for t in wf["tasks"] if t["key"] == task_key), None)


def _require_auth(request: Request):
    """Returns (user, None) or (None, RedirectResponse)."""
    user = get_current_user(request)
    if not user:
        return None, RedirectResponse("/login", status_code=302)
    return user, None


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/", include_in_schema=False)
async def root(request: Request):
    user = get_current_user(request)
    return RedirectResponse("/dashboard" if user else "/login", status_code=302)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/debug/config")
async def debug_config(request: Request):
    """Verify loaded settings (auth required, all sensitive values masked).

    Previously unauthenticated and leaked the broker URI verbatim — now gated
    behind the dashboard session and only confirms whether each value is set,
    not its content. Closes audit finding H6.
    """
    user, redirect = _require_auth(request)
    if redirect:
        return redirect
    from config import _APPS_ENV
    return {
        "env_file": str(_APPS_ENV),
        "env_file_exists": _APPS_ENV.exists(),
        "flower_url": settings.flower_url,
        "flower_user_set": bool(settings.flower_user),
        "flower_password_set": bool(settings.flower_password),
        "celery_broker_set": bool(settings.celery_broker),
    }


# ── Auth ──────────────────────────────────────────────────────────────────────

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, error: Optional[str] = None):
    return templates.TemplateResponse(request, "login.html", {"error": error})


@app.post("/login")
async def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    ip = request.client.host if request.client else "unknown"

    if is_rate_limited(ip):
        logger.warning("Login rate limit hit for IP %s", ip)
        return templates.TemplateResponse(
            request, "login.html",
            {"error": "Too many failed attempts — try again in 15 minutes."},
            status_code=429,
        )

    # Constant-time compare for both fields to avoid leaking timing signals.
    username_ok = hmac.compare_digest(username, settings.app_username)
    password_ok = hmac.compare_digest(password, settings.app_password)
    if username_ok and password_ok:
        clear_failed_logins(ip)
        token = create_session_token(username)
        response = RedirectResponse("/dashboard", status_code=302)
        response.set_cookie(
            "session",
            token,
            max_age=settings.session_max_age,
            httponly=True,
            samesite="lax",
            secure=settings.behind_proxy,
        )
        return response

    record_failed_login(ip)
    logger.warning("Failed login attempt for user %r from IP %s", username, ip)
    return templates.TemplateResponse(
        request, "login.html",
        {"error": "Invalid username or password."},
        status_code=401,
    )


@app.get("/logout")
async def logout():
    response = RedirectResponse("/login", status_code=302)
    response.delete_cookie("session")
    return response


# ── Dashboard ─────────────────────────────────────────────────────────────────

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    user, redirect = _require_auth(request)
    if redirect:
        return redirect
    return templates.TemplateResponse(
        request, "dashboard.html",
        {
            "user": user,
            "workflows": TASK_REGISTRY,
            "flower_url": settings.flower_url,
        },
    )


# ── Task trigger ──────────────────────────────────────────────────────────────

@app.post("/tasks/{workflow}/{task_key}/trigger", response_class=HTMLResponse)
async def trigger_task(request: Request, workflow: str, task_key: str):
    user = get_current_user(request)
    if not user:
        return HTMLResponse(
            '<p class="text-red-400 text-xs">Session expired — please log in again.</p>'
        )

    task = _find_task(workflow, task_key)
    if not task:
        return HTMLResponse(
            '<p class="text-red-400 text-xs">Task not found in registry.</p>'
        )

    try:
        task_id = celery_client.dispatch(
            task_path=task["task_path"],
            kwargs=task.get("kwargs", {}),
            queue=task["queue"],
        )
    except Exception as exc:
        return templates.TemplateResponse(
            request, "partials/status_panel.html",
            {
                "task_id": None,
                "state": "DISPATCH_ERROR",
                "info": {"note": str(exc)},
                "polling": False,
            },
        )

    return templates.TemplateResponse(
        request, "partials/status_panel.html",
        {
            "task_id": task_id,
            "state": "PENDING",
            "info": {"note": "Waiting for a worker to pick up the task…"},
            "polling": True,
        },
    )


# ── Status poll ───────────────────────────────────────────────────────────────

@app.get("/tasks/status/{task_id}", response_class=HTMLResponse)
async def task_status(request: Request, task_id: str):
    if not get_current_user(request):
        return HTMLResponse("")

    info = await celery_client.get_task_info(task_id)
    state = info.get("state", "UNKNOWN")

    return templates.TemplateResponse(
        request, "partials/status_panel.html",
        {
            "task_id": task_id,
            "state": state,
            "info": info,
            "polling": not celery_client.is_terminal(state),
        },
    )


# ── Open local path (Windows) ─────────────────────────────────────────────────

@app.get("/open-path")
async def open_path(request: Request, p: str):
    """Open a local file or directory using the OS default application."""
    if not get_current_user(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    try:
        if sys.platform == "win32":
            os.startfile(p)
        elif sys.platform == "darwin":
            subprocess.run(["open", p], check=True)
        else:
            subprocess.run(["xdg-open", p], check=True)
        return JSONResponse({"ok": True})
    except Exception as exc:
        logger.warning("open-path failed for %r: %s", p, exc)
        return JSONResponse({"error": str(exc)}, status_code=500)


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=True,
    )
