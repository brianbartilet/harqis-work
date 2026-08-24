"""
HARQIS module frontend — FastAPI entry point.

Routes
------
GET  /                              → redirect to /home
GET  /login                         → login page
POST /login                         → authenticate and set session cookie
GET  /logout                        → clear session, redirect to /login
GET  /profile                       → edit the global owner profile
GET  /home                          → module overview
GET  /manifesto                     → manifesto and guiding principles
GET  /workflows                     → workflow task dashboard
POST /tasks/{workflow}/{key}/trigger → dispatch Celery task, return status HTML
GET  /tasks/status/{task_id}        → poll task status (HTMX partial)
GET  /applications                  → app inventory, docs, and pytest controls
GET  /hfl-corpus                    → recursive corpus browser and search
GET  /health                        → simple health check
"""
from collections.abc import Mapping
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

import asyncio
import hmac
import logging
import os
import secrets
import subprocess
import sys
import time

import uvicorn
from fastapi import FastAPI, Form, Request
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
)
from fastapi.staticfiles import StaticFiles
from starlette.middleware.gzip import GZipMiddleware
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
from modules.hfl_corpus.corpus import corpus_index
from modules.hfl_corpus.remote import close_remote_http_client
from modules.hfl_corpus.router import router as hfl_corpus_router
from modules.hfl_shares.router import guest_router as hfl_share_guest_router
from modules.hfl_shares.router import owner_router as hfl_share_owner_router
from modules.git_forks.router import router as git_forks_router
from modules.home.router import router as home_router
from modules.manifesto.router import router as manifesto_router
from modules.profile.router import router as profile_router
from modules.second_brain.router import router as second_brain_router
from modules.workflows.router import router as workflows_router
from web import require_user as _require_auth, templates

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

PUBLIC_SHARE_MAX_BODY_BYTES = 32 * 1024
PUBLIC_SHARE_MAX_BODY_MESSAGES = 64
PUBLIC_SHARE_BODY_TIMEOUT_SECONDS = 10.0


class PublicShareBodyLimitMiddleware:
    """Bound public share POST bodies before form parsing or route work."""

    def __init__(
        self,
        app,
        max_body_bytes: int = PUBLIC_SHARE_MAX_BODY_BYTES,
        max_body_messages: int = PUBLIC_SHARE_MAX_BODY_MESSAGES,
        body_timeout_seconds: float = PUBLIC_SHARE_BODY_TIMEOUT_SECONDS,
    ):
        self.app = app
        self.max_body_bytes = max_body_bytes
        self.max_body_messages = max_body_messages
        self.body_timeout_seconds = body_timeout_seconds

    async def __call__(self, scope, receive, send):
        if (
            scope.get("type") != "http"
            or scope.get("method") != "POST"
            or not str(scope.get("path", "")).startswith("/share/")
        ):
            await self.app(scope, receive, send)
            return

        raw_headers = scope.get("headers", ())
        if not isinstance(raw_headers, (list, tuple)) or any(
            not isinstance(header, (list, tuple))
            or len(header) != 2
            or not isinstance(header[0], bytes)
            or not isinstance(header[1], bytes)
            for header in raw_headers
        ):
            await PlainTextResponse("Invalid request headers", status_code=400)(
                scope, receive, send
            )
            return
        headers = [(header[0], header[1]) for header in raw_headers]
        content_lengths = [
            value
            for name, value in headers
            if name.lower() == b"content-length"
        ]
        transfer_encodings = [
            value
            for name, value in headers
            if name.lower() == b"transfer-encoding"
        ]
        if transfer_encodings and (
            len(transfer_encodings) != 1
            or transfer_encodings[0].lower() != b"chunked"
        ):
            await PlainTextResponse("Invalid Transfer-Encoding", status_code=400)(
                scope, receive, send
            )
            return
        if content_lengths and transfer_encodings:
            await PlainTextResponse("Invalid request framing", status_code=400)(
                scope, receive, send
            )
            return
        declared_body_bytes = None
        if len(content_lengths) > 1:
            await PlainTextResponse("Invalid Content-Length", status_code=400)(
                scope, receive, send
            )
            return
        if content_lengths:
            declared_length = content_lengths[0]
            if not declared_length or any(
                byte < ord("0") or byte > ord("9") for byte in declared_length
            ):
                await PlainTextResponse(
                    "Invalid Content-Length", status_code=400
                )(scope, receive, send)
                return
            normalized_length = declared_length.lstrip(b"0") or b"0"
            maximum_length = str(self.max_body_bytes).encode("ascii")
            if len(normalized_length) > len(maximum_length) or (
                len(normalized_length) == len(maximum_length)
                and normalized_length > maximum_length
            ):
                await self._reject(scope, receive, send)
                return
            declared_body_bytes = int(normalized_length)

        body = bytearray()
        disconnected = False
        message_count = 0
        rejection = None
        try:
            async with asyncio.timeout(self.body_timeout_seconds):
                while True:
                    message = await receive()
                    message_count += 1
                    if message_count > self.max_body_messages:
                        rejection = (400, "Invalid request body")
                        break
                    if not isinstance(message, Mapping):
                        rejection = (400, "Invalid request body")
                        break
                    message_type = message.get("type")
                    if message_type == "http.disconnect":
                        disconnected = True
                        break
                    if message_type != "http.request":
                        rejection = (400, "Invalid request body")
                        break
                    chunk = message.get("body", b"")
                    more_body = message.get("more_body", False)
                    if not isinstance(chunk, bytes) or type(more_body) is not bool:
                        rejection = (400, "Invalid request body")
                        break
                    if len(chunk) > self.max_body_bytes - len(body):
                        rejection = (413, "Payload too large")
                        break
                    body.extend(chunk)
                    if not more_body:
                        break
        except TimeoutError:
            rejection = (408, "Request body timeout")

        if rejection is not None:
            status_code, detail = rejection
            await PlainTextResponse(detail, status_code=status_code)(
                scope, receive, send
            )
            return

        if disconnected:
            return
        if declared_body_bytes is not None and len(body) != declared_body_bytes:
            await PlainTextResponse("Invalid request framing", status_code=400)(
                scope, receive, send
            )
            return

        replayed = False

        async def replay_receive():
            nonlocal replayed
            if replayed:
                return {"type": "http.disconnect"}
            replayed = True
            return {
                "type": "http.request",
                "body": bytes(body),
                "more_body": False,
            }

        await self.app(scope, replay_receive, send)

    @staticmethod
    async def _reject(scope, receive, send):
        await PlainTextResponse("Payload too large", status_code=413)(
            scope, receive, send
        )

# ── App setup ─────────────────────────────────────────────────────────────────
settings = get_settings()
warn_insecure_defaults(settings)


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Warm local corpus state and release pooled remote connections cleanly."""
    if not get_settings().hfl_corpus_api_url.strip():
        await asyncio.to_thread(corpus_index.documents, True)
    try:
        yield
    finally:
        close_remote_http_client()


app = FastAPI(
    title="HARQIS Frontend",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    lifespan=lifespan,
)
app.add_middleware(PublicShareBodyLimitMiddleware)
app.add_middleware(
    GZipMiddleware,
    minimum_size=max(500, settings.frontend_gzip_minimum_size),
    compresslevel=5,
)
app.include_router(home_router)
app.include_router(manifesto_router)
app.include_router(workflows_router)
app.include_router(applications_router)
app.include_router(hfl_corpus_api_router)
app.include_router(hfl_corpus_router)
app.include_router(hfl_share_owner_router)
app.include_router(hfl_share_guest_router)
app.include_router(git_forks_router)
app.include_router(profile_router)
app.include_router(second_brain_router)


# ── Security headers ──────────────────────────────────────────────────────────
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    started_at = time.perf_counter()
    request.state.csp_nonce = secrets.token_urlsafe(24)
    response = await call_next(request)
    duration_ms = (time.perf_counter() - started_at) * 1_000
    response.headers["Server-Timing"] = f"app;dur={duration_ms:.1f}"
    if duration_ms >= max(1.0, settings.frontend_slow_request_ms):
        logger.warning(
            "Slow request method=%s path=%s status=%s duration_ms=%.1f",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
        )
    response.headers["X-Frame-Options"]        = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"]        = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"]     = "geolocation=(), microphone=(), camera=()"
    if request.url.path.startswith("/static/") and response.status_code == 200:
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    else:
        response.headers["Cache-Control"] = "no-store"
    if request.url.path.startswith("/share/"):
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data:; "
            "media-src 'self'; "
            f"script-src 'self' 'nonce-{request.state.csp_nonce}'; "
            "style-src 'self' 'unsafe-inline'; form-action 'self'; "
            "frame-ancestors 'none'; base-uri 'none'"
        )
    if settings.behind_proxy:
        response.headers["Strict-Transport-Security"] = "max-age=31536000"
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
        server_header=False,
    )
