"""
HARQIS module frontend — FastAPI entry point.

Routes
------
GET  /                              → redirect to /home
GET  /login                         → login page
POST /login                         → authenticate and set session cookie
GET  /logout                        → clear session, redirect to /login
GET  /home                          → manifesto and module overview
GET  /workflows                     → workflow task dashboard
POST /tasks/{workflow}/{key}/trigger → dispatch Celery task, return status HTML
GET  /tasks/status/{task_id}        → poll task status (HTMX partial)
GET  /applications                  → app inventory, docs, and pytest controls
GET  /hfl-corpus                    → recursive corpus browser and search
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
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from auth import (
    create_session_token,
    get_current_user,
    is_rate_limited,
    record_failed_login,
    clear_failed_logins,
)
from config import get_settings, warn_insecure_defaults
from modules.applications.router import router as applications_router
from modules.hfl_corpus.api import router as hfl_corpus_api_router
from modules.hfl_corpus.router import router as hfl_corpus_router
from modules.home.router import router as home_router
from modules.workflows.router import router as workflows_router
from web import require_user as _require_auth, templates

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── App setup ─────────────────────────────────────────────────────────────────
settings = get_settings()
warn_insecure_defaults(settings)

app = FastAPI(title="HARQIS Frontend", docs_url=None, redoc_url=None)
app.include_router(home_router)
app.include_router(workflows_router)
app.include_router(applications_router)
app.include_router(hfl_corpus_api_router)
app.include_router(hfl_corpus_router)


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

static_dir = _here / "static"
static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/", include_in_schema=False)
async def root(request: Request):
    user = get_current_user(request)
    return RedirectResponse("/home" if user else "/login", status_code=302)


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


@app.get("/dashboard", include_in_schema=False)
async def legacy_dashboard(request: Request):
    user = get_current_user(request)
    return RedirectResponse("/home" if user else "/login", status_code=302)


# ── Open local path (Windows) ─────────────────────────────────────────────────

# Extensions that are runnable on Windows / macOS / Linux. `os.startfile` and
# `xdg-open` will execute these, so they are forbidden even when the path is
# inside an allowed root.
_OPEN_PATH_DENIED_EXTENSIONS = frozenset({
    ".exe", ".bat", ".cmd", ".com", ".lnk", ".ps1", ".psm1", ".vbs",
    ".js", ".jse", ".jar", ".msi", ".scr", ".pif", ".sh", ".reg",
})


def _resolve_open_path_roots() -> list[Path]:
    """Compute the absolute root directories that `/open-path` may open under.

    Source order:
      1. `OPEN_PATH_ALLOWED_ROOTS` env var — OS-pathsep-separated absolute paths.
      2. Default — repo root, plus `RAINMETER_WRITE_SKINS_TO_PATH` and
         `DESKTOP_PATH_RUN` env vars when present.
    """
    raw = os.environ.get("OPEN_PATH_ALLOWED_ROOTS", "").strip()
    if raw:
        return [Path(p).resolve() for p in raw.split(os.pathsep) if p.strip()]
    roots = [Path(__file__).resolve().parent.parent]
    for env_key in ("RAINMETER_WRITE_SKINS_TO_PATH", "DESKTOP_PATH_RUN"):
        value = os.environ.get(env_key)
        if value:
            roots.append(Path(value).resolve())
    return roots


_OPEN_PATH_ALLOWED_ROOTS: list[Path] = _resolve_open_path_roots()


def _is_open_path_safe(p: str) -> tuple[bool, str]:
    """Validate `p` is safe for `/open-path`. Returns `(ok, reason)`."""
    if not p:
        return False, "empty path"
    # Reject UNC paths up front — they can point at attacker-controlled SMB shares.
    if p.startswith("\\\\") or p.startswith("//"):
        return False, "UNC paths not allowed"
    try:
        resolved = Path(p).resolve(strict=False)
    except (OSError, ValueError) as exc:
        return False, f"cannot resolve path: {exc}"
    if not resolved.exists():
        return False, "path does not exist"
    if resolved.suffix.lower() in _OPEN_PATH_DENIED_EXTENSIONS:
        return False, f"extension not allowed: {resolved.suffix}"
    for root in _OPEN_PATH_ALLOWED_ROOTS:
        try:
            resolved.relative_to(root)
            return True, ""
        except ValueError:
            continue
    return False, "path is not under an allowed root"


@app.get("/open-path")
async def open_path(request: Request, p: str):
    """Open a local file or directory using the OS default application.

    Restricted to paths under `OPEN_PATH_ALLOWED_ROOTS` (or repo root +
    `RAINMETER_WRITE_SKINS_TO_PATH` + `DESKTOP_PATH_RUN` by default). Rejects
    UNC paths and runnable extensions (`.exe`, `.bat`, `.cmd`, `.lnk`, …).
    Closes audit finding C2.
    """
    if not get_current_user(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    ok, reason = _is_open_path_safe(p)
    if not ok:
        logger.warning("open-path blocked for %r: %s", p, reason)
        return JSONResponse({"error": reason}, status_code=400)
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
    reload_enabled = os.environ.get("FRONTEND_RELOAD", "").strip().lower() in {
        "1", "true", "yes", "on",
    }
    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=reload_enabled,
        reload_dirs=[str(_here)] if reload_enabled else None,
    )
