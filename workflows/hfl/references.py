"""
workflows/hfl/references.py

Resolver for HFL entry `references` (see workflows/hfl/dto/entry.py).

An HFL entry may carry references — URLs or host file paths pointing at
the source material behind the moment. `summarize_hfl_week` calls
`resolve_references` to fetch bounded excerpts and inject them into the
weekly rollup prompt, so the summary is grounded in the actual material,
not just the one-line moment. This is what keeps references from being
"dead weight" per docs/MANIFESTO.md §1 — every captured reference has a
Distill consumer within one hop.

Hard bounds (the privacy/cost tension flagged in the spec):
  - http(s) only for URLs; everything else is treated as a local path.
  - per-reference byte cap (`max_bytes`) and a total cap across all
    references (`max_total`) — the resolved text is sent to Anthropic.
  - text-only: a file that looks binary (NUL bytes) is skipped.
  - best-effort: any failure yields ok=False with a reason; the caller
    annotates "(unresolved: …)" and the weekly beat never breaks.
  - NOT path-allowlisted (per the approved spec): any readable text file
    is resolvable. Tighten here if that changes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

import httpx

from core.utilities.logging.custom_logger import create_logger

_log = create_logger("hfl.references")

_DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def _looks_binary(blob: bytes) -> bool:
    """A NUL byte in the first 4 KiB is a strong binary signal."""
    return b"\x00" in blob[:4096]


def _resolve_one(ref: str, *, timeout: float, max_bytes: int) -> dict[str, Any]:
    ref = (ref or "").strip()
    if not ref:
        return {"ref": ref, "ok": False, "content": "", "reason": "empty"}

    if ref.lower().startswith(("http://", "https://")):
        try:
            with httpx.Client(
                timeout=timeout,
                follow_redirects=True,
                headers={"User-Agent": _DEFAULT_UA, "Accept": "*/*"},
            ) as c:
                r = c.get(ref)
            r.raise_for_status()
            ctype = r.headers.get("content-type", "")
            blob = r.content[:max_bytes]
            if _looks_binary(blob):
                return {"ref": ref, "ok": False, "content": "",
                        "reason": f"non-text content ({ctype or 'unknown'})"}
            text = blob.decode(r.encoding or "utf-8", errors="replace")
            return {"ref": ref, "ok": True, "content": text.strip(),
                    "reason": f"http {r.status_code}, {len(blob)}B"}
        except httpx.HTTPStatusError as exc:
            sc = exc.response.status_code if exc.response is not None else "?"
            return {"ref": ref, "ok": False, "content": "",
                    "reason": f"http {sc}"}
        except Exception as exc:  # noqa: BLE001 - network/DNS/TLS all best-effort
            return {"ref": ref, "ok": False, "content": "",
                    "reason": f"fetch error: {type(exc).__name__}"}

    # Local host path.
    try:
        p = Path(ref).expanduser()
        if not p.exists():
            return {"ref": ref, "ok": False, "content": "", "reason": "not found"}
        if not p.is_file():
            return {"ref": ref, "ok": False, "content": "", "reason": "not a file"}
        blob = p.read_bytes()[:max_bytes]
        if _looks_binary(blob):
            return {"ref": ref, "ok": False, "content": "", "reason": "binary file"}
        text = blob.decode("utf-8", errors="replace")
        return {"ref": ref, "ok": True, "content": text.strip(),
                "reason": f"file, {len(blob)}B"}
    except OSError as exc:
        return {"ref": ref, "ok": False, "content": "",
                "reason": f"read error: {exc.__class__.__name__}"}


def resolve_references(
    refs: Iterable[str],
    *,
    timeout: float = 10.0,
    max_bytes: int = 20_000,
    max_total: int = 60_000,
) -> list[dict[str, Any]]:
    """Resolve references to bounded text excerpts (order-stable, deduped).

    Returns one dict per unique reference:
        {"ref": str, "ok": bool, "content": str, "reason": str}

    `content` is truncated so the cumulative resolved text never exceeds
    `max_total`. Once the budget is spent, remaining references resolve
    metadata-only (ok=False, reason="budget exhausted") so the entry still
    records that they exist without ballooning the prompt.
    """
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    spent = 0
    for raw in refs or []:
        ref = (raw or "").strip()
        if not ref or ref in seen:
            continue
        seen.add(ref)
        if spent >= max_total:
            out.append({"ref": ref, "ok": False, "content": "",
                        "reason": "budget exhausted"})
            continue
        res = _resolve_one(ref, timeout=timeout, max_bytes=max_bytes)
        if res["ok"] and res["content"]:
            remaining = max_total - spent
            if len(res["content"]) > remaining:
                res["content"] = res["content"][:remaining]
                res["reason"] += " (truncated to total budget)"
            spent += len(res["content"])
        if not res["ok"]:
            _log.info("hfl.references: unresolved %s — %s", ref, res["reason"])
        out.append(res)
    return out
