"""Plaud acquisition adapter.

Two interchangeable backends behind one interface so callers never care which
served the data:

  * :class:`PlaudCloudBackend` — PRIMARY. Talks DIRECTLY to the (unofficial)
    ``api.plaud.ai`` REST surface over HTTP with a bearer token — no SDK
    package, just ``requests``. Lists recordings, resolves temporary download
    URLs, fetches audio, and surfaces Plaud's own transcript/summary when the
    listing includes them.
  * :class:`PlaudFolderBackend` — FALLBACK. Reads a local export folder the user
    populates manually from the Plaud desktop app (audio + optional sibling
    transcript/summary text files).

:class:`PlaudAdapter` tries the cloud first and transparently falls back to the
folder when the cloud is unconfigured, unauthenticated, or errors. The
unofficial cloud surface is isolated in ``PlaudCloudBackend`` so it can be
swapped for Plaud's official OAuth API later without touching any caller.

⚠️  ``api.plaud.ai`` is an UNOFFICIAL, reverse-engineered surface (endpoints and
field names per the openplaud project, mid-2026) — not a documented contract.
Endpoints/fields may drift; everything is wrapped defensively and field mapping
is tolerant of key drift, so a changed surface degrades to the folder backend
rather than crashing the pipeline. Override the base URL with ``PLAUD_API_BASE``
for non-US regions.

Auth (preferred → fallback):
  1. ``PLAUD_EMAIL`` + ``PLAUD_PASSWORD`` — the backend MINTS its own JWT
     (~30-day TTL on the live APSE1 surface) via ``POST /auth/access-token``
     (the web app's own login call, per the plaud-toolkit project), caches it in
     a git-ignored file, re-mints within a few days of expiry and transparently
     on a ``-419 token expired`` response.
  2. ``PLAUD_TOKEN`` — manual bearer lifted from ``web.plaud.ai`` →
     ``localStorage.getItem("tokenstr")``; expires periodically and must be
     re-pasted by hand, so credentials are the recommended path.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional
from urllib.parse import urlparse

from apps.plaud.references.dto.recording import DtoPlaudRecording

logger = logging.getLogger("harqis-mcp.plaud")

_AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac", ".opus"}
_TRANSCRIPT_EXTS = (".txt", ".md", ".srt", ".vtt")
_SUMMARY_SUFFIXES = ("-summary", "_summary", ".summary")

# Minted-token cache (git-ignored under logs/). Re-mint inside this buffer so a
# token never expires mid-window between nightly runs. The live APSE1 surface
# issues ~30-day tokens, so the buffer MUST stay well under that TTL — otherwise
# the cache is never fresh enough to serve and the backend re-mints on every run.
_TOKEN_REFRESH_BUFFER_S = 3 * 24 * 3600
_DEFAULT_TOKEN_CACHE = Path(__file__).resolve().parents[3] / "logs" / "plaud_token.json"


# ── helpers ─────────────────────────────────────────────────────────────────

def _iso(dt: datetime) -> str:
    """UTC ISO-8601 with second precision (matches the OwnTracks convention)."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-") or "recording"


def _jwt_claims(token: str) -> dict:
    """Best-effort decode of a JWT payload (NO signature check — only used to
    read our own token's ``iat``/``exp`` for cache freshness). Returns {} on
    any malformed input."""
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload))
    except Exception:  # noqa: BLE001 - diagnostics only, never fatal
        return {}


def _in_window(started_at: Optional[str], since: Optional[str], until: Optional[str]) -> bool:
    """Inclusive date-window filter on an ISO ``started_at``. Missing bounds are
    treated as open; an unparseable/absent timestamp is kept (never silently
    dropped — better to ingest than to lose a recording)."""
    if not started_at:
        return True
    if since and started_at < since:
        return False
    if until and started_at > until:
        return False
    return True


# ── interface ───────────────────────────────────────────────────────────────

class PlaudBackend(ABC):
    """Common interface for both acquisition paths."""

    name: str = "base"

    @abstractmethod
    def available(self) -> bool:
        """Cheap readiness check (token present / folder exists)."""

    @abstractmethod
    def list_recordings(self, since: Optional[str] = None,
                        until: Optional[str] = None) -> List[DtoPlaudRecording]:
        """Return recordings whose ``started_at`` falls within [since, until]."""

    @abstractmethod
    def ensure_audio_local(self, rec: DtoPlaudRecording, dest_dir: str) -> Optional[str]:
        """Make the audio available on disk under ``dest_dir``; return its path.

        Folder recordings already are local; cloud recordings are downloaded.
        Returns ``None`` if the audio cannot be obtained.
        """


# ── cloud (primary, unofficial) ──────────────────────────────────────────────

class PlaudCloudBackend(PlaudBackend):
    """Talks directly to the unofficial ``api.plaud.ai`` REST surface over HTTP
    (bearer token, no SDK). Isolated so the rest of the pipeline is insulated
    from upstream breakage and a future swap to Plaud's official OAuth API.

    Endpoints (reverse-engineered, per the openplaud project — mid-2026):
      * ``GET /file/simple/web``        — paginated recording list
      * ``GET /file/temp-url/{file_id}`` — short-lived signed audio URL
    """

    name = "cloud"

    _DEFAULT_BASE = "https://api.plaud.ai"
    _PAGE_LIMIT = 200          # per-page size for the list endpoint
    _MAX_PAGES = 50            # hard backstop so a bad cursor can't loop forever
    _TIMEOUT = 30             # seconds per HTTP call

    def __init__(self, token: Optional[str], base_url: Optional[str] = None,
                 email: Optional[str] = None, password: Optional[str] = None,
                 token_cache: Optional[str] = None):
        # Env resolution happens once in build_adapter(); the backend uses
        # exactly what it's handed so it's predictable and unit-testable.
        self._manual_token = (token or "").strip()
        self._email = (email or "").strip()
        self._password = (password or "").strip()
        self._token_cache = Path(token_cache) if token_cache else _DEFAULT_TOKEN_CACHE
        self._base = (base_url or os.environ.get("PLAUD_API_BASE")
                      or self._DEFAULT_BASE).rstrip("/")
        self._session = None  # lazily constructed requests.Session

    def available(self) -> bool:
        return bool(self._manual_token or self._can_mint())

    # ── token lifecycle (mint → cache → manual fallback) ──────────────────────

    @property
    def auth_mode(self) -> Optional[str]:
        """'credentials' (auto-mint), 'manual-token', or None."""
        if self._can_mint():
            return "credentials"
        return "manual-token" if self._manual_token else None

    def _can_mint(self) -> bool:
        return bool(self._email and self._password)

    def _resolve_token(self) -> str:
        """Current bearer: valid cached minted token → fresh mint → manual
        PLAUD_TOKEN. A mint failure falls back to the manual token when one is
        set (it may still be alive) instead of raising."""
        if self._can_mint():
            cached = self._load_cached_token()
            if cached:
                return cached
            try:
                return self._mint_token()
            except Exception as exc:  # noqa: BLE001 - unofficial surface
                if not self._manual_token:
                    raise
                logger.warning(
                    "plaud auth: mint failed (%s) — trying manual PLAUD_TOKEN", exc)
        return self._manual_token

    def _load_cached_token(self) -> Optional[str]:
        """Cached minted token, only if comfortably outside the refresh buffer.
        A missing/corrupt/stale cache simply means 'mint again'."""
        try:
            data = json.loads(self._token_cache.read_text(encoding="utf-8"))
            token = str(data.get("access_token") or "")
            expires_at = float(data.get("expires_at") or 0)
        except Exception:  # noqa: BLE001 - cache is disposable by design
            return None
        if token and expires_at - time.time() > _TOKEN_REFRESH_BUFFER_S:
            return token
        return None

    def _mint_token(self) -> str:
        """Mint a fresh JWT (~30-day TTL on APSE1) via ``POST /auth/access-token`` (the web
        app's own login call — form-encoded username/password). Follows the
        regional redirect once, caches the token, and resets the session so the
        next request carries the new bearer. Raises on failure; NEVER logs the
        password or the token itself."""
        body = self._post_auth()
        if isinstance(body, dict) and not body.get("access_token"):
            new_base = self._region_base(body)
            if new_base and new_base != self._base:
                logger.info("plaud auth: region redirect %s -> %s", self._base, new_base)
                self._base = new_base
                body = self._post_auth()
        token = ""
        if isinstance(body, dict):
            token = str(body.get("access_token")
                        or (body.get("data") or {}).get("access_token") or "")
        if not token:
            status = body.get("status") if isinstance(body, dict) else "?"
            msg = body.get("msg") if isinstance(body, dict) else None
            raise RuntimeError(
                f"auth/access-token failed: status={status} msg={msg!r} "
                f"(base={self._base})")
        claims = _jwt_claims(token)
        try:
            self._token_cache.parent.mkdir(parents=True, exist_ok=True)
            self._token_cache.write_text(json.dumps({
                "access_token": token,
                "issued_at": claims.get("iat"),
                "expires_at": claims.get("exp"),
                "base_url": self._base,
            }), encoding="utf-8")
        except OSError as exc:
            # No cache just means re-minting next run — not worth failing over.
            logger.warning("plaud auth: could not cache token (%s)", exc)
        self._session = None  # rebuild with the fresh bearer
        logger.info("plaud auth: minted token (expires %s)",
                    datetime.fromtimestamp(claims["exp"], tz=timezone.utc).date()
                    if claims.get("exp") else "unknown")
        return token

    def _post_auth(self):
        import requests

        resp = requests.post(
            f"{self._base}/auth/access-token",
            data={"username": self._email, "password": self._password},
            headers={"Accept": "application/json",
                     "User-Agent": "Mozilla/5.0 (harqis-work plaud ingest)"},
            timeout=self._TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()

    def token_info(self) -> dict:
        """Diagnostics (scripts/agents/diagnostics/check_plaud_token.py): active auth mode + bearer expiry."""
        info: dict = {"mode": self.auth_mode}
        try:
            token = self._resolve_token()
        except Exception as exc:  # noqa: BLE001 - diagnostics must not raise
            info["error"] = str(exc)
            return info
        exp = _jwt_claims(token).get("exp")
        if exp:
            info["expires_at"] = datetime.fromtimestamp(
                exp, tz=timezone.utc).strftime("%Y-%m-%d")
        return info

    def _get_session(self):
        if self._session is not None:
            return self._session
        token = self._resolve_token()
        if not token:
            raise RuntimeError(
                "Plaud cloud auth not configured (no PLAUD_EMAIL/PLAUD_PASSWORD "
                "and no PLAUD_TOKEN)")
        try:
            import requests
        except ImportError as e:  # requests is a core dep, but stay honest
            raise RuntimeError(
                "the 'requests' package is required for the Plaud cloud backend "
                "(pip install requests); or use the PLAUD_EXPORT_DIR folder backend"
            ) from e
        s = requests.Session()
        s.headers.update({
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            # web.plaud.ai sends a browser UA; mirror it so the unofficial
            # surface doesn't reject the call as a non-browser client.
            "User-Agent": "Mozilla/5.0 (harqis-work plaud ingest)",
        })
        self._session = s
        return s

    # Plaud's JSON envelope reports success as status 0 (some endpoints omit it).
    _SUCCESS_STATUS = (0, None)

    def _get(self, path: str, **params):
        """GET a JSON endpoint, unwrap the ``{status, msg, data}`` envelope, and
        transparently follow Plaud's regional redirect (envelope ``status -302``)
        exactly once.

        Returns the unwrapped ``data`` payload for an enveloped response, or the
        raw body otherwise. Raises on a non-success envelope so a server-side
        error is never silently read as 'no recordings'.
        """
        body = self._raw_get(path, **params)
        if not isinstance(body, dict):
            return body
        if body.get("status") in self._SUCCESS_STATUS:
            return body.get("data", body)
        # Wrong region: Plaud answers -302 and hands back the correct API host
        # (e.g. https://api-apse1.plaud.ai). Re-point and retry once; the new
        # base sticks on the instance so later calls go straight there.
        new_base = self._region_base(body)
        if new_base and new_base != self._base:
            logger.info("plaud cloud: region redirect %s -> %s", self._base, new_base)
            self._base = new_base
            body = self._raw_get(path, **params)
            if isinstance(body, dict) and body.get("status") in self._SUCCESS_STATUS:
                return body.get("data", body)
        # Expired bearer (-419): mint a fresh one and retry once. Only possible
        # with credentials; a manual-token-only setup still surfaces the error.
        if self._is_token_expired(body) and self._can_mint():
            logger.info("plaud cloud: token expired — minting a fresh one")
            self._mint_token()
            body = self._raw_get(path, **params)
            if isinstance(body, dict) and body.get("status") in self._SUCCESS_STATUS:
                return body.get("data", body)
        raise RuntimeError(
            f"api.plaud.ai error: status={body.get('status')} "
            f"msg={body.get('msg')!r} (base={self._base})"
        )

    _EXPIRED_STATUS = (-419,)

    @staticmethod
    def _is_token_expired(body) -> bool:
        if not isinstance(body, dict):
            return False
        if body.get("status") in PlaudCloudBackend._EXPIRED_STATUS:
            return True
        return "token expired" in str(body.get("msg") or "").lower()

    def _raw_get(self, path: str, **params):
        session = self._get_session()
        resp = session.get(f"{self._base}{path}", params=params, timeout=self._TIMEOUT)
        resp.raise_for_status()
        return resp.json()

    @staticmethod
    def _region_base(body: dict) -> Optional[str]:
        """Extract the correct regional API host from a -302 region-mismatch body:
        ``{"data": {"domains": {"api": "https://api-apse1.plaud.ai"}}}``."""
        data = body.get("data") if isinstance(body, dict) else None
        domains = data.get("domains") if isinstance(data, dict) else None
        api = domains.get("api") if isinstance(domains, dict) else None
        return api.rstrip("/") if isinstance(api, str) and api else None

    def list_recordings(self, since: Optional[str] = None,
                        until: Optional[str] = None) -> List[DtoPlaudRecording]:
        out: List[DtoPlaudRecording] = []
        skip = 0
        for _ in range(self._MAX_PAGES):
            data = self._get(
                "/file/simple/web",
                skip=skip, limit=self._PAGE_LIMIT,
                is_trash=0, sort_by="start_time", is_desc="true",
            )
            # `data` is already unwrapped (the recording array, or an envelope
            # nesting it); _extract_list tolerates either shape.
            items = self._extract_list(data)
            if not items:
                break
            stop = False
            for item in items:
                rec = self._normalize(item)
                # Newest-first ordering: once we pass below `since` every
                # remaining page is older, so we can stop early.
                if since and rec.started_at and rec.started_at < since:
                    stop = True
                    continue
                if _in_window(rec.started_at, since, until):
                    out.append(rec)
            if stop or len(items) < self._PAGE_LIMIT:
                break
            skip += len(items)
        logger.info("plaud cloud: %d recording(s) in window", len(out))
        return out

    def ensure_audio_local(self, rec: DtoPlaudRecording, dest_dir: str) -> Optional[str]:
        if rec.audio_path and os.path.exists(rec.audio_path):
            return rec.audio_path
        Path(dest_dir).mkdir(parents=True, exist_ok=True)
        try:
            url = self._resolve_audio_url(rec)
            if not url:
                logger.warning("plaud cloud: no download URL for %s", rec.id)
                return None
            import requests

            with requests.get(url, timeout=self._TIMEOUT, stream=True) as r:
                r.raise_for_status()
                ext = self._extension_from_url(url) or rec.audio_format or "mp3"
                dest = os.path.join(dest_dir, f"{rec.id}.{ext}")
                with open(dest, "wb") as fh:
                    for chunk in r.iter_content(chunk_size=1 << 16):
                        if chunk:
                            fh.write(chunk)
        except Exception as e:  # noqa: BLE001 — unofficial surface, stay defensive
            logger.warning("plaud cloud download failed for %s: %s", rec.id, e)
            return None
        rec.audio_path = dest
        return dest

    def _resolve_audio_url(self, rec: DtoPlaudRecording) -> Optional[str]:
        """A recording's signed URL: use one already on the DTO, else ask
        ``/file/temp-url/{id}`` (prefers WAV; falls back to whatever it returns)."""
        if rec.audio_url:
            return rec.audio_url
        if not rec.id:
            return None
        # is_opus=1 returns the ORIGINAL recording (opus/.ogg), which always
        # exists; is_opus=0 asks for a server-side WAV transcode that may not.
        # Whisper accepts opus, so prefer the original.
        data = self._get(f"/file/temp-url/{rec.id}", is_opus=1)
        if not isinstance(data, dict):
            return None
        for key in ("temp_url_opus", "temp_url", "url", "download_url"):
            val = data.get(key)
            if val:
                ext = self._extension_from_url(val)
                if ext:
                    rec.audio_format = ext
                elif key == "temp_url_opus":
                    rec.audio_format = rec.audio_format or "ogg"
                elif key == "temp_url":
                    rec.audio_format = "wav"
                return val
        return None

    @staticmethod
    def _extension_from_url(url: str) -> Optional[str]:
        suffix = Path(urlparse(url).path).suffix.lower()
        return suffix.lstrip(".") if suffix in _AUDIO_EXTS else None

    @staticmethod
    def _extract_list(body) -> list:
        """Pull the recording array out of a list response, tolerant of envelope
        drift across the unofficial surface."""
        if isinstance(body, list):
            return body
        if isinstance(body, dict):
            for key in ("data_file_list", "data", "files", "list", "items", "result"):
                val = body.get(key)
                if isinstance(val, list):
                    return val
                if isinstance(val, dict):  # e.g. {"data": {"list": [...]}}
                    for k2 in ("data_file_list", "list", "files", "items"):
                        if isinstance(val.get(k2), list):
                            return val[k2]
        return []

    @staticmethod
    def _normalize(item) -> DtoPlaudRecording:
        """Map a raw api.plaud.ai record (dict or object) to the normalized DTO.

        Field names follow the live ``/file/simple/web`` surface (id, filename,
        start_time, duration, fullname, keywords) with legacy/alternate keys kept
        as fallbacks so the mapping survives key drift. ``start_time``/``duration``
        are epoch MILLISECONDS in this API; the unit is detected once from the
        timestamp magnitude and applied to both.
        """
        def g(*keys, default=None):
            for k in keys:
                if isinstance(item, dict) and item.get(k) is not None:
                    return item[k]
                if hasattr(item, k) and getattr(item, k) is not None:
                    return getattr(item, k)
            return default

        rid = str(g("id", "file_id", "recording_id", "uuid", default="")) or None

        started_raw = g("start_time", "started_at", "created_at", "create_time", "date")
        in_ms = isinstance(started_raw, (int, float)) and started_raw > 1e12
        if isinstance(started_raw, (int, float)):
            started = _iso(datetime.fromtimestamp(
                started_raw / 1000 if in_ms else started_raw, tz=timezone.utc))
        else:
            started = started_raw if isinstance(started_raw, str) else None

        duration = g("duration", "duration_seconds", "length")
        if isinstance(duration, (int, float)):
            duration = int(duration / 1000) if in_ms else int(duration)

        # Real extension lives on `fullname` (e.g. "<id>.ogg"); fall back to an
        # explicit format field, then mp3.
        ext = os.path.splitext(str(g("fullname", default="") or ""))[1].lstrip(".").lower()
        audio_format = ext or (g("format", "audio_format", default="mp3") or "mp3").lower()

        return DtoPlaudRecording(
            id=rid,
            title=g("filename", "title", "name", default=rid),
            started_at=started,
            duration_seconds=duration,
            audio_url=g("audio_url", "download_url", "url"),
            audio_format=audio_format,
            transcript=g("transcript", "transcription", "transcript_text", "trans_result"),
            summary=g("summary", "summary_text", "ai_summary"),
            tags=list(g("keywords", "tags", default=[]) or []),
            origin="cloud",
        )


# ── folder (fallback, fully supported) ────────────────────────────────────────

class PlaudFolderBackend(PlaudBackend):
    """Reads recordings the user exported from the Plaud desktop app into a
    watched folder. Audio files are paired with sibling transcript/summary text
    files by filename stem."""

    name = "folder"

    def __init__(self, export_dir: Optional[str]):
        self._dir = (export_dir or "").strip()

    def available(self) -> bool:
        return bool(self._dir) and os.path.isdir(self._dir)

    def list_recordings(self, since: Optional[str] = None,
                        until: Optional[str] = None) -> List[DtoPlaudRecording]:
        if not self.available():
            return []
        out: List[DtoPlaudRecording] = []
        for path in sorted(Path(self._dir).rglob("*")):
            if not path.is_file() or path.suffix.lower() not in _AUDIO_EXTS:
                continue
            rec = self._from_audio_file(path)
            if _in_window(rec.started_at, since, until):
                out.append(rec)
        logger.info("plaud folder: %d recording(s) in window from %s", len(out), self._dir)
        return out

    def ensure_audio_local(self, rec: DtoPlaudRecording, dest_dir: str) -> Optional[str]:
        # Folder recordings are already local; nothing to download.
        return rec.audio_path if rec.audio_path and os.path.exists(rec.audio_path) else None

    def _from_audio_file(self, path: Path) -> DtoPlaudRecording:
        stem = path.stem
        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        transcript, summary = self._sidecar_text(path)
        # Deterministic id so re-runs upsert rather than duplicate.
        rid = f"{mtime.strftime('%Y%m%d')}-{_slug(stem)}"
        return DtoPlaudRecording(
            id=rid,
            title=stem,
            started_at=_iso(mtime),
            audio_path=str(path),
            audio_format=path.suffix.lower().lstrip("."),
            transcript=transcript,
            summary=summary,
            origin="folder",
        )

    def _sidecar_text(self, audio: Path) -> tuple[Optional[str], Optional[str]]:
        """Find sibling transcript/summary text files sharing the audio stem."""
        transcript = summary = None
        stem = audio.stem
        for sibling in audio.parent.iterdir():
            if not sibling.is_file() or sibling.suffix.lower() not in _TRANSCRIPT_EXTS:
                continue
            sib_stem = sibling.stem
            if not sib_stem.startswith(stem):
                continue
            try:
                text = sibling.read_text(encoding="utf-8", errors="replace").strip()
            except OSError:
                continue
            if any(sib_stem.lower().endswith(sfx) for sfx in _SUMMARY_SUFFIXES):
                summary = text
            elif sib_stem == stem and transcript is None:
                transcript = text
        return transcript, summary


# ── adapter (cloud → folder) ──────────────────────────────────────────────────

class PlaudAdapter:
    """Acquisition facade: try cloud first, fall back to the export folder."""

    def __init__(self, cloud: PlaudCloudBackend, folder: PlaudFolderBackend):
        self._cloud = cloud
        self._folder = folder

    def _active_backend(self) -> Optional[PlaudBackend]:
        if self._cloud.available():
            return self._cloud
        if self._folder.available():
            return self._folder
        return None

    @property
    def active_backend(self) -> Optional[PlaudBackend]:
        """The backend that would actually serve data (cloud if ready, else
        folder). Exposed for diagnostics that need to call it DIRECTLY and see
        a real error — `list_recordings` deliberately swallows a cloud failure
        and falls back to the folder, which would mask a bad/expired token."""
        return self._active_backend()

    def list_recordings(self, since: Optional[str] = None,
                        until: Optional[str] = None) -> List[DtoPlaudRecording]:
        """List recordings in [since, until]. Tries cloud, then folder.

        Args:
            since: inclusive lower bound, ISO-8601 (e.g. "2026-06-08T00:00:00").
            until: inclusive upper bound, ISO-8601.
        """
        if self._cloud.available():
            try:
                return self._cloud.list_recordings(since, until)
            except Exception as e:  # noqa: BLE001 — unofficial cloud surface
                logger.warning(
                    "plaud cloud unavailable (%s) — falling back to export folder", e
                )
        return self._folder.list_recordings(since, until)

    def ensure_audio_local(self, rec: DtoPlaudRecording, dest_dir: str) -> Optional[str]:
        backend = self._cloud if rec.origin == "cloud" else self._folder
        return backend.ensure_audio_local(rec, dest_dir)

    @property
    def status(self) -> dict:
        return {
            "cloud_ready": self._cloud.available(),
            "folder_ready": self._folder.available(),
            "active": (self._active_backend().name if self._active_backend() else None),
        }


def build_adapter(config) -> PlaudAdapter:
    """Construct a :class:`PlaudAdapter` from an app config (``apps.plaud.config.CONFIG``).

    Reads ``app_data.email``/``password``/``token``/``export_dir`` with
    ``PLAUD_EMAIL`` / ``PLAUD_PASSWORD`` / ``PLAUD_TOKEN`` / ``PLAUD_EXPORT_DIR``
    env vars as fallbacks. Credentials (auto-mint) are preferred over the
    manual token — see :class:`PlaudCloudBackend`.
    """
    app_data = getattr(config, "app_data", {}) or {}
    token = app_data.get("token") or os.environ.get("PLAUD_TOKEN", "")
    email = app_data.get("email") or os.environ.get("PLAUD_EMAIL", "")
    password = app_data.get("password") or os.environ.get("PLAUD_PASSWORD", "")
    api_base = app_data.get("api_base") or os.environ.get("PLAUD_API_BASE", "")
    export_dir = app_data.get("export_dir") or os.environ.get("PLAUD_EXPORT_DIR", "")
    return PlaudAdapter(
        PlaudCloudBackend(token, base_url=api_base or None,
                          email=email, password=password),
        PlaudFolderBackend(export_dir),
    )
