"""Deterministic category arbitration that remains available without Hermes."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from workflows.second_brain.models import ModeDecision, isoformat, normalize_modes


RESOLVER_VERSION = "configurable-v2"


def _enabled_modes(definitions: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [mode for mode in definitions if mode.get("enabled", True) and not mode.get("archived", False)]


def infer_modes(
    signals: Iterable[dict[str, Any]],
    *,
    mode_definitions: Iterable[dict[str, Any]],
    now: datetime | None = None,
) -> tuple[tuple[str, ...], float, tuple[str, ...]]:
    current = (now or datetime.now(timezone.utc)).astimezone()
    definitions = _enabled_modes(mode_definitions)
    scores = {mode["mode_id"]: 0.0 for mode in definitions}
    reasons: list[str] = []
    for signal in signals:
        kind = str(signal.get("event_type") or "").casefold()
        payload = signal.get("payload") or {}
        text = " ".join(str(value) for value in payload.values()).casefold()
        calendar_values = payload.get("calendar_categories") or payload.get("calendar_summaries") or []
        if isinstance(calendar_values, str):
            calendar_values = [calendar_values]
        for mode in definitions:
            mode_id = mode["mode_id"]
            keywords = {str(value).casefold() for value in mode.get("keywords") or []}
            calendars = {str(value) for value in mode.get("calendar_categories") or []}
            matched_keywords = [keyword for keyword in keywords if keyword and (keyword in text or keyword == kind)]
            if matched_keywords:
                scores[mode_id] += min(1.0, 0.55 + 0.1 * len(matched_keywords))
                reasons.append(f"keyword:{mode_id}")
            if calendars.intersection(str(value) for value in calendar_values):
                scores[mode_id] += 0.8
                reasons.append(f"calendar:{mode_id}")
    selected = tuple(mode_id for mode_id, score in scores.items() if score >= 0.5)
    if not selected:
        for mode in definitions:
            for window in mode.get("fallback_windows") or []:
                days = window.get("days", list(range(7)))
                hhmm = current.strftime("%H:%M")
                start, end = str(window.get("start", "00:00")), str(window.get("end", "23:59"))
                within = start <= hhmm <= end if start <= end else hhmm >= start or hhmm <= end
                if current.weekday() in days and within:
                    selected += (mode["mode_id"],)
                    scores[mode["mode_id"]] = max(scores[mode["mode_id"]], 0.5)
                    reasons.append(f"time-window:{mode['mode_id']}")
        if not selected and "default" in scores:
            selected = ("default",)
            scores["default"] = 0.45
            reasons.append("default-fallback")
    confidence = max((scores[mode] for mode in selected), default=0.0)
    return normalize_modes(selected), min(1.0, confidence), tuple(dict.fromkeys(reasons))


def resolve_modes(
    signals: Iterable[dict[str, Any]],
    *,
    mode_definitions: Iterable[dict[str, Any]],
    manual_override: dict[str, Any] | None = None,
    agent_candidate: dict[str, Any] | None = None,
    now: datetime | None = None,
    correlation_id: str,
) -> ModeDecision:
    current = now or datetime.now(timezone.utc)
    definitions = _enabled_modes(mode_definitions)
    available = {mode["mode_id"] for mode in definitions}
    detected, confidence, reasons = infer_modes(signals, mode_definitions=definitions, now=current)
    agent_modes: tuple[str, ...] = ()
    if agent_candidate:
        try:
            agent_modes = tuple(mode for mode in normalize_modes(agent_candidate.get("modes") or ()) if mode in available)
            agent_confidence = max(0.0, min(1.0, float(agent_candidate.get("confidence", 0))))
            if agent_modes and agent_confidence >= 0.65:
                detected = agent_modes
                confidence = agent_confidence
                reasons = tuple(dict.fromkeys((*reasons, "hermes-candidate")))
        except (TypeError, ValueError):
            reasons = tuple(dict.fromkeys((*reasons, "hermes-candidate-invalid")))
    manual = tuple(mode for mode in normalize_modes((manual_override or {}).get("modes") or ()) if mode in available)
    effective = manual or detected or (("default",) if "default" in available else ())
    if manual:
        reasons = tuple(dict.fromkeys((*reasons, "manual-selection")))
        confidence = 1.0
    valid_until = (manual_override or {}).get("expires_at") or isoformat(current + timedelta(minutes=15))
    return ModeDecision(
        effective_modes=effective,
        detected_modes=detected,
        manual_modes=manual,
        confidence=confidence,
        reason_codes=reasons,
        resolver_version=RESOLVER_VERSION,
        valid_until=str(valid_until),
        agent_profile="second-brain" if agent_modes else "",
        correlation_id=correlation_id,
    )
