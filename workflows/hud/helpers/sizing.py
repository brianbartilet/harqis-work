"""
HUD sizing helpers — compute Rainmeter `ItemLines` from rendered content.

Most HUD widgets need their height to track the dump they produce: too few
lines and rows are clipped; too many and the widget leaves a tall empty
strip below the last visible row. `compute_max_hud_lines` returns a value
suitable to assign into `ini['Variables']['ItemLines']` — call it AFTER the
dump is composed and BEFORE the dimension formulas are written.

Usage:
    from workflows.hud.helpers.sizing import compute_max_hud_lines

    dump = build_dump(...)
    dump = "[SCROLL FOR MORE]\\n" + dump + "\\n[END]"

    max_hud_lines = compute_max_hud_lines(dump)              # default cap
    # or, for a tighter widget that scrolls sooner:
    max_hud_lines = compute_max_hud_lines(dump, cap=8)

    ini['Variables']['ItemLines'] = str(max_hud_lines)

The MeasureScrollableText measure (set up via `ini['MeterDisplay']['MeasureName']`)
handles overflow when the dump exceeds `cap` lines.
"""

from __future__ import annotations


# Default height ceiling. Beyond this, content scrolls instead of expanding
# the widget. Tuned for 88-char-row table widgets with up to ~4 sections.
DEFAULT_MAX_HUD_LINES: int = 14

# Padding rows added below the last visible line so the bottom border
# doesn't sit flush against the final character.
HUD_LINE_BUFFER: int = 2


def compute_max_hud_lines(dump: str, cap: int = DEFAULT_MAX_HUD_LINES) -> int:
    """Return the `ItemLines` value that fits the dump + a buffer, capped.

    Counts every newline + 1 for the final line. Adds `HUD_LINE_BUFFER`
    rows so the bottom border has visual breathing room, then caps at
    `cap` so an unexpectedly long dump doesn't expand the widget across
    the whole screen — beyond the cap, MeasureScrollableText handles
    overflow via mouse-wheel scroll.

    Args:
        dump:  The composed dump text (including any [SCROLL FOR MORE] /
               [END] wrappers, since those are visible lines too).
        cap:   Maximum HUD line height. Default `DEFAULT_MAX_HUD_LINES` (14).
               Pass a larger value when you want a taller widget; pass a
               smaller value to force scrolling sooner.

    Returns:
        Integer suitable for assignment to `ini['Variables']['ItemLines']`.
    """
    if not dump:
        return HUD_LINE_BUFFER
    line_count = dump.count("\n") + 1
    return min(cap, line_count + HUD_LINE_BUFFER)
