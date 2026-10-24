---
name: create-new-hud
description: >
  Create or extend a portable Second Brain web HUD widget, collector, projection,
  and fixed-size dashboard presentation. Rainmeter scaffolding is legacy opt-in.
user-invocable: true
allowed-tools: Bash Read Glob Grep Edit Write
---

# Create a HUD widget

The default surface is `/second-brain`. Read
`docs/info/SECOND-BRAIN-HUD-MIGRATION.md` and the nearest existing collector before
implementation. Existing authorization to build a widget covers routine reversible
implementation choices; ask only for missing information that changes its behavior.

## Contract

- Infer title, source, update cadence, linked Spaces, size, and motion from the
  request. Default to 2x2 and static/manual scroll. Ask about consequential source
  mutations; a display widget is normally read-only.
- Use `create-new-service-app` only for a missing integration, and
  `create-new-workflow` plus `choose-automation-runtime` for collection. Celery owns
  deterministic collection, agent runtimes own open-ended widget-building work.
  Keep exactly one schedule owner. Do not create a second poller for existing data.
- Return a dictionary with `text`, optional `summary`, `metrics` and HTTP(S) `links`.
  Keep fetch/transform code separate from rendering; new collectors must be
  cross-platform unless the source itself needs Windows.
- Publish through `workflows.second_brain.hud_projection.capture_hud_projection`.
  Add a code-owned `OperationSpec` to `workflows/second_brain/registry.py`; never
  accept import paths from prompts or browser requests. Set truthful freshness,
  sensitivity, source task and refresh interval. The dashboard catalog derives
  from this registry, so standard text widgets need no bespoke JS.
- Register a new task module in its workflow `__init__.py`, preserve queue/host
  requirements, and regenerate the frontend registry when schedules change.
- Existing HUD task names remain collector compatibility adapters. `init_meter`
  defaults to portable output. Do not add a Rainmeter dependency to a new widget.

## Presentation

Use `frontend/modules/second_brain/hud.py`, `hud_router.py`,
`templates/modules/second_brain/hud.html`, `static/js/second-brain-hud.js` and
`static/css/second-brain-hud.css`. Follow `review-frontend-patterns` when available.
The grid has six columns with four viewport rows and vertical overflow. Supported
sizes only: 1x1, 1x2, 1x3, 1x4, 2x1, 2x2, 2x4, 3x1, 3x3, 3x4. Mobile is one column with the
same row span. Use persisted layout revisions and the shared Corpus Space IDs and
selection preferences. No linked Spaces means globally visible.

Motion options are static, marquee and typing. Preserve manual scroll, pause,
keyboard controls, reduced-motion behavior, safe text rendering and stale/empty/
unavailable states. Do not execute links or commands copied from Rainmeter INIs.

## Agent handoff

The dashboard's Build with agent form creates a canonical action and opens the
existing Kanban agent workspace. Its prompt includes these skills' content hashes.
Use the configured Hermes/runtime settings there. Keep build execution distinct
from the advisory-only Second Brain chat; do not widen chat's operation allowlist.
Implement on a feature branch, test and publish a reviewable PR when requested.

## Validation and documentation

Test collector normalization and missing/error responses, projection redaction,
source freshness, allowlist registration, layout persistence and linked Spaces.
Use existing fixture isolation; do not mutate live services from test runs.
Validate desktop/mobile, drag and keyboard reorder, all sizes, hide/restore,
full screen and motion pause. Use `run-tests` and the host environment bootstrap.
Update workflow docs, root HUD inventory and the migration inventory; report
source-dependent limitations separately from UI behavior.

## Legacy Rainmeter maintenance

Only when explicitly requested, use [the legacy guide](references/rainmeter-legacy.md).
Enable `HARQIS_LEGACY_RAINMETER=1` or pass `render_legacy_hud=True` for rendering.
Keep the portable projection working. Desktop-only commands do not become browser
commands. New web widgets do not need the legacy eight-question scaffold.
