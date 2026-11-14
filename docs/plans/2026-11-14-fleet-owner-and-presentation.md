# Fleet owner and presentation update

Approved scope: owner identity and ownership links, explicit idea assignment,
status outlines and labels in Fleet and Activity Graph, readable descriptions,
full-width grouped relationships, date presets, compact Space menus, and Fleet HUD controls.

## Reuse map

- Profile identity: modules/profile/models.py and the existing profile store.
- Permitted activity: fleet_entry_cache and canonical_snapshot; no new ingest/backfill.
- Status presentation: shared action-status.mjs; entity fills remain type-colored.
- Dates: graph-dates.mjs, including local-calendar week and rolling-date behavior.
- Markdown: services/markdown.py sanitizer; corpus field labels become sections.
- Assignments: existing bridge configuration store with an idea namespace,
  owner/CSRF checks and atomic compare-and-set. Assignment does not dispatch work.
- HUD: existing Agents layout revision checks and HUD build-context/action bridge.
- Space controls: shared workspace_views template; compact presentation on Fleet,
  Kanban, HUD and Activity Graph, sharing controls only on the corpus page.

## Behavior and boundaries

Owner links use “belongs to corpus”; they do not claim authorship or agent assignment.
All available permitted historical entries and canonical intent records participate.
Owner anchors follow filtered visible records. Existing ingestion and schedules are unchanged.
Descriptions load sanitized full Markdown on selection rather than rendering every historical
entry during graph refresh. Plain paragraphs preserve line breaks and metadata hashtags
remain text. Actions retain their entity color with a status ring/glow; shortened labels
reserve room for status text. Multiple relationships to a single entity share one card,
with bounded incremental display for large owner relationship lists.

The HUD add icon lists linked operations absent or hidden in the Agents layout and is
disabled when there are no candidates. Build-new remains separate, creates a durable
HUD action, assigns executable Hermes agents where applicable, and opens the existing
agent workspace in Fleet. It does not start execution automatically. Shared widget
Space membership is preserved when restoring; a widget outside active Spaces stays
filtered. Existing layouts keep optimistic revision checks.

## Validation

Focused Python coverage: projection, receipt attribution, owner links, protected-description
access, sanitized metadata, assignment conflict/reassignment, ecosystem, and HUD layout.
Graph tests cover owner visibility under filters and status retention in shortened labels.
Browser checks cover desktop/mobile layout, date presets, compact menus, idea assignment,
formatted entry selection, HUD add/restore and build-new, and no navigation away from Fleet.
Saved-Space synchronization/navigation tests pass at 1440px and 390px.

Historical corpus coverage is limited to data present in permitted sources. Large corpora
still have graph/rendering costs; this change retains the shared corpus cache and avoids
bulk Markdown rendering. No production deployment or commit is included in this update.

Date-filter clarification: actions and ideas remain visible regardless of creation date,
including Done actions. Dismissed (archived) intent is hidden. Activity entries still
follow date presets; Space, search, type and service filters continue to apply.
