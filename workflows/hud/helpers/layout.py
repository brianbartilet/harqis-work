"""
HUD layout helpers — compute X coordinates AND widths for horizontal link rows.

Most HUD widgets render a row of clickable text labels at the top of the
skin (`ECHOMTG | ORDERS | AUDIT | TCG_QR`). Historically each meter's `X`
position AND `W` (click region width) were hand-tuned, which broke the
moment a label was renamed or a link was added — the next meter would
either overlap or leave a visible gap. The helper here returns one
`(X, W)` pair per label so the caller can apply both at once and the
visible row stays clean regardless of label length.

Usage:
    from workflows.hud.helpers.layout import compute_horizontal_link_layout

    labels = ["BOARD", "DASHBOARD", "REPOSITORY", "STRUCTURE", "DUMP"]
    layout = compute_horizontal_link_layout(labels)
    # layout is [(10, 34), ...] — list of (X, W) per label.

    # Apply each pair to its meter:
    ini['meterLink']['X'] = '({0}*#Scale#)'.format(layout[0][0])
    ini['meterLink']['W'] = str(layout[0][1])
    ...
"""

from __future__ import annotations

from typing import List, Tuple


# Approximate pixel width of one monospace character at the font size used
# by the standard HUD link style (`sItemLink`). Calibrated against the
# existing show_tcg_orders layout (X positions 10 / 52 / 96 / 132 for
# 'ECHOMTG' / '|ORDERS' / '|AUDIT' / '|TCG_QR'). Matches well at 6.
DEFAULT_PX_PER_CHAR: int = 6

# Number of additional characters the leading `|` separator adds to a
# label's rendered width. The separator is part of the second-and-onwards
# meters' Text field (e.g. `Text=|ORDERS`) — the first label does NOT
# carry the prefix.
SEPARATOR_CHARS: int = 1

# Default starting X for the leftmost label. Mirrors the implicit position
# the Rainmeter base template puts `meterLink` at when no `X=` is set.
DEFAULT_START_X: int = 10

# Pixels of breathing room between consecutive link meters. Without it,
# adjacent labels can visually touch (or overlap by 1-2 px due to font
# kerning). 6 keeps the row tidy without spreading labels out too far.
DEFAULT_GAP_PX: float = 0

# Extra pixels added to each meter's W on top of the text's rendered width
# so the click region is comfortable and the right edge of the text doesn't
# get clipped by Rainmeter's strict width enforcement.
DEFAULT_EXTRA_W_PX: int = 3


def compute_horizontal_link_layout(
    labels: List[str],
    start_x: int = DEFAULT_START_X,
    px_per_char: int = DEFAULT_PX_PER_CHAR,
    separator_chars: int = SEPARATOR_CHARS,
    gap_px: int = DEFAULT_GAP_PX,
    extra_w_px: int = DEFAULT_EXTRA_W_PX,
) -> List[Tuple[int, int]]:
    """Return one `(X, W)` pair per label for a horizontal link row.

    For each label:
      * `X` is the cursor position when the label is laid out.
      * `W` is the click-area width — `len(label_with_separator) *
        px_per_char + extra_w_px`.

    After laying out each label, the cursor advances by `W + gap_px` so
    the next label sits to its right without visually overlapping.

    The math is intentionally simple. With defaults (`px_per_char=6`,
    `gap_px=6`, `extra_w_px=4`) it reproduces the historical
    show_tcg_orders layout within a few pixels and prevents the
    "JIRA_B..." text-clipping bug that happened when only `X` was set.

    Args:
        labels:           Display text of each link, in left-to-right order,
                          WITHOUT the leading `|` separator (the helper
                          accounts for it on labels after the first).
        start_x:          X for the leftmost label.
        px_per_char:      Approximate monospace character width.
        separator_chars:  How many extra characters the `|` separator adds
                          to a label's rendered width. Default 1.
        gap_px:           Pixels of empty space between consecutive meters.
        extra_w_px:       Extra pixels added to each W (click padding).

    Returns:
        List of `(x, w)` integer tuples, same length as `labels`. Apply
        each pair directly:

            x, w = layout[i]
            ini[slot]['X'] = '({0}*#Scale#)'.format(x)
            ini[slot]['W'] = str(w)

    Examples:
        >>> compute_horizontal_link_layout(["A", "B", "C"], start_x=0,
        ...                                 px_per_char=10, gap_px=0,
        ...                                 extra_w_px=0)
        [(0, 10), (10, 20), (40, 20)]
    """
    out: List[Tuple[int, int]] = []
    cursor = start_x
    for i, label in enumerate(labels):
        sep = separator_chars if i > 0 else 0
        text_chars = len(label or "") + sep
        w = text_chars * px_per_char + extra_w_px
        out.append((cursor, w))
        cursor += w + gap_px
    return out
