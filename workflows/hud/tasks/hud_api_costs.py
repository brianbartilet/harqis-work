"""
TOKEN BURN HUD widget.

Trailing 3-month LLM API spend across the connected services
(Anthropic, OpenAI, Gemini). The newest month (month-to-date) appears
first; older calendar months follow. Each month shows a total at the
top, then one section per service that incurred non-zero cost in that
month, with a per-model breakdown below.

Anthropic numbers come from the real admin **cost report** API — actual
billed USD, the same figures the console shows (requires
ANTHROPIC_ADMIN_KEY). This is deliberately NOT the token-estimate path:
estimating cost from token counts times a static price table drifted from
billing (cache-write pricing especially), so the widget undercounted. See
``ApiServiceAnthropicUsage.get_cost_by_model``. OpenAI / Gemini are stubbed
at zero until cost endpoints are added to those apps — when a service's
monthly total is zero, its section is omitted entirely (filter rule). A
month with no spend across any service still renders its header so the
trailing-3 layout stays consistent.
"""

from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from core.apps.sprout.app.celery import SPROUT
from core.apps.es_logging.app.elasticsearch import log_result
from core.utilities.logging.custom_logger import logger as log

from apps.rainmeter.references.helpers.config_builder import ConfigHelperRainmeter, init_meter
from apps.desktop.helpers.feed import feed

from apps.antropic.references.web.api.usage import ApiServiceAnthropicUsage
from apps.antropic.config import APP_NAME as APP_NAME_ANTHROPIC

from apps.rainmeter.config import CONFIG as RAINMETER_CONFIG
from apps.apps_config import CONFIG_MANAGER

from apps.google_apps.references.constants import ScheduleCategory

from workflows.hud.helpers.layout import compute_horizontal_link_layout
from workflows.hud.helpers.text import truncate
from workflows.hud.tasks.sections import sections__api_costs


# 24-char content rows — matches PC DAILY SALES (width_multiplier=0.9).
_ROW_WIDTH: int = 24
_LABEL_WIDTH: int = 15
_AMOUNT_WIDTH: int = 8
_SEP_MONTH: str = "=" * _ROW_WIDTH
_SEP_SERVICE: str = "-" * _ROW_WIDTH

# Vendor prefixes stripped from displayed model names so they fit the
# 15-char label column without ugly mid-name ellipsizing.
_VENDOR_PREFIXES: Tuple[str, ...] = ("claude-", "gemini-", "gpt-", "models/")


def _shorten_model_name(model: str) -> str:
    """Compact model name for the 15-char label column.

    Strips a single known vendor prefix (`claude-`, `gpt-`, `gemini-`,
    `models/`), then strips a trailing `-YYYYMMDD` date suffix if
    present (so `claude-haiku-4-5-20251001` becomes `haiku-4-5`).
    Falls back to ellipsizing via `truncate` when still too long.
    """
    if not model:
        return "(unknown)"
    name = model.strip()
    for prefix in _VENDOR_PREFIXES:
        if name.lower().startswith(prefix):
            name = name[len(prefix):]
            break
    parts = name.rsplit("-", 1)
    if len(parts) == 2 and len(parts[1]) == 8 and parts[1].isdigit():
        name = parts[0]
    return truncate(name, _LABEL_WIDTH)


def _format_money(amount: float) -> str:
    """Right-aligned 8-char USD amount, two decimals."""
    return "{0:>{w}.2f}".format(amount or 0.0, w=_AMOUNT_WIDTH)


def _format_row(label: str, amount: float) -> str:
    """`label` left-padded to 15 + 1-space gap + 8-char amount = 24 chars."""
    clipped = (label or "")[:_LABEL_WIDTH]
    return "{0:<{lw}} {1}".format(clipped, _format_money(amount), lw=_LABEL_WIDTH)


def _month_window(year: int, month: int) -> Tuple[str, str]:
    """ISO `(starting_at, ending_at)` for a calendar month, UTC.

    `ending_at` is the first instant of the following month so the
    interval is half-open `[start, end)` — a May 2026 query covers
    May only, never the first second of June 1st.
    """
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    if month == 12:
        end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(year, month + 1, 1, tzinfo=timezone.utc)
    return (start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            end.strftime("%Y-%m-%dT%H:%M:%SZ"))


def _trailing_month_windows(n: int = 3,
                            now: Optional[datetime] = None
                            ) -> List[Tuple[int, int, str]]:
    """Trailing `n` calendar months including the current one, newest first.

    Returns `(year, month, label)` tuples with `label` = `MM-YYYY`.
    """
    now = now or datetime.now(timezone.utc)
    year, month = now.year, now.month
    out: List[Tuple[int, int, str]] = []
    for _ in range(n):
        out.append((year, month, "{0:02d}-{1}".format(month, year)))
        month -= 1
        if month == 0:
            month = 12
            year -= 1
    return out


# ── Service fetchers ─────────────────────────────────────────────────────────

def _fetch_anthropic_by_model(year: int, month: int, cfg) -> Dict[str, float]:
    """Per-model **billed** USD cost for a calendar month. Returns {} on failure.

    Uses the Anthropic admin *cost report* (actual billed amounts) rather than
    the token-estimate path: the estimate drifted materially from billing
    (cache-write pricing in particular), so the HUD showed less than the real
    spend. ``get_cost_by_model`` returns the same figures as the console.
    """
    start, end = _month_window(year, month)
    try:
        svc = ApiServiceAnthropicUsage(cfg)
        return svc.get_cost_by_model(start_time=start, end_time=end)
    except Exception as exc:
        log.warning("anthropic cost fetch failed for %s-%s: %s", year, month, exc)
        return {}


def _fetch_openai_by_model(year: int, month: int, cfg) -> Dict[str, float]:
    """STUB — OpenAI cost endpoint not yet implemented under apps/open_ai.

    To wire real data: create `apps/open_ai/references/web/api/usage.py`
    modeled on `apps/antropic/.../usage.py`, expose a `get_usage` method,
    and replace this body with a call to it.
    """
    return {}


def _fetch_gemini_by_model(year: int, month: int, cfg) -> Dict[str, float]:
    """STUB — Gemini cost endpoint not yet implemented under apps/gemini.

    To wire real data: create `apps/gemini/references/web/api/usage.py`,
    expose a `get_usage` method, and replace this body with a call to it.
    """
    return {}


# ── Rendering ────────────────────────────────────────────────────────────────

def _render_service_section(label: str, by_model: Dict[str, float]) -> str:
    """Header + separator + one row per model. Empty string if no models."""
    if not by_model:
        return ""
    total = sum(by_model.values())
    lines = [_format_row(label, total), _SEP_SERVICE]
    for model, cost in sorted(by_model.items(), key=lambda kv: kv[1], reverse=True):
        lines.append(_format_row(_shorten_model_name(model), cost))
    return "\n".join(lines)


_NO_USAGE_MESSAGE: str = "No usage this month"


def _render_month_section(month_label: str,
                          services: List[Tuple[str, Dict[str, float]]]) -> str:
    """Month header + total + each non-zero service section.

    `services` is `[(display_name, by_model_dict), ...]`. The month
    total sums every service, including those whose section is omitted
    because their individual total is zero. When *every* service is zero
    a `No usage this month` placeholder is shown under the separator so
    the empty month is visually obvious instead of looking truncated.
    """
    rendered = [
        _render_service_section(name, by_model)
        for name, by_model in services
    ]
    rendered = [s for s in rendered if s]

    month_total = sum(sum(by_model.values()) for _, by_model in services)
    header = "\n".join([_format_row(month_label, month_total), _SEP_MONTH])

    if rendered:
        return header + "\n\n" + "\n\n".join(rendered)
    return header + "\n" + _NO_USAGE_MESSAGE


def _render_api_costs_dump(
        months_data: List[Tuple[str, List[Tuple[str, Dict[str, float]]]]]) -> str:
    """Full dump from collected per-month, per-service data.

    Months are separated by two blank lines so the headers visually
    anchor to the section they own rather than the previous month's tail.
    """
    return "\n\n\n".join(
        _render_month_section(label, services) for label, services in months_data
    )


# ── Task entrypoint ──────────────────────────────────────────────────────────

@SPROUT.task()
@log_result()
@init_meter(RAINMETER_CONFIG, hud_item_name='TOKEN BURN',
            new_sections_dict=sections__api_costs, play_sound=False,
            schedule_categories=[ScheduleCategory.ORGANIZE, ScheduleCategory.FINANCE])
@feed()
def show_api_costs(ini=ConfigHelperRainmeter(),
                   months: int = 3,
                   visible_lines: int = 10,
                   **kwargs):
    """Trailing N-month API spend, grouped by month -> service -> model.

    Args:
        months: How many trailing calendar months to render (incl. current MTD).
        visible_lines: Visible HUD line count. The rest scrolls via mouse wheel.
        cfg_id__anthropic: Config key for the Anthropic admin API client
            (default 'ANTHROPIC' — matches apps_config.yaml).
    """
    log.info("show_api_costs kwargs: %s", list(kwargs.keys()))

    cfg_id__anthropic = kwargs.get('cfg_id__anthropic', APP_NAME_ANTHROPIC)
    cfg__anthropic = CONFIG_MANAGER.get(cfg_id__anthropic)

    # region Fetch — one (year, month) tuple per trailing calendar month
    months_data: List[Tuple[str, List[Tuple[str, Dict[str, float]]]]] = []
    for year, month, label in _trailing_month_windows(months):
        services = [
            ("ANTHROPIC", _fetch_anthropic_by_model(year, month, cfg__anthropic)),
            ("OPENAI",    _fetch_openai_by_model(year, month, None)),
            ("GEMINI",    _fetch_gemini_by_model(year, month, None)),
        ]
        months_data.append((label, services))
    # endregion

    # region Build header links — ANTHROPIC | OPENAI | GEMINI
    url_anthropic = "https://platform.claude.com/workspaces/default/cost"
    url_openai = "https://platform.openai.com/usage"
    url_gemini = "https://aistudio.google.com/app/spend"

    header_labels = ["ANTHROPIC", "OPENAI", "GEMINI"]
    layout = compute_horizontal_link_layout(header_labels)

    x0, w0 = layout[0]
    ini['meterLink']['text'] = header_labels[0]
    ini['meterLink']['leftmouseupaction'] = '!Execute ["{0}" 3]'.format(url_anthropic)
    ini['meterLink']['tooltiptext'] = url_anthropic
    ini['meterLink']['X'] = '({0}*#Scale#)'.format(x0)
    ini['meterLink']['W'] = str(w0)

    extra_links = [
        ("meterLink_openai", header_labels[1], url_openai),
        ("meterLink_gemini", header_labels[2], url_gemini),
    ]
    for i, (slot, label, target) in enumerate(extra_links, start=1):
        x, w = layout[i]
        ini[slot]['Meter'] = 'String'
        ini[slot]['MeterStyle'] = 'sItemLink'
        ini[slot]['X'] = '({0}*#Scale#)'.format(x)
        ini[slot]['Y'] = '(38*#Scale#)'
        ini[slot]['W'] = str(w)
        ini[slot]['H'] = '55'
        ini[slot]['Text'] = '|{0}'.format(label)
        ini[slot]['LeftMouseUpAction'] = '!Execute ["{0}" 3]'.format(target)
        ini[slot]['tooltiptext'] = target
    # endregion

    # region Compose dump (24-char rows)
    # Trailing blank lines give the bottom row visual breathing room before
    # the widget border and ensure MeasureScrollableText's scroll region
    # extends past the final data line (so wheel-scroll engages on the last
    # rows instead of bouncing back).
    dump = _render_api_costs_dump(months_data) or "(no API spend in window)"
    dump = dump + "\n\n\n"
    # endregion

    # region Set dimensions — mirror PC DAILY SALES (width_multiplier=0.9)
    width_multiplier = 0.9
    ini['meterSeperator']['W'] = '({0}*186*#Scale#)'.format(width_multiplier)

    ini['MeterDisplay']['W'] = '({0}*186*#Scale#)'.format(width_multiplier)
    ini['MeterDisplay']['H'] = '((42*#Scale#)+((#ItemLines#+4)*22)*#Scale#)'
    ini['MeterDisplay']['X'] = '14'
    ini['MeterDisplay']['MeasureName'] = 'MeasureScrollableText'

    ini['MeterBackground']['Shape'] = (
        'Rectangle 0,0,({0}*190),(36+((#ItemLines#+4)*22)),2 '
        '| Fill Color #fillColor# | StrokeWidth (1*#Scale#) '
        '| Stroke Color [#darkColor] | Scale #Scale#,#Scale#,0,0'
    ).format(width_multiplier)
    ini['MeterBackgroundTop']['Shape'] = (
        'Rectangle 3,3,({0}*186),25,2 | Fill Color #headerColor# '
        '| StrokeWidth 0 | Stroke Color [#darkColor] '
        '| Scale #Scale#,#Scale#,0,0'
    ).format(width_multiplier)

    ini['Rainmeter']['SkinWidth'] = '({0}*198*#Scale#)'.format(width_multiplier)
    ini['Rainmeter']['SkinHeight'] = '((42*#Scale#)+((#ItemLines#+4)*22)*#Scale#)'

    ini['meterTitle']['W'] = '({0}*190*#Scale#)'.format(width_multiplier)
    ini['meterTitle']['X'] = '({0}*198*#Scale#)/2'.format(width_multiplier)

    ini['Variables']['ItemLines'] = str(visible_lines)
    # endregion

    grand_total = sum(
        sum(by_model.values())
        for _, services in months_data
        for _, by_model in services
    )
    return {
        "text": dump,
        "summary": "{0} month(s) · total ${1:,.2f}".format(len(months_data), grand_total),
        "metrics": {
            "months": len(months_data),
            "grand_total_usd": round(grand_total, 2),
            "by_month": [
                {
                    "month": label,
                    "total": round(sum(sum(by_model.values()) for _, by_model in services), 2),
                    "services": [
                        {
                            "name": name,
                            "total": round(sum(by_model.values()), 2),
                            "models": [
                                {"model": m, "cost": round(c, 2)}
                                for m, c in by_model.items()
                            ],
                        }
                        for name, by_model in services if by_model
                    ],
                }
                for label, services in months_data
            ],
        },
        "links": {
            "anthropic": url_anthropic,
            "openai": url_openai,
            "gemini": url_gemini,
        },
    }
