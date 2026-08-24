"""Deterministic mode arbitration that remains available without Hermes."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from workflows.second_brain.models import ModeDecision, isoformat, normalize_modes


RESOLVER_VERSION = "deterministic-v1"


def infer_modes(signals: Iterable[dict[str, Any]], *, now: datetime | None = None) -> tuple[tuple[str, ...], float, tuple[str, ...]]:
    current = (now or datetime.now(timezone.utc)).astimezone()
    scores = {"work": 0.0, "play": 0.0, "finance": 0.0}
    reasons: list[str] = []
    for signal in signals:
        kind = str(signal.get("event_type") or "").casefold()
        text = " ".join(str(value) for value in (signal.get("payload") or {}).values()).casefold()
        if kind in {"calendar", "desktop_activity", "jira"} or any(word in text for word in ("jira", "meeting", "coding", "review")):
            scores["work"] += 0.7
            reasons.append("work-signal")
        if kind in {"game", "deck_selected"} or any(word in text for word in ("mtg", "magic", "game", "deck")):
            scores["play"] += 0.8
            reasons.append("play-signal")
        if kind in {"finance", "market"} or any(word in text for word in ("oanda", "portfolio", "stock", "finance")):
            scores["finance"] += 0.8
            reasons.append("finance-signal")
    if not any(scores.values()):
        if current.weekday() < 5 and 8 <= current.hour < 19:
            scores["work"] = 0.55
            reasons.append("weekday-work-window")
        else:
            scores["play"] = 0.45
            reasons.append("off-hours-default")
    threshold = 0.5
    modes = tuple(mode for mode, score in scores.items() if score >= threshold)
    if not modes:
        modes = (max(scores, key=scores.get),)
    confidence = max(scores[mode] for mode in modes)
    return normalize_modes(modes), min(1.0, confidence), tuple(dict.fromkeys(reasons))


def resolve_modes(
    signals: Iterable[dict[str, Any]],
    *,
    manual_override: dict[str, Any] | None = None,
    agent_candidate: dict[str, Any] | None = None,
    now: datetime | None = None,
    correlation_id: str,
) -> ModeDecision:
    current = now or datetime.now(timezone.utc)
    detected, confidence, reasons = infer_modes(signals, now=current)
    agent_modes: tuple[str, ...] = ()
    if agent_candidate:
        try:
            agent_modes = normalize_modes(agent_candidate.get("modes") or ())
            agent_confidence = max(0.0, min(1.0, float(agent_candidate.get("confidence", 0))))
            if agent_modes and agent_confidence >= 0.65:
                detected = agent_modes
                confidence = agent_confidence
                reasons = tuple(dict.fromkeys((*reasons, "hermes-candidate")))
        except (TypeError, ValueError):
            reasons = tuple(dict.fromkeys((*reasons, "hermes-candidate-invalid")))
    manual = normalize_modes((manual_override or {}).get("modes") or ())
    effective = manual or detected
    if manual:
        reasons = tuple(dict.fromkeys((*reasons, "manual-override")))
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
