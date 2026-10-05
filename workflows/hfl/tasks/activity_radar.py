"""Analyze recent HFL entries against related history and optionally notify."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import re
import socket
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import quote

import httpx

from core.apps.es_logging.app.elasticsearch import log_result
from core.apps.sprout.app.celery import SPROUT
from core.utilities.logging.custom_logger import create_logger

from workflows.hfl.dto import HflEntry
from workflows.hfl.es_store import query_hfl_entries_status
from workflows.hfl.persistence import submit_hfl_entry
from workflows.hfl.prompts import load_prompt
from workflows.hfl.tasks.capture import resolve_corpus_dir

_log = create_logger("hfl.activity_radar")
_DEFAULT_MODEL = "claude-haiku-4-5-20251001"
_SECTIONS = {
    "critical_risks": "Critical risks",
    "missed_commitments": "Possibly missed commitments",
    "current_focus": "Current focus",
    "related_history": "Related historical evidence",
    "recommendations": "Recommendations and improvements",
    "contradictions": "Contradictions or changed assumptions",
}
_ENTRY_RE = re.compile(r"^## (.+?)\s*$", re.MULTILINE)
_SECRET_PATTERNS = (
    re.compile(r"(?i)(authorization\s*:\s*bearer\s+)[^\s]+"),
    re.compile(r"(?i)((?:api[_-]?key|access[_-]?token|refresh[_-]?token|token|password|secret)\s*[:=]\s*)[^\s&]+"),
    re.compile(r"(?i)([?&](?:token|key|api_key|signature|sig)=)[^&#\s]+"),
)


def redact_secrets(value: Any) -> str:
    text = str(value or "")
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(r"\1[REDACTED]", text)
    return text


def state_path() -> Path:
    root = os.environ.get("HARQIS_DATA_ROOT", "").strip()
    base = Path(root).expanduser() / "runtime" if root else Path(__file__).resolve().parents[3] / "logs"
    return (base / "activity-radar" / "state.json").resolve()


def load_state(path: Path | None = None) -> dict[str, Any]:
    target = path or state_path()
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            data.setdefault("version", 1)
            data.setdefault("findings", {})
            return data
    except (OSError, ValueError):
        pass
    return {"version": 1, "last_success_at": None, "findings": {}}


def save_state(state: dict[str, Any], path: Path | None = None) -> None:
    target = path or state_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(temporary, target)


def _parse_when(row: dict[str, Any]) -> datetime | None:
    raw = row.get("when") or row.get("entry_date")
    if not raw:
        return None
    try:
        value = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        return value if value.tzinfo else value.astimezone()
    except ValueError:
        return None


def _row(entry: HflEntry, path: str = "") -> dict[str, Any]:
    return {
        "when": entry.when.isoformat() if entry.when else None,
        "moment": entry.moment,
        "what_happened": entry.what_happened,
        "why_it_stayed": entry.why_it_stayed,
        "possible_use": entry.possible_use,
        "tags": list(entry.tags),
        "references": list(entry.references),
        "source": entry.source,
        "entry_id": entry.entry_id,
        "path": path,
    }


def _corpus_rows(since: datetime, limit: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    corpus = resolve_corpus_dir()
    for path in sorted(corpus.glob("*.md"), reverse=True):
        try:
            if datetime.strptime(path.stem, "%Y-%m-%d").date() < since.date():
                break
            text = path.read_text(encoding="utf-8")
        except (OSError, ValueError):
            continue
        matches = list(_ENTRY_RE.finditer(text))
        for index, match in enumerate(matches):
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            entry = HflEntry.from_markdown(match.group(1), text[match.end():end])
            when = entry.when
            if when and (when if when.tzinfo else when.astimezone()) >= since:
                rows.append(_row(entry, str(path)))
            if len(rows) >= limit:
                return rows
    return rows


def retrieve_entries(
    since: datetime, *, query: str = "", tags: list[str] | None = None,
    source: str | None = None, limit: int = 120,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Return exactly-windowed entries, falling back to canonical Markdown."""
    degraded: list[str] = []
    result = query_hfl_entries_status(
        query=query, since=since.date().isoformat(), tags=tags, source=source, limit=limit,
    )
    rows = list(result.rows)
    if not result.available:
        degraded.append("Elasticsearch unavailable; canonical Markdown fallback used")
        rows = _corpus_rows(since, limit)
    filtered = []
    for row in rows:
        when = _parse_when(row)
        row_tags = {str(tag).strip().lower().lstrip("#") for tag in row.get("tags") or []}
        wanted_tags = {str(tag).strip().lower().lstrip("#") for tag in tags or []}
        haystack = " ".join(str(row.get(key, "")) for key in ("moment", "what_happened", "why_it_stayed", "possible_use")).lower()
        if not when or when < since or row.get("source") == "activity-radar":
            continue
        if source and str(row.get("source", "")).lower() != source.lower():
            continue
        if wanted_tags and not wanted_tags.issubset(row_tags):
            continue
        if query and query.lower() not in haystack and query.lower().lstrip("#") not in row_tags:
            continue
        filtered.append(row)
    return filtered[:limit], degraded


def infer_topics(rows: Iterable[dict[str, Any]], limit: int = 8) -> list[str]:
    counts: dict[str, int] = {}
    stop = {"manual-entry", "notes", "reminders", "fyi", "retrospective", "activity-radar"}
    for row in rows:
        for tag in row.get("tags") or []:
            value = str(tag).strip().lower().lstrip("#")
            if value and value not in stop:
                counts[value] = counts.get(value, 0) + 3
        for word in re.findall(r"[A-Za-z][A-Za-z0-9_-]{3,}", str(row.get("moment", "")).lower()):
            if word not in {"with", "from", "that", "this", "have", "about"}:
                counts[word] = counts.get(word, 0) + 1
    return [key for key, _ in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:limit]]


def _evidence_rows(recent: list[dict[str, Any]], history: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    compact, lookup = [], {}
    for prefix, rows in (("N", recent), ("H", history)):
        for index, row in enumerate(rows, 1):
            eid = f"{prefix}{index}"
            safe_row = {
                **row,
                **{key: redact_secrets(row.get(key, "")) for key in ("moment", "what_happened", "why_it_stayed", "possible_use")},
                "source": redact_secrets(row.get("source", "")),
                "tags": [redact_secrets(value) for value in (row.get("tags") or [])],
                "references": [redact_secrets(value) for value in (row.get("references") or [])],
            }
            item = {
                "id": eid, "when": safe_row.get("when"), "source": safe_row.get("source"),
                "moment": safe_row["moment"][:300],
                "details": safe_row["what_happened"][:1500],
                "possible_use": safe_row["possible_use"][:500],
                "tags": (safe_row.get("tags") or [])[:12],
                "references": safe_row["references"][:8],
            }
            compact.append(item)
            lookup[eid] = safe_row
    return compact, lookup


def synthesize_findings(
    evidence: list[dict[str, Any]], *, context: str = "", model: str = _DEFAULT_MODEL,
    cfg_id: str = "ANTHROPIC", max_tokens: int = 2200,
) -> dict[str, Any]:
    from apps.antropic.config import get_config as get_anthropic_config
    from apps.antropic.references.web.base_api_service import BaseApiServiceAnthropic
    from workflows.hfl.tasks.ingest_git import _parse_model_json

    client = BaseApiServiceAnthropic(get_anthropic_config(cfg_id))
    if not getattr(client, "base_client", None):
        raise RuntimeError("Anthropic client is not configured")
    response = client.send_message(
        prompt=json.dumps({"additional_context": redact_secrets(context), "evidence": evidence}, ensure_ascii=False),
        system=load_prompt("activity_radar").strip(), model=model, max_tokens=max_tokens,
    )
    text = response.content[0].text if response and response.content else ""
    parsed = _parse_model_json(text)
    if not isinstance(parsed, dict) or not isinstance(parsed.get("findings"), list):
        raise RuntimeError("Activity radar returned invalid JSON")
    return parsed


def validate_findings(
    data: dict[str, Any], valid_ids: set[str],
    *, lookup: dict[str, dict[str, Any]] | None = None, include_matrix: bool = False, include_boards: bool = False,
) -> list[dict[str, Any]]:
    findings = []
    for raw in data.get("findings", []):
        if not isinstance(raw, dict) or raw.get("category") not in _SECTIONS:
            continue
        evidence = [str(x) for x in raw.get("evidence", []) if str(x) in valid_ids]
        latest_evidence = [
            str(x) for x in raw.get("latest_evidence", [])
            if str(x) in valid_ids and str(x) in evidence
        ]
        severity = str(raw.get("severity", "low")).lower()
        if severity not in {"critical", "high", "medium", "low"}:
            severity = "low"
        if severity in {"critical", "high"} and not evidence:
            continue
        status = str(raw.get("status", "uncertain")).strip().lower()
        if status not in {"open", "resolved", "uncertain"}:
            status = "uncertain"
        resolution_check = str(raw.get("resolution_check", "")).strip()
        claimed_latest_is_current = True
        if lookup:
            timestamps = {
                eid: _parse_when(lookup[eid])
                for eid in evidence
                if eid in lookup
            }
            dated = [when for when in timestamps.values() if when is not None]
            if dated:
                newest = max(dated)
                claimed_latest_is_current = bool(latest_evidence) and all(
                    timestamps.get(eid) == newest for eid in latest_evidence
                )
        if severity in {"critical", "high"} and (
            status != "open"
            or not resolution_check
            or not latest_evidence
            or not any(eid.startswith("N") for eid in latest_evidence)
            or not claimed_latest_is_current
        ):
            continue
        confidence = str(raw.get("confidence", "medium")).lower()
        if confidence not in {"high", "medium", "low"}:
            confidence = "medium"
        finding = {
            "category": raw["category"], "severity": severity,
            "confidence": confidence,
            "title": str(raw.get("title", "Untitled finding")).strip()[:240],
            "observation": str(raw.get("observation", "")).strip(),
            "inference": str(raw.get("inference", "")).strip(),
            "recommendation": str(raw.get("recommendation", "")).strip(),
            "evidence": evidence,
            "status": status,
            "latest_evidence": latest_evidence,
            "resolution_check": resolution_check,
        }
        if include_matrix:
            from workflows.hfl.timeline_store import validate_matrix
            try:
                finding.update(validate_matrix(raw))
            except ValueError:
                finding.update(validate_matrix({}))
        if include_boards:
            from workflows.hfl.intent_boards import board_ids
            finding['board_ids'] = board_ids(raw.get('board_ids', []))
        canonical = json.dumps({k: finding[k] for k in ("category", "title", "evidence")}, sort_keys=True)
        finding["fingerprint"] = hashlib.sha256(canonical.encode()).hexdigest()[:16]
        finding["evidence_signature"] = hashlib.sha256("|".join(evidence).encode()).hexdigest()[:12]
        findings.append(finding)
    return findings


def bind_evidence_signatures(findings: list[dict[str, Any]], lookup: dict[str, dict[str, Any]]) -> None:
    """Bind suppression to cited content, not merely stable evidence IDs."""
    for finding in findings:
        payload = [lookup[eid] for eid in finding["evidence"] if eid in lookup]
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
        finding["evidence_signature"] = hashlib.sha256(canonical.encode()).hexdigest()[:12]


def select_notifications(findings: list[dict[str, Any]], state: dict[str, Any]) -> list[dict[str, Any]]:
    selected = []
    previous = state.get("findings", {})
    for finding in findings:
        old = previous.get(finding["fingerprint"], {})
        unchanged = old.get("evidence_signature") == finding["evidence_signature"]
        if old.get("status") == "resolved" and unchanged:
            continue
        if old.get("status") == "dismissed" and finding["severity"] != "critical" and unchanged:
            continue
        promoted_to_high = (
            finding["severity"] == "high"
            and old.get("severity") in {"medium", "low"}
        )
        if (
            finding["severity"] == "critical"
            or not old
            or old.get("evidence_signature") != finding["evidence_signature"]
            or promoted_to_high
        ):
            selected.append(finding)
    return selected


def render_markdown(findings: list[dict[str, Any]], lookup: dict[str, dict[str, Any]], degraded: list[str] | None = None) -> str:
    if not findings:
        text = "No new material findings."
    else:
        blocks = ["# HFL Activity Radar"]
        for key, title in _SECTIONS.items():
            section = [f for f in findings if f["category"] == key]
            if not section:
                continue
            blocks.append(f"\n## {title}")
            for finding in section:
                blocks.append(f"\n### [{finding['severity'].upper()} · {finding['confidence']} confidence] {finding['title']} `{finding['fingerprint']}`")
                if finding["observation"]:
                    blocks.append(f"**Fact:** {finding['observation']}")
                if finding["inference"]:
                    blocks.append(f"**Inference:** {finding['inference']}")
                if finding["recommendation"]:
                    blocks.append(f"**Recommendation:** {finding['recommendation']}")
                blocks.append("**Evidence:** " + ", ".join(finding["evidence"]))
        blocks.append("\n## Evidence")
        used = dict.fromkeys(eid for finding in findings for eid in finding["evidence"])
        for eid in used:
            row = lookup[eid]
            refs = "; ".join(str(x) for x in (row.get("references") or [])[:3])
            suffix = f" — {refs}" if refs else ""
            source = redact_secrets(row.get("source", "unknown"))
            blocks.append(
                f"- **{eid}** {row.get('when', '')} [{source}] "
                f"{row.get('moment', '')}{suffix}"
            )
        text = "\n".join(blocks)
    if degraded:
        text += "\n\n> Partial report: " + "; ".join(degraded)
    return text


def _compact_plain_text(value: Any, *, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if not text:
        return "Not provided."
    if len(text) <= limit:
        return text
    candidate = text[:limit].rstrip()
    sentence_end = max(candidate.rfind(". "), candidate.rfind("! "), candidate.rfind("? "))
    if sentence_end >= min(60, limit // 2):
        return candidate[: sentence_end + 1]
    candidate = text[: max(0, limit - 1)].rstrip()
    word_end = candidate.rfind(" ")
    if word_end > 0:
        candidate = candidate[:word_end].rstrip(" ,;:-")
    return candidate.rstrip(".!?") + "."


def _telegram_evidence_summary(
    finding: dict[str, Any], lookup: dict[str, dict[str, Any]], *, limit: int = 140,
) -> str:
    ids = finding.get("latest_evidence") or finding.get("evidence") or []
    summaries: list[str] = []
    for eid in ids[:2]:
        row = lookup.get(str(eid), {})
        if not row:
            continue
        when = _parse_when(row)
        date = f"{when.strftime('%b')} {when.day}" if when else "Undated"
        source = _compact_plain_text(
            redact_secrets(row.get("source") or "unknown"), limit=30
        )
        moment = _compact_plain_text(row.get("moment"), limit=110)
        summaries.append(f"{date} {source} — {moment}")
    if not summaries:
        return "See the linked corpus report."
    return _compact_plain_text("; ".join(summaries), limit=limit)


def render_telegram_message(
    findings: list[dict[str, Any]],
    degraded: list[str] | None = None,
    *,
    max_findings: int | None = None,
    lookup: dict[str, dict[str, Any]] | None = None,
) -> str:
    """Render urgent findings as a compact, mobile-scannable plain-text message."""
    priority = {"critical": 0, "high": 1}
    findings = sorted(
        (finding for finding in findings if finding["severity"] in priority),
        key=lambda finding: priority[finding["severity"]],
    )
    visible = findings if max_findings is None else findings[:max(0, max_findings)]
    if not findings:
        text = "No high-priority findings."
    else:
        noun = "FINDING" if len(findings) == 1 else "FINDINGS"
        count_line = f"{len(findings)} HIGH-PRIORITY {noun}"
        if len(visible) < len(findings):
            count_line += f" (SHOWING {len(visible)})"
        blocks = [f"HFL ACTIVITY RADAR\n{count_line}"]
        for index, finding in enumerate(visible, 1):
            severity = finding["severity"].upper()
            icon = "🚨" if finding["severity"] == "critical" else "⚠️"
            title = _compact_plain_text(finding["title"], limit=96)
            lines = [f"{index}. {icon} {severity} — {title}"]
            lines.append(
                "WHAT: " + _compact_plain_text(finding["observation"], limit=150)
            )
            lines.append(
                "WHY: " + _compact_plain_text(finding["inference"], limit=150)
            )
            lines.append(
                "NEXT: " + _compact_plain_text(finding["recommendation"], limit=150)
            )
            lines.append(
                "SOURCE: " + _telegram_evidence_summary(finding, lookup or {})
            )
            blocks.append("\n".join(lines))
        if len(visible) < len(findings):
            blocks.append(
                f"MORE: {len(findings) - len(visible)} additional findings are in "
                "the linked HFL entry."
            )
        text = "\n\n".join(blocks)
    if degraded:
        partial = "; ".join(
            _compact_plain_text(note, limit=120) for note in degraded[:3]
        )
        if len(degraded) > 3:
            partial += f"; +{len(degraded) - 3} more"
        text += "\n\nPARTIAL REPORT: " + partial
    return text


def _valid_web_hostname(hostname: str) -> bool:
    try:
        ipaddress.ip_address(hostname)
        return True
    except ValueError:
        pass
    try:
        socket.inet_aton(hostname)
    except OSError:
        pass
    else:
        return False
    if len(hostname) > 253:
        return False
    return all(
        re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label)
        for label in hostname.split(".")
    )


def _validated_web_origin(configured: str) -> str:
    if (
        not configured
        or len(configured) > 320
        or any(not 0x21 <= ord(char) <= 0x7E for char in configured)
        or any(char in configured for char in ("\\", "?", "#", "@"))
    ):
        raise RuntimeError("HFL_CORPUS_WEB_URL must contain a canonical web origin")
    try:
        parsed = httpx.URL(configured)
    except (httpx.InvalidURL, ValueError) as exc:
        raise RuntimeError("HFL_CORPUS_WEB_URL has an invalid authority") from exc
    hostname = parsed.host
    if (
        parsed.scheme not in {"http", "https"}
        or not hostname
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or parsed.username
        or parsed.password
        or (parsed.port is not None and not 1 <= parsed.port <= 65535)
        or not _valid_web_hostname(hostname)
    ):
        raise RuntimeError("HFL_CORPUS_WEB_URL must contain a canonical web origin")
    canonical = str(parsed)
    if canonical.endswith("/"):
        canonical = canonical[:-1]
    if configured not in {canonical, f"{canonical}/"}:
        raise RuntimeError("HFL_CORPUS_WEB_URL must use its canonical spelling")
    return canonical


def _corpus_web_origin() -> str:
    return _validated_web_origin(os.environ.get("HFL_CORPUS_WEB_URL", ""))


def corpus_document_url(
    writeback: dict[str, Any], *, fallback_filename: str = "",
) -> str:
    filename = Path(str(writeback.get("path") or "")).name or fallback_filename
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}\.md", filename):
        raise RuntimeError("HFL writeback did not identify a daily Markdown document")
    return f"{_corpus_web_origin()}/hfl-corpus/document/{quote(filename, safe='')}"


def _notify(text: str) -> list[int]:
    from apps.telegram.config import CONFIG as telegram_config
    from apps.telegram.references.web.api.messages import ApiServiceTelegramMessages
    chat_id = telegram_config.app_data.get("default_chat_id")
    if not chat_id:
        raise RuntimeError("Telegram default_chat_id is missing")
    chunks: list[str] = []
    remaining = text.strip()
    while remaining:
        if len(remaining) <= 3900:
            chunks.append(remaining)
            break
        split = remaining.rfind("\n\n", 0, 3900)
        if split < 1000:
            split = remaining.rfind("\n", 0, 3900)
        if split < 1000:
            split = 3900
        chunks.append(remaining[:split].rstrip())
        remaining = remaining[split:].lstrip()
    message_ids: list[int] = []
    for index, chunk in enumerate(chunks, 1):
        prefix = f"HFL Activity Radar ({index}/{len(chunks)})\n\n" if len(chunks) > 1 else ""
        result = ApiServiceTelegramMessages(telegram_config).send_message(
            chat_id=chat_id, text=prefix + chunk
        )
        message_id = result.get("message_id") if isinstance(result, dict) else None
        if isinstance(message_id, bool) or not isinstance(message_id, int) or message_id <= 0:
            raise RuntimeError(
                f"Telegram sendMessage response for chunk {index}/{len(chunks)} "
                "did not contain a valid message_id"
            )
        message_ids.append(message_id)
    return message_ids


def _writeback(
    text: str, now: datetime, *, dedup_key: str | None = None,
) -> dict[str, Any]:
    entry = HflEntry(
        when=now, moment="HFL activity radar retrospective", what_happened=text,
        why_it_stayed="Retains a point-in-time review of current work and risks.",
        possible_use="Use these findings to prioritize follow-up work.",
        tags=("fyi", "retrospective", "activity-radar"), source="activity-radar", synthesized=True,
    )
    return submit_hfl_entry(
        entry,
        source="activity-radar",
        synthesized=True,
        dedup_key=dedup_key,
        replace_duplicate=bool(dedup_key),
    )


def scheduled_dedup_key(state: dict[str, Any], now: datetime) -> str:
    """Identify one scheduled daily window; same-day retries replace it."""
    marker = str(state.get("last_success_at") or "first-run")
    identity = f"activity-radar-window-v1:{now.date().isoformat()}:{marker}"
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
    return f"activity-radar:{digest}"


def record_activity_radar_feedback(fingerprint: str, status: str, *, path: Path | None = None, dry_run: bool = False) -> dict[str, Any]:
    if status not in {"useful", "dismissed", "resolved"}:
        raise ValueError("status must be useful, dismissed, or resolved")
    state = load_state(path)
    if fingerprint not in state["findings"]:
        raise KeyError(f"unknown finding fingerprint: {fingerprint}")
    if not dry_run:
        state["findings"][fingerprint]["status"] = status
        save_state(state, path)
    return {"fingerprint": fingerprint, "status": status, "dry_run": dry_run}


def run_activity_radar(
    *, scheduled: bool = False, recent_hours: int = 8, retrospective_days: int = 90,
    query: str = "", tags: list[str] | None = None, source: str | None = None,
    context: str = "", model: str = _DEFAULT_MODEL, cfg_id__anthropic: str = "ANTHROPIC",
    notify: bool | None = None, save_to_hfl: bool = False, dry_run: bool = False,
    state_file: Path | None = None, now: datetime | None = None,
    synthesizer: Callable[..., dict[str, Any]] = synthesize_findings,
) -> dict[str, Any]:
    now = now or datetime.now().astimezone()
    state = load_state(state_file)
    if scheduled:
        marker = _parse_when({"when": state.get("last_success_at")})
        since = marker or now - timedelta(hours=48)
        since = max(since, now - timedelta(hours=48))
    else:
        since = now - timedelta(hours=max(1, recent_hours))
    recent, degraded = retrieve_entries(since, query=query, tags=tags, source=source)
    if not recent:
        if scheduled and not dry_run and not degraded:
            state["last_success_at"] = now.astimezone(timezone.utc).isoformat()
            save_state(state, state_file)
        status = "partial" if degraded else "no-findings"
        return {"status": status, "text": render_markdown([], {}, degraded), "recent_count": 0, "degraded": degraded}

    topics = infer_topics(recent)
    history_since = now - timedelta(days=max(1, retrospective_days))
    history: list[dict[str, Any]] = []
    def identity(row: dict[str, Any]) -> tuple[Any, ...]:
        return (row.get("entry_id") or "", row.get("when") or "", row.get("source") or "", row.get("moment") or "")
    seen = {identity(item) for item in recent}
    for topic in topics[:5] or [query]:
        if not topic:
            continue
        rows, notes = retrieve_entries(history_since, query=topic, tags=tags, source=source, limit=30)
        degraded.extend(note for note in notes if note not in degraded)
        for row in rows:
            if identity(row) not in seen:
                history.append(row)
                seen.add(identity(row))
            if len(history) >= 60:
                break
    evidence, lookup = _evidence_rows(recent[:40], history[:60])
    try:
        raw = synthesizer(evidence, context=context, model=model, cfg_id=cfg_id__anthropic)
        findings = validate_findings(raw, set(lookup), lookup=lookup)
        bind_evidence_signatures(findings, lookup)
    except Exception as exc:
        degraded.append(f"analysis unavailable: {type(exc).__name__}")
        return {"status": "partial", "text": render_markdown([], lookup, degraded), "recent_count": len(recent), "degraded": degraded}

    material = select_notifications(findings, state) if scheduled else findings
    if scheduled:
        material = [
            finding for finding in material
            if finding["severity"] in {"critical", "high"}
        ]
        archive_text = render_telegram_message(material, degraded, lookup=lookup)
        text = render_telegram_message(
            material, degraded, max_findings=4, lookup=lookup
        )
    else:
        text = render_markdown(material, lookup, degraded)
        archive_text = text
    should_notify = scheduled if notify is None else notify
    writeback = None
    should_write = bool(material) and (scheduled or save_to_hfl) and not dry_run
    if should_write:
        dedup_key = scheduled_dedup_key(state, now) if scheduled else None
        if scheduled:
            _corpus_web_origin()  # Validate the Express link before mutating HFL.
        writeback = _writeback(archive_text, now, dedup_key=dedup_key)
        if scheduled:
            if writeback.get("delivery") not in {"persisted", "forwarded"}:
                raise RuntimeError("HFL writeback was not delivered")
            document_url = corpus_document_url(
                writeback,
                fallback_filename=f"{now.date().isoformat()}.md",
            )
            text += f"\n\nCORPUS: {document_url}"
    notification_succeeded = False
    if material and should_notify and not dry_run:
        _notify(text)
        notification_succeeded = True
    can_record_scheduled_state = not material or notification_succeeded
    if scheduled and not dry_run and can_record_scheduled_state:
        timestamp = now.astimezone(timezone.utc).isoformat()
        for finding in findings:
            old = state["findings"].get(finding["fingerprint"], {})
            state["findings"][finding["fingerprint"]] = {
                **old, "first_seen": old.get("first_seen", timestamp), "last_seen": timestamp,
                "severity": finding["severity"], "title": finding["title"],
                "evidence_signature": finding["evidence_signature"], "status": old.get("status", "open"),
            }
        if not degraded:
            state["last_success_at"] = timestamp
        save_state(state, state_file)
    status = "partial" if degraded else ("findings" if material else "no-findings")
    return {
        "status": status, "text": text,
        "recent_count": len(recent), "history_count": len(history),
        "finding_count": len(material), "degraded": degraded, "writeback": writeback,
    }


@SPROUT.task()
@log_result()
def activity_radar(**kwargs: Any) -> dict[str, Any]:
    """Run the scheduled HFL watchdog; notify only for material findings."""
    return run_activity_radar(scheduled=True, notify=True, **kwargs)
