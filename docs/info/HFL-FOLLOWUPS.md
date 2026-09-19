# Activity Corpus Follow-ups

Approved feature specification, 2026-09-20.

Explore → Follow-ups opens a six-lane board: Open, Active, In Progress,
Incomplete, Done, and Dismissed. Explore → Graph retains the graph entry point.

## Context and filtering

The board follows the current workspace selection and additional corpus filters.
The existing day/period Actions panel and heatmap action indicators use the same
filtering. Linked actions match through their entry's source, tags, search text,
and dates, including actions generated from background ideas. Combined workspaces
retain their existing union semantics, with additional filters narrowing results.

Unlinked manual actions have source `manual-entry`. Their own created/updated
timestamps support those date filters; entry-date and tag constraints exclude them
when they cannot match. Text search uses their title and expected outcome.

The board shows applied views and Dynamic ON/OFF. Its All activity toggle
bypasses view filters only within the board. Access restrictions still apply.
Historical panels retain old dismissals; the board shows only actions whose latest
transition into Dismissed was within the preceding 14 days. Editing a dismissed
action does not restart that period. Other lanes have no extra age cutoff.

## Interaction and refresh

Cards reuse the Actions panel's controls, source and triage pills, and due dates.
Expected outcome and Prompt are collapsed by default. Unlinked manual cards omit the evidence link. Linked cards with unavailable evidence
show a disabled link. Create actionable opens the shared editor.

Drag a card to change status, or use Edit to select a status with the keyboard.
Writes use the action version to reject concurrent overwrites. A failed move leaves
the saved status intact and reloads the board with an inline error.

The browser polls every five seconds while the board is visible, pausing while
editing or dragging. Local saves refresh immediately. This introduces no Celery
schedule or agent automation. Dynamic workspace transitions preserve the open
board and its local override, show the existing loading dialog, and reopen the
board using the new context. Editing dialogs continue to pause transitions.

Listings filter before pagination. The board retrieves every page. Routine updates
preserve expansion and lane scroll state where possible. Failed refreshes retain
the last cards and identify them as potentially stale, with a Refresh control.

## Verification

Regression coverage lives in `frontend/tests/test_hfl_timeline.py` and
`frontend/tests/test_adaptive_views.py`: source/tag/date inheritance, consistent
markers and period results, dismissal transitions, optimistic concurrency,
workspace behavior, desktop/mobile board controls, drag-and-drop, and background
status refresh.

## Display and result recovery

The board uses a compact toolbar and cards, full-width Results controls, and the
heatmap status colors: yellow for Open/Active, blue for In Progress, red for
Incomplete, green for Done, and grey for Dismissed. Explore uses a neutral dropdown
with a caret; the global Profile menu remains above page controls.

Results also reads saved completion notes from canonical action history. These
are labeled **Saved action outcome**, rendered as sanitized Markdown, and deduplicated
against local execution reports. This makes existing outcomes visible on frontends
that do not own the original execution store; it does not recreate missing run
metadata or recover output that was never saved to the action. History renders
completion notes with the same sanitizer.

Supporting-file Preview opens a nested dialog for images, audio/video, PDF, text,
and Markdown. Saved Word documents receive a text preview. Unsupported formats
retain their download link, and pending Word documents must be saved first.

The header groups Create entry and Create actionable under Create. On mobile,
Create spans the first row; Explore and Workspaces share the second row equally.
