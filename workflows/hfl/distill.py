"""Shared helpers for HFL source distillation."""

from __future__ import annotations

import json
import re
from typing import Any


def parse_model_json(text: str) -> dict[str, Any]:
    """Parse a model response containing either JSON or fenced JSON."""
    value = (text or "").strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", value, re.DOTALL)
    if fenced:
        value = fenced.group(1)
    else:
        start, end = value.find("{"), value.rfind("}")
        if start >= 0 and end > start:
            value = value[start:end + 1]
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


# Backward-compatible alias for existing source modules while they migrate.
_parse_model_json = parse_model_json
