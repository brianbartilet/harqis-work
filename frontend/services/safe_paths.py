"""Containment checks and signed download tokens for local references."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from config import get_settings
from web import REPO_ROOT


@dataclass(frozen=True)
class ReferenceLink:
    label: str
    kind: str
    href: str | None
    reason: str = ""


def allowed_reference_roots(corpus_root: Path) -> tuple[Path, ...]:
    roots = [corpus_root.resolve(), REPO_ROOT.resolve()]
    configured = get_settings().hfl_reference_allowed_roots
    for raw in configured.split(os.pathsep):
        if raw.strip():
            roots.append(Path(raw.strip()).expanduser().resolve())
    unique: list[Path] = []
    for root in roots:
        if root not in unique:
            unique.append(root)
    return tuple(unique)


def is_within_roots(path: Path, roots: tuple[Path, ...]) -> bool:
    resolved = path.resolve()
    for root in roots:
        try:
            resolved.relative_to(root.resolve())
            return True
        except ValueError:
            continue
    return False


def safe_relative_file(root: Path, relative_path: str, suffix: str | None = None) -> Path | None:
    candidate = (root / unquote(relative_path or "")).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        return None
    if not candidate.is_file() or (suffix and candidate.suffix.lower() != suffix.lower()):
        return None
    return candidate


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(get_settings().secret_key, salt="hfl-reference-download")


def make_download_token(path: Path) -> str:
    return _serializer().dumps(str(path.resolve()))


def load_download_token(token: str, roots: tuple[Path, ...], max_age: int = 86_400) -> Path | None:
    try:
        raw = _serializer().loads(token, max_age=max_age)
    except (BadSignature, SignatureExpired):
        return None
    path = Path(raw).resolve()
    if not path.is_file() or not is_within_roots(path, roots):
        return None
    return path


def resolve_reference(
    reference: str,
    *,
    source_document: Path,
    corpus_root: Path,
) -> ReferenceLink:
    raw = (reference or "").strip()
    parsed = urlparse(raw)
    if parsed.scheme.lower() in {"http", "https"}:
        return ReferenceLink(label=raw, kind="external", href=raw)

    if parsed.scheme.lower() == "file":
        uri_path = f"//{parsed.netloc}{parsed.path}" if parsed.netloc else parsed.path
        local_raw = url2pathname(unquote(uri_path))
    else:
        local_raw = raw
    candidate = Path(local_raw).expanduser()
    candidates = [candidate] if candidate.is_absolute() else [
        source_document.parent / candidate,
        REPO_ROOT / candidate,
    ]
    resolved = next((path.resolve() for path in candidates if path.exists()), candidates[0].resolve())
    roots = allowed_reference_roots(corpus_root)
    if not resolved.exists():
        return ReferenceLink(label=Path(local_raw).name or raw, kind="blocked", href=None, reason="missing")
    if not resolved.is_file():
        return ReferenceLink(label=resolved.name, kind="blocked", href=None, reason="not a file")
    if not is_within_roots(resolved, roots):
        return ReferenceLink(label=resolved.name, kind="blocked", href=None, reason="outside allowed roots")
    token = make_download_token(resolved)
    return ReferenceLink(
        label=resolved.name,
        kind="download",
        href=f"/hfl-corpus/references/{token}/download",
    )
