# Fleet graph review and interaction specification

Date: 2026-11-21. Reviewed HEAD `d95fabbf` and the preceding five commits.
Scope: review, diagnostic tests, and proposed UX. This document does not claim the redesign is implemented.

## Findings

### P1: low zoom can render label boxes with no readable text

`frontend/src/agent-fleet.jsx:314` sets the canvas font to `box.font / scale` while drawing under the graph transform. `a906913c` lowered minZoom from 0.01 to 0.000001, exposing a browser font limit. In headless Edge, drawing “Agent label” with the same transform and 12px target font produced:

| Zoom | Actual canvas font | Pixels containing text |
| --- | --- | --- |
| 1 | 12px | 369 |
| 0.02 | 600px | 369 |
| 0.005 | 2400px | 369 |
| 0.001 | 10000px (clamped) | 231 |
| 0.0001 | 10000px (clamped) | 0 |
| 0.000001 | 10000px (clamped) | 0 |

The rectangle geometry still scales correctly. This reproduces the screenshot's blank-box symptom, but the screenshot's actual camera scale is unavailable. Agent labels are preferred candidates via `activityKind('agent') === 'sources'`; ordinary label eligibility alone does not explain the missing agent text.

Fix direction: draw labels in a separate screen-coordinate pass, preserving device pixel ratio but removing camera scale. Keep fonts at 12–14 CSS pixels. Supply anchor obstacles to placement instead of choosing a box and subsequently discarding it when it intersects an avatar (`agent-fleet.jsx:302`). Give every visible parent an explicit label placement or an edge-clamped callout.

### P1: reset can place a child under the wrong parent

`frontend/src/fleet-reset.mjs` combines direct neighbors, `agent_ids`, and `groupParent`, then chooses the candidate with the greatest degree. This makes a relationship count override explicit assignment. A probe with an action assigned to A and linked to A and B placed it 65 units from B and 1,016 units from A because B had one additional child.

The algorithm also fills available viewport space without reserving parent territories. With two parents 100 units apart and 100 children each in a 972×694 viewport, 38/200 children ended up closer to the other parent. This is a reproducible layout ambiguity, not an overlap assertion failure. The latest commit's “orbs remain distinct” test cannot detect it.

Fix direction: use a stable primary layout parent, with assignment precedence, and size cluster regions before placing children. Shared relationships must not compete as layout parents.

### P1: dragging follows connectivity rather than ownership

`fleet-drag.mjs` excludes other anchors, but delegates to `releaseDragNeighbors` in `graph-drag.mjs`, which traverses all remaining edges. A child-to-child relationship crosses parent boundaries: a probe dragging A released both A's child and B's related child. Released nodes also lose `manual` status. Status/grouping edges are not excluded by that traversal.

`236e83a9` improves the screen-speed cap but retains a 0.02 minimum scale for follow/collision forces, versus 0.000001 for damping. At zoom 0.0001 collision radius becomes only 0.005 of its intended screen size. Existing tests assert progress and finite settling, not collision clearance or ownership preservation.

Fix direction: move the selected ownership subtree using local offsets, with bounded visual spring motion. Cross-links never release another cluster or clear an explicit pin.

### P2: reset, zoom, and layout have conflicting responsibilities

Reset both rearranges children and fits the camera, while also switching animation off. Packing uses screen radii and viewport dimensions, then may reduce the camera scale again for overflow. That final reduction invalidates the spacing used for packing. All anchors remain fixed, so Reset cannot repair overlapping saved parent positions.

The six-commit sequence is: stabilize reset (`21886549`), fit/freeze (`694b150b`), revert (`fdfefded`), compact reset/wider zoom (`a906913c`), speed adjustment (`236e83a9`), viewport packing (`d95fabbf`). The fit/freeze commit and its revert cancel; this is not six independent UX improvements. Labels were not changed in this range, but widening supported zoom exposed their existing rendering assumption.

## Proposed experience

The default view is a readable parent map. Each agent, owner, and connector has a persistent name, avatar, status, and child count. Each owns a bounded region; high child counts become named type groups such as “Skills · 86”. Users expand a group or focus a parent to inspect individual entities. Every entity remains searchable and reachable through the existing inspector/list.

### Ownership and child arrangement

1. Resolve layout parent in order: explicit assigned agent; canonical provider/agent relationship; previously saved valid primary parent among multiple memberships; deterministic remaining membership; owner/unassigned group. Corpus ownership is a fallback, not a competing assignment.
2. Store one presentation parent per entity. Preserve every canonical relationship separately. An ownership change moves only that child to the new cluster.
3. Lay out parent regions first, allowing enough room for names and expanded children. Within a region, use stable type sectors and deterministic ID order, with compact staggered rows or rings. Reserve label rectangles as well as circles.
4. At overview density, collapse overflowing types into count chips. In focused view, initially show up to 24 children per type with “Show more” and a searchable list. Treat 24 as a starting budget to validate at each viewport size.
5. Draw parent-child links within the active region. Reveal cross-parent links on selection/hover, with relationship names in the inspector. Status is a badge or optional filter/group, not a force that pulls all parents together.

### Drag and follow

- A parent tracks the pointer on the next animation frame. Its region and child target positions translate by the identical delta; do not recompute the cluster or camera during drag.
- Children can trail their targets with a critically damped spring. Proposed tuning: 80–120ms response and no more than 16 CSS pixels of visible lag; settle within 250ms after release. Measure these targets in browser tests rather than relying on force iteration counts.
- Preserve child order and parent-relative offsets. Collision correction stays within the active region. Move unrelated clusters only through an explicit Arrange operation.
- Dragging a child changes its local position only. Distinguish a saved placement from an explicit “Pin position” action; moving something does not silently change ownership.
- Parent drag retains explicit pins; show a small pinned indicator and a connector if a pinned child remains behind. Undo restores all affected positions and pin states in one operation.
- Pointer cancellation, Escape, and lost capture cancel the gesture without leaving a running simulation. Touch uses a movement threshold to distinguish tap from drag; pinch operates the camera.
- Reduced-motion mode uses immediate subtree translation with no trailing animation. Idle layout is stationary; decorative animation never mutates saved positions.

### Zoom and detail

Use projected available space to choose detail, rather than raw camera scale: legacy saved coordinates can be arbitrarily large. Zoom never changes stored world positions or parent assignment.

| Level | Visible content | Interaction |
| --- | --- | --- |
| Overview | Named parents, status, counts, bounded type chips | Select parent; Focus opens its region |
| Cluster | Selected parent and type groups; children when spacing permits | Expand/collapse one group; inspect child |
| Detail | Child names, status and selected relationships | Read, select, reposition, inspect |

Use 15% hysteresis around detail thresholds and a short settle delay to prevent repeated expand/collapse while pinching. Selection stays visible through transitions. Parent and selected-child labels remain readable at all camera scales. Rebase extreme legacy coordinates on explicit Arrange or through a versioned migration that preserves the prior layout for undo; do not overwrite saved views on load.

### Controls and stability

- **Fit view:** camera only, includes label bounds and open-drawer occlusion.
- **Focus selected:** camera only, frames a parent region and expands its groups as needed.
- **Arrange children:** deterministic local layout for the selected parent, preserving explicit pins and camera.
- **Arrange all:** repairs parent spacing and child regions; preserves pins, provides Undo, and reports constraints if pins prevent separation.
- **Animation:** independent preference; arrangement does not silently change it.
- Persist parent positions, local child offsets, explicit pins, expansion state, and camera separately with a schema version. Reload restores the same resting view.
- Filtering preserves hidden positions and selected identity. New arrivals fill free slots in their own region. Resize changes detail budgets, not saved positions; do not auto-fit on every refresh.
- At 390px, use one focused cluster with breadcrumbs and the existing mobile inspector. Provide a keyboard-accessible parent/entity list, visible focus, Enter to inspect, Escape to close, and 44px touch controls. Canvas-only labels are not an accessibility substitute.

## Existing patterns to reuse

| Need | Existing source | Reuse |
| --- | --- | --- |
| Identity, color, statuses | `fleet-presentation.jsx`, `action-status.mjs`, `agent-fleet.css` | Existing avatar, type and status vocabulary |
| Details and relationships | `fleet-inspector.jsx`, `fleet-presentation.jsx` | Inspector selection and bounded “Show more” lists |
| Large catalogs | `fleet-entity-catalog.jsx`, `agent-fleet.jsx` Choices | Search/type filters and bounded results |
| Drawers and mobile | `fleet-drawers.jsx` | Existing open/close and focus behavior |
| Labels | `graph-labels.mjs` | Screen-space placement/cache; add true screen-space rendering and anchor reservations |
| Persistence and camera | `agent-fleet.jsx` | Existing storage ownership and viewport controls, with a versioned layout schema |

## Acceptance tests and delivery order

First repair screen-space text and add a real canvas-rendering regression at zoom 1, 0.02, 0.005, 0.001, 0.0001 and 0.000001, DPR 1 and 2. Assert visible glyph pixels, stable 12–14px text, and label/avatar clearance; screenshots must be inspected, not merely saved.

Then establish stable ownership and local cluster coordinates. Test explicit assignment versus a higher-degree unrelated hub, shared children, missing parents, grouping edges, pinned children, and arrivals. Drag A must move zero children belonging exclusively to B, including when A's and B's children share an edge.

Next implement bounded disclosure and camera-only zoom. Use fixtures with 3 nodes, 16 parents/700 children, 1,000 children under one parent, close/overlapping anchors, and extreme legacy coordinates. Validate at widths 390, 972, 1440 and 1920. Expanded children must remain visually attributable to their parent; overview must never become hundreds of unlabeled dots.

Finally test pointer/reversal/cancel/pinch/keyboard/reduced-motion, reload, filters, resize, repeated arrange and undo. Proposed performance targets on the recorded test machine: p95 frame time under 20ms desktop and 33ms mobile during drag; no visible idle drift; pointer-parent lag under one frame; settled offset error under 1 CSS pixel within 250ms. These are acceptance targets, not measured results from this review.

## Validation performed

- `node --test frontend/src/fleet-*.test.mjs frontend/src/graph-*.test.mjs`: 53 passed, 0 failed, 0 skipped.
- `node --test frontend/tests/graph-labels.test.mjs`: 13 passed, 0 failed, 0 skipped.
- Headless Edge canvas probe: reproduced font clamping and zero text pixels at extreme zoom; no full live-page diagnosis is claimed.
- Node diagnostic probes: reproduced assignment override, children closer to another parent, and cross-parent child release. These probes expose missing acceptance coverage; the passing tests above do not establish acceptable UX.
- `frontend/tests/test_fleet_zoom_browser.py`: 2 passed, 0 failed, 0 errored, 0 skipped at 1440px and 390px (125.66s; six dependency/syntax warnings). Its fixture contains only three nodes and cannot validate dense graph readability. Machine environment was bootstrapped before pytest; tests used the isolated frontend fixtures. JUnit output: `results/fleet-review-2026-11-21.xml`.
- Total existing automated checks: 68 passed, no failures/errors/skips. Diagnostic probes separately reproduced the defects above; they are not included in that passing count.

The initial review changed no runtime code, deployed assets, or user layout data.

## Implementation follow-up

The requested implementation adds a true screen-coordinate label pass, a shared ownership resolver, bounded type groups (24 items per page on desktop; 12 on narrow canvases), group search/paging, and direct parent-relative translation during drag. Narrow canvases focus one parent at a time, with all dense groups retained in the group browser. Explicit pins remain fixed; cross-links do not participate in drag. Collapsed children with saved positions translate with their parent. Assignment changes relocate unpinned children on their next placement.

Arrange all repairs parent spacing and lays children around their owners without changing camera or animation preference. Arrange children operates on the selected parent. Fit view reserves room around the visible layout; Focus selected frames the selected cluster. Pin position and a one-operation Undo layout are available in the viewport controls. Escape/pointer cancellation restore the gesture snapshot. Existing stored coordinates remain readable; no automatic destructive migration is performed. Layout records now carry a version and parent identity, and group expansion/page is saved separately.

This implementation deliberately uses explicit group expansion instead of automatic zoom-triggered expansion, and immediate translation instead of a trailing spring. These choices keep child membership and offsets stable during navigation. The performance thresholds and more elaborate semantic-zoom behavior above remain design targets; they are not claimed as measured or implemented.

For an existing crowded saved view, use **Arrange all**, then **Fit view**. The first repairs positions; the second changes only the camera. **Layout → Undo layout** restores the prior arrangement. The initial saved view is preserved until the user chooses to arrange it.

### Implementation validation

- 74 JavaScript checks passed across the Fleet/source graph suites and shared label suite, including the additional compact-view, ownership, pin, legacy-camera and assignment regressions.
- The two Edge glyph tests passed at DPR 1 and 2 across all six zoom levels; actual glyph pixels remain identical across zoom levels.
- Desktop/mobile zoom, arrangement, undo, persistence and dense-group browser checks passed. The dense fixture contains 200 children; unit coverage additionally checks a 700-child overview and a 1,000-child legacy arrangement.
- The final dense browser run verifies actual pointer dragging, parent navigation, and preserved parent positions when widening a mobile canvas. Desktop and mobile screenshots were visually inspected. Selected labels reserve space before parent labels, and label placement reserves every displayed node's circle.
- Browser reruns disabled optional pytest plugin autoload after startup stalled before collection. The canonical environment bootstrap and repository fixtures remained active; the unused `env_files` plugin setting consequently emits a configuration warning. Dependency deprecations and existing escape-sequence warnings remain.
- The Fleet asset bundle builds successfully and `git diff --check` is clean. These are focused regression checks, not a full repository test run or a measured frame-rate benchmark.
