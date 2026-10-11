# HARQIS frontend MCP coverage

Summary verified against source revision `0acc1e6`. This is a source and test-backed contract; deployed tool
availability still depends on configuration, `MCP_ENABLED_APPS`, API revision,
and reconnecting the MCP client.

## Implemented coverage

**125 canonical `/api/hfl` method/path endpoints** have dedicated MCP
wrappers in the existing `hfl_corpus` integration. Two additional internal
sharing-input endpoints remain protocol-only and must not be exposed through
general MCP tools. Existing names remain compatible. This covers corpus/calendar,
entries and references, actions/categories/pins, entity graph and profiles,
merge/unmerge/audits/matching, saved graph views, timeline, ideas, mind maps,
goals, graph links, proposals/conversions, attachments, and facets.

Another **71 browser-facing routes** have canonical API equivalents, and **10
routes** have shared-service equivalents: five fork routes and five file-catalog
routes. Git
operations execute on the MCP host, which may differ from the frontend host.

The complete inventory contains **383 method/path routes**. Remaining surfaces
are explicitly recorded: **99 deferred routes**, **45 UI/session routes**, and
**33 protocol routes** (guest/worker and internal sharing). Some deferred routes have partial related
tools (for example pin CRUD without all browser scheduling controls). These are
not counted as exact equivalents. This PR does not claim every frontend feature
is exposed to MCP.

## Consistency contract

[frontend/mcp_coverage.json](../../frontend/mcp_coverage.json) maps every mounted
endpoint to tool names or a reviewed reason. Run:

```text
python -m tools.frontend_coverage --check
python -m tools commands hfl_corpus
python -m tools schema hfl_corpus create_hfl_corpus_map
```

The source-only checker resolves nested router prefixes and aliases without
importing application configuration. It fails on missing/stale route rows,
missing tools, or an uncovered canonical API route. CI also compares this
inventory to the mounted FastAPI routes, checks standalone canonical parity,
verifies tool schemas and write classification, and exercises HTTP contracts
and isolated frontend lifecycles. New routes must receive an explicit coverage
decision; new canonical HFL routes must receive tools.

The inventory counts mounted methods separately, including the 12 timeline and
44 ideas operations at both browser/API prefixes. `/static` is an asset mount,
not a semantic tool, and is excluded. Main frontend disables public Swagger;
standalone `frontend/hfl_api.py` publishes `/openapi.json` for the canonical API,
including graph views and one copy of each entity merge route.

## Behavior and authentication

The extended client uses configured HFL bearer authentication and fixed endpoint
methods. IDs are validated and URL-encoded; tools cannot supply arbitrary URLs.
Version/revision conflicts remain 409 responses. Merge writes require the
reviewed preview token and stable request UUID. No automatic write retry occurs.
Document search forwards calendar/entry/scope filters; document replacement now
exposes `expected_updated_at`. Multipart uploads stream and binary downloads use
an atomic temporary-file replacement. Navigation redirects are returned as
links, not followed with credentials.

The original action/pin management tools keep their scheduling restrictions.
Advanced timeline tools can edit the agenda's execution settings and explicitly
document that capability. Internal worker attribution is rejected by the owner
update tool. Exploration, scans, exports and file downloads are classified as
writes for the CLI. Existing server-side authentication and validation remain
authoritative.

| Surface | Authentication and handling |
| --- | --- |
| Corpus/management/timeline/ideas API | HFL owner bearer token |
| Entity and graph-view API | HFL owner bearer or existing owner session |
| Most dashboard administration | Owner session; needs a separate typed machine-facing contract |
| Sharing owner routes | Owner session and form CSRF where checked |
| Owner agent bridge | Owner session and X-CSRF-Token for non-GET requests |
| Worker agent bridge | Separate bridge bearer plus execution identity/state/lease checks |
| Second Brain feed/events | Owner session or SECOND_BRAIN_API_TOKEN; SSE needs bounded event handling |
| Second Brain commands/settings/chat | Owner session; feed bearer does not grant mutation access |
| Share guest portal | Invitation/pending/guest context; scope and redemption rules apply |

Generic `browser_fetch` can conditionally send HTTP requests to remaining routes,
but it is not dedicated coverage: private addresses are blocked by default,
authentication must be provided, cookies are not retained between calls, response
headers are not returned, text is truncated, and streaming/binary transfers are
not a complete supported workflow. No network-policy or credential settings were
changed by this implementation.

## Remaining work

1. Add structured administration APIs for workflow dispatch/status, application
   inventory/test/cancel, profile/settings and workspace views with explicit
   target-host semantics and the existing task/test allowlists.
2. Add a separate Second Brain adapter for bounded feed reads and deliberately
   authenticated commands; preserve its operation allowlist and scheduling rules.
3. Design sharing and owner-agent controls around scope, CSRF/session boundaries,
   reviewed run decisions and explicit scheduling. Keep guest redemption, login,
   worker claims/leases and desktop open-path as specialized flows.

## Every mounted endpoint

The tables below retain the earlier review snapshot, including historical source
line links; they are not the current exhaustive inventory. Use
[`frontend/mcp_coverage.json`](../../frontend/mcp_coverage.json) and the checker
above for current routes, tool mappings, and coverage decisions.

`covered` means a dedicated HTTP tool, `alias` a canonical semantic equivalent,
`service` an existing shared-service tool, and `deferred`/`ui`/`protocol` explain
intentional remaining coverage. Aliases do not reproduce HTML rendering or all
browser context. Source links point to the route definitions.

### frontend/main.py

| Method | Path | Coverage | Tool / rationale |
| --- | --- | --- | --- |
| GET | [`/`](../../frontend/main.py#L337) | ui | Presentation, redirect, authentication/session or host-desktop flow; browser-specific. |
| GET | [`/health`](../../frontend/main.py#L343) | deferred | Session-authenticated frontend operation; dedicated machine-facing service/auth contract is deferred. |
| GET | [`/debug/config`](../../frontend/main.py#L348) | deferred | Session-authenticated frontend operation; dedicated machine-facing service/auth contract is deferred. |
| GET | [`/login`](../../frontend/main.py#L372) | ui | Presentation, redirect, authentication/session or host-desktop flow; browser-specific. |
| POST | [`/login`](../../frontend/main.py#L377) | ui | Presentation, redirect, authentication/session or host-desktop flow; browser-specific. |
| GET | [`/logout`](../../frontend/main.py#L419) | ui | Presentation, redirect, authentication/session or host-desktop flow; browser-specific. |
| GET | [`/dashboard`](../../frontend/main.py#L426) | ui | Presentation, redirect, authentication/session or host-desktop flow; browser-specific. |
| GET | [`/open-path`](../../frontend/main.py#L489) | ui | Presentation, redirect, authentication/session or host-desktop flow; browser-specific. |

### frontend/modules/home/router.py

| Method | Path | Coverage | Tool / rationale |
| --- | --- | --- | --- |
| GET | [`/distill`](../../frontend/modules/home/router.py#L13) | ui | Owner-facing HTML landing page for reviewing ideas and actions; underlying data operations use the existing canonical HFL tools. |
| GET | [`/home`](../../frontend/modules/home/router.py#L13) | ui | Presentation, redirect, authentication/session or host-desktop flow; browser-specific. |

### frontend/modules/manifesto/router.py

| Method | Path | Coverage | Tool / rationale |
| --- | --- | --- | --- |
| GET | [`/manifesto`](../../frontend/modules/manifesto/router.py#L13) | ui | Presentation, redirect, authentication/session or host-desktop flow; browser-specific. |

### frontend/modules/workflows/router.py

| Method | Path | Coverage | Tool / rationale |
| --- | --- | --- | --- |
| GET | [`/workflows`](../../frontend/modules/workflows/router.py#L15) | ui | Presentation, redirect, authentication/session or host-desktop flow; browser-specific. |
| POST | [`/tasks/{workflow}/{task_key}/trigger`](../../frontend/modules/workflows/router.py#L48) | deferred | Session-authenticated frontend operation; dedicated machine-facing service/auth contract is deferred. |
| GET | [`/tasks/status/{task_id}`](../../frontend/modules/workflows/router.py#L95) | ui | Presentation, redirect, authentication/session or host-desktop flow; browser-specific. |

### frontend/modules/applications/router.py

| Method | Path | Coverage | Tool / rationale |
| --- | --- | --- | --- |
| GET | [`/applications`](../../frontend/modules/applications/router.py#L22) | ui | Presentation, redirect, authentication/session or host-desktop flow; browser-specific. |
| POST | [`/applications/refresh`](../../frontend/modules/applications/router.py#L41) | deferred | Session-authenticated frontend operation; dedicated machine-facing service/auth contract is deferred. |
| GET | [`/applications/{app_key}`](../../frontend/modules/applications/router.py#L50) | ui | Presentation, redirect, authentication/session or host-desktop flow; browser-specific. |
| GET | [`/applications/{app_key}/docs/{doc_path:path}`](../../frontend/modules/applications/router.py#L71) | ui | Presentation, redirect, authentication/session or host-desktop flow; browser-specific. |
| POST | [`/applications/{app_key}/tests`](../../frontend/modules/applications/router.py#L98) | deferred | Session-authenticated frontend operation; dedicated machine-facing service/auth contract is deferred. |
| GET | [`/applications/test-runs/{run_id}`](../../frontend/modules/applications/router.py#L135) | ui | Presentation, redirect, authentication/session or host-desktop flow; browser-specific. |
| POST | [`/applications/test-runs/{run_id}/cancel`](../../frontend/modules/applications/router.py#L150) | deferred | Session-authenticated frontend operation; dedicated machine-facing service/auth contract is deferred. |

### frontend/modules/hfl_corpus/api.py

| Method | Path | Coverage | Tool / rationale |
| --- | --- | --- | --- |
| POST | [`/api/hfl/entries`](../../frontend/modules/hfl_corpus/api.py#L163) | covered | `create_hfl_corpus_entry` |
| POST | [`/api/hfl/entries/preview`](../../frontend/modules/hfl_corpus/api.py#L181) | covered | `preview_hfl_corpus_entry` |
| POST | [`/api/hfl/entries/upload`](../../frontend/modules/hfl_corpus/api.py#L193) | covered | `upload_hfl_corpus_entry` |
| GET | [`/api/hfl/documents`](../../frontend/modules/hfl_corpus/api.py#L217) | covered | `list_hfl_corpus_documents` |
| GET | [`/api/hfl/tree`](../../frontend/modules/hfl_corpus/api.py#L338) | covered | `get_hfl_corpus_tree` |
| GET | [`/api/hfl/matches/{relative_path:path}`](../../frontend/modules/hfl_corpus/api.py#L356) | covered | `list_hfl_corpus_matches` |
| GET | [`/api/hfl/day-matches/{activity_day}`](../../frontend/modules/hfl_corpus/api.py#L408) | covered | `list_hfl_corpus_day_matches` |
| GET | [`/api/hfl/document/{relative_path:path}`](../../frontend/modules/hfl_corpus/api.py#L448) | covered | `get_hfl_corpus_document` |
| POST | [`/api/hfl/document/{relative_path:path}`](../../frontend/modules/hfl_corpus/api.py#L517) | covered | `update_hfl_corpus_document` |
| GET | [`/api/hfl/reference/{token}`](../../frontend/modules/hfl_corpus/api.py#L551) | covered | `download_hfl_corpus_reference` |
| GET | [`/api/hfl/reference/{token}/preview`](../../frontend/modules/hfl_corpus/api.py#L560) | covered | `get_hfl_corpus_reference_preview` |
| GET | [`/api/hfl/reference/{token}/media`](../../frontend/modules/hfl_corpus/api.py#L587) | covered | `download_hfl_corpus_reference_media` |
| GET | [`/api/hfl/reference/{token}/thumbnail`](../../frontend/modules/hfl_corpus/api.py#L605) | covered | `download_hfl_corpus_reference_thumbnail` |

### frontend/modules/hfl_corpus/timeline.py

| Method | Path | Coverage | Tool / rationale |
| --- | --- | --- | --- |
| GET | [`/api/hfl/timeline/source`](../../frontend/modules/hfl_corpus/timeline.py#L117) | covered | `get_hfl_corpus_timeline_source` |
| GET | [`/api/hfl/timeline/evidence`](../../frontend/modules/hfl_corpus/timeline.py#L124) | covered | `get_hfl_corpus_timeline_evidence` |
| GET | [`/api/hfl/timeline/items`](../../frontend/modules/hfl_corpus/timeline.py#L131) | covered | `list_hfl_corpus_timeline_items` |
| PUT | [`/api/hfl/timeline/items/order`](../../frontend/modules/hfl_corpus/timeline.py#L154) | covered | `update_hfl_corpus_timeline_order` |
| POST | [`/api/hfl/timeline/items`](../../frontend/modules/hfl_corpus/timeline.py#L167) | covered | `create_hfl_corpus_timeline_item` |
| PATCH | [`/api/hfl/timeline/items/{followup_id}`](../../frontend/modules/hfl_corpus/timeline.py#L200) | covered | `update_hfl_corpus_timeline_item` |
| GET | [`/api/hfl/timeline/items/{followup_id}`](../../frontend/modules/hfl_corpus/timeline.py#L222) | covered | `get_hfl_corpus_timeline_item` |
| GET | [`/api/hfl/timeline/items/{followup_id}/history`](../../frontend/modules/hfl_corpus/timeline.py#L231) | covered | `get_hfl_corpus_timeline_history` |
| GET | [`/api/hfl/timeline/markers`](../../frontend/modules/hfl_corpus/timeline.py#L257) | covered | `get_hfl_corpus_timeline_markers` |
| GET | [`/api/hfl/timeline/period`](../../frontend/modules/hfl_corpus/timeline.py#L283) | covered | `get_hfl_corpus_timeline_period` |
| POST | [`/api/hfl/timeline/suggestions/{sid}/dismiss`](../../frontend/modules/hfl_corpus/timeline.py#L301) | covered | `update_hfl_corpus_timeline_suggestion_dismiss` |
| POST | [`/api/hfl/timeline/explore`](../../frontend/modules/hfl_corpus/timeline.py#L310) | covered | `create_hfl_corpus_timeline_exploration` |
| GET | [`/hfl-corpus/timeline/source`](../../frontend/modules/hfl_corpus/timeline.py#L117) | alias | `get_hfl_corpus_timeline_source` |
| GET | [`/hfl-corpus/timeline/evidence`](../../frontend/modules/hfl_corpus/timeline.py#L124) | alias | `get_hfl_corpus_timeline_evidence` |
| GET | [`/hfl-corpus/timeline/items`](../../frontend/modules/hfl_corpus/timeline.py#L131) | alias | `list_hfl_corpus_timeline_items` |
| PUT | [`/hfl-corpus/timeline/items/order`](../../frontend/modules/hfl_corpus/timeline.py#L154) | alias | `update_hfl_corpus_timeline_order` |
| POST | [`/hfl-corpus/timeline/items`](../../frontend/modules/hfl_corpus/timeline.py#L167) | alias | `create_hfl_corpus_timeline_item` |
| PATCH | [`/hfl-corpus/timeline/items/{followup_id}`](../../frontend/modules/hfl_corpus/timeline.py#L200) | alias | `update_hfl_corpus_timeline_item` |
| GET | [`/hfl-corpus/timeline/items/{followup_id}`](../../frontend/modules/hfl_corpus/timeline.py#L222) | alias | `get_hfl_corpus_timeline_item` |
| GET | [`/hfl-corpus/timeline/items/{followup_id}/history`](../../frontend/modules/hfl_corpus/timeline.py#L231) | alias | `get_hfl_corpus_timeline_history` |
| GET | [`/hfl-corpus/timeline/markers`](../../frontend/modules/hfl_corpus/timeline.py#L257) | alias | `get_hfl_corpus_timeline_markers` |
| GET | [`/hfl-corpus/timeline/period`](../../frontend/modules/hfl_corpus/timeline.py#L283) | alias | `get_hfl_corpus_timeline_period` |
| POST | [`/hfl-corpus/timeline/suggestions/{sid}/dismiss`](../../frontend/modules/hfl_corpus/timeline.py#L301) | alias | `update_hfl_corpus_timeline_suggestion_dismiss` |
| POST | [`/hfl-corpus/timeline/explore`](../../frontend/modules/hfl_corpus/timeline.py#L310) | alias | `create_hfl_corpus_timeline_exploration` |

### frontend/modules/hfl_corpus/ideas_api.py

| Method | Path | Coverage | Tool / rationale |
| --- | --- | --- | --- |
| GET | [`/api/hfl/timeline/ideas/ideas/{identity}/connections`](../../frontend/modules/hfl_corpus/ideas_api.py#L120) | covered | `get_hfl_corpus_idea_connections` |
| GET | [`/hfl-corpus/timeline/ideas/ideas/{identity}/connections`](../../frontend/modules/hfl_corpus/ideas_api.py#L120) | alias | `get_hfl_corpus_idea_connections` |
| GET | [`/api/hfl/timeline/ideas/snapshot`](../../frontend/modules/hfl_corpus/ideas_api.py#L94) | covered | `get_hfl_corpus_ideas_snapshot` |
| GET | [`/api/hfl/timeline/ideas/connection-availability`](../../frontend/modules/hfl_corpus/ideas_api.py#L100) | covered | `get_hfl_corpus_connection_availability` |
| GET | [`/api/hfl/timeline/ideas/actions/{identity}/connections`](../../frontend/modules/hfl_corpus/ideas_api.py#L108) | covered | `get_hfl_corpus_action_connections` |
| GET | [`/api/hfl/timeline/ideas/dates/{identity}/connections`](../../frontend/modules/hfl_corpus/ideas_api.py#L113) | covered | `get_hfl_corpus_date_connections` |
| GET | [`/api/hfl/timeline/ideas/boards`](../../frontend/modules/hfl_corpus/ideas_api.py#L131) | covered | `list_hfl_corpus_boards` |
| PUT | [`/api/hfl/timeline/ideas/boards/order`](../../frontend/modules/hfl_corpus/ideas_api.py#L140) | covered | `update_hfl_corpus_board_order` |
| PUT | [`/api/hfl/timeline/ideas/goals/order`](../../frontend/modules/hfl_corpus/ideas_api.py#L148) | covered | `update_hfl_corpus_goal_order` |
| GET | [`/api/hfl/timeline/ideas/goal-options`](../../frontend/modules/hfl_corpus/ideas_api.py#L177) | covered | `get_hfl_corpus_goal_options` |
| GET | [`/api/hfl/timeline/ideas/maps/{identity}`](../../frontend/modules/hfl_corpus/ideas_api.py#L183) | covered | `get_hfl_corpus_map` |
| GET | [`/api/hfl/timeline/ideas/maps/{identity}/graph`](../../frontend/modules/hfl_corpus/ideas_api.py#L189) | covered | `get_hfl_corpus_map_graph` |
| GET | [`/api/hfl/timeline/ideas/maps/{identity}/attach-options`](../../frontend/modules/hfl_corpus/ideas_api.py#L206) | covered | `list_hfl_corpus_map_attach_options` |
| POST | [`/api/hfl/timeline/ideas/render`](../../frontend/modules/hfl_corpus/ideas_api.py#L221) | covered | `get_hfl_corpus_rendered_markdown` |
| GET | [`/api/hfl/timeline/ideas/objects/{identity}`](../../frontend/modules/hfl_corpus/ideas_api.py#L232) | covered | `get_hfl_corpus_idea` |
| POST | [`/api/hfl/timeline/ideas/objects`](../../frontend/modules/hfl_corpus/ideas_api.py#L248) | covered | `create_hfl_corpus_idea` |
| PATCH | [`/api/hfl/timeline/ideas/objects/{identity}`](../../frontend/modules/hfl_corpus/ideas_api.py#L256) | covered | `update_hfl_corpus_idea` |
| POST | [`/api/hfl/timeline/ideas/topics`](../../frontend/modules/hfl_corpus/ideas_api.py#L265) | covered | `create_hfl_corpus_topic` |
| POST | [`/api/hfl/timeline/ideas/links`](../../frontend/modules/hfl_corpus/ideas_api.py#L280) | covered | `create_hfl_corpus_link` |
| DELETE | [`/api/hfl/timeline/ideas/links`](../../frontend/modules/hfl_corpus/ideas_api.py#L281) | covered | `delete_hfl_corpus_link` |
| POST | [`/api/hfl/timeline/ideas/maps`](../../frontend/modules/hfl_corpus/ideas_api.py#L292) | covered | `create_hfl_corpus_map` |
| PATCH | [`/api/hfl/timeline/ideas/maps/{identity}`](../../frontend/modules/hfl_corpus/ideas_api.py#L293) | covered | `update_hfl_corpus_map` |
| DELETE | [`/api/hfl/timeline/ideas/maps/{identity}`](../../frontend/modules/hfl_corpus/ideas_api.py#L313) | covered | `delete_hfl_corpus_map` |
| POST | [`/api/hfl/timeline/ideas/maps/{identity}/promote`](../../frontend/modules/hfl_corpus/ideas_api.py#L321) | covered | `create_hfl_corpus_map_promotion` |
| GET | [`/api/hfl/timeline/ideas/goals/{identity}`](../../frontend/modules/hfl_corpus/ideas_api.py#L330) | covered | `get_hfl_corpus_goal` |
| POST | [`/api/hfl/timeline/ideas/maps/{identity}/promote-link`](../../frontend/modules/hfl_corpus/ideas_api.py#L336) | covered | `create_hfl_corpus_map_link_promotion` |
| POST | [`/api/hfl/timeline/ideas/maps/{identity}/connections`](../../frontend/modules/hfl_corpus/ideas_api.py#L352) | covered | `update_hfl_corpus_map_connection` |
| POST | [`/api/hfl/timeline/ideas/goals`](../../frontend/modules/hfl_corpus/ideas_api.py#L359) | covered | `create_hfl_corpus_goal` |
| PATCH | [`/api/hfl/timeline/ideas/goals/{identity}`](../../frontend/modules/hfl_corpus/ideas_api.py#L360) | covered | `update_hfl_corpus_goal` |
| GET | [`/api/hfl/timeline/ideas/objects/{identity}/conversion`](../../frontend/modules/hfl_corpus/ideas_api.py#L397) | covered | `get_hfl_corpus_idea_conversion` |
| POST | [`/api/hfl/timeline/ideas/objects/{identity}/convert`](../../frontend/modules/hfl_corpus/ideas_api.py#L423) | covered | `create_hfl_corpus_idea_conversion` |
| GET | [`/api/hfl/timeline/ideas/objects/{identity}/attachments`](../../frontend/modules/hfl_corpus/ideas_api.py#L484) | covered | `list_hfl_corpus_idea_attachments` |
| GET | [`/api/hfl/timeline/ideas/objects/{identity}/attachments/{attachment_id}`](../../frontend/modules/hfl_corpus/ideas_api.py#L485) | covered | `download_hfl_corpus_idea_attachment` |
| POST | [`/api/hfl/timeline/ideas/objects/{identity}/attachments`](../../frontend/modules/hfl_corpus/ideas_api.py#L497) | covered | `upload_hfl_corpus_idea_attachments` |
| DELETE | [`/api/hfl/timeline/ideas/objects/{identity}/attachments/{attachment_id}`](../../frontend/modules/hfl_corpus/ideas_api.py#L506) | covered | `delete_hfl_corpus_idea_attachment` |
| POST | [`/api/hfl/timeline/ideas/maps/{identity}/accept-proposal`](../../frontend/modules/hfl_corpus/ideas_api.py#L546) | covered | `create_hfl_corpus_map_proposal` |
| GET | [`/hfl-corpus/timeline/ideas/snapshot`](../../frontend/modules/hfl_corpus/ideas_api.py#L94) | alias | `get_hfl_corpus_ideas_snapshot` |
| GET | [`/hfl-corpus/timeline/ideas/connection-availability`](../../frontend/modules/hfl_corpus/ideas_api.py#L100) | alias | `get_hfl_corpus_connection_availability` |
| GET | [`/hfl-corpus/timeline/ideas/actions/{identity}/connections`](../../frontend/modules/hfl_corpus/ideas_api.py#L108) | alias | `get_hfl_corpus_action_connections` |
| GET | [`/hfl-corpus/timeline/ideas/dates/{identity}/connections`](../../frontend/modules/hfl_corpus/ideas_api.py#L113) | alias | `get_hfl_corpus_date_connections` |
| GET | [`/hfl-corpus/timeline/ideas/boards`](../../frontend/modules/hfl_corpus/ideas_api.py#L131) | alias | `list_hfl_corpus_boards` |
| PUT | [`/hfl-corpus/timeline/ideas/boards/order`](../../frontend/modules/hfl_corpus/ideas_api.py#L140) | alias | `update_hfl_corpus_board_order` |
| PUT | [`/hfl-corpus/timeline/ideas/goals/order`](../../frontend/modules/hfl_corpus/ideas_api.py#L148) | alias | `update_hfl_corpus_goal_order` |
| GET | [`/hfl-corpus/timeline/ideas/goal-options`](../../frontend/modules/hfl_corpus/ideas_api.py#L177) | alias | `get_hfl_corpus_goal_options` |
| GET | [`/hfl-corpus/timeline/ideas/maps/{identity}`](../../frontend/modules/hfl_corpus/ideas_api.py#L183) | alias | `get_hfl_corpus_map` |
| GET | [`/hfl-corpus/timeline/ideas/maps/{identity}/graph`](../../frontend/modules/hfl_corpus/ideas_api.py#L189) | alias | `get_hfl_corpus_map_graph` |
| GET | [`/hfl-corpus/timeline/ideas/maps/{identity}/attach-options`](../../frontend/modules/hfl_corpus/ideas_api.py#L206) | alias | `list_hfl_corpus_map_attach_options` |
| POST | [`/hfl-corpus/timeline/ideas/render`](../../frontend/modules/hfl_corpus/ideas_api.py#L221) | alias | `get_hfl_corpus_rendered_markdown` |
| GET | [`/hfl-corpus/timeline/ideas/objects/{identity}`](../../frontend/modules/hfl_corpus/ideas_api.py#L232) | alias | `get_hfl_corpus_idea` |
| POST | [`/hfl-corpus/timeline/ideas/objects`](../../frontend/modules/hfl_corpus/ideas_api.py#L248) | alias | `create_hfl_corpus_idea` |
| PATCH | [`/hfl-corpus/timeline/ideas/objects/{identity}`](../../frontend/modules/hfl_corpus/ideas_api.py#L256) | alias | `update_hfl_corpus_idea` |
| POST | [`/hfl-corpus/timeline/ideas/topics`](../../frontend/modules/hfl_corpus/ideas_api.py#L265) | alias | `create_hfl_corpus_topic` |
| POST | [`/hfl-corpus/timeline/ideas/links`](../../frontend/modules/hfl_corpus/ideas_api.py#L280) | alias | `create_hfl_corpus_link` |
| DELETE | [`/hfl-corpus/timeline/ideas/links`](../../frontend/modules/hfl_corpus/ideas_api.py#L281) | alias | `delete_hfl_corpus_link` |
| POST | [`/hfl-corpus/timeline/ideas/maps`](../../frontend/modules/hfl_corpus/ideas_api.py#L292) | alias | `create_hfl_corpus_map` |
| PATCH | [`/hfl-corpus/timeline/ideas/maps/{identity}`](../../frontend/modules/hfl_corpus/ideas_api.py#L293) | alias | `update_hfl_corpus_map` |
| DELETE | [`/hfl-corpus/timeline/ideas/maps/{identity}`](../../frontend/modules/hfl_corpus/ideas_api.py#L313) | alias | `delete_hfl_corpus_map` |
| POST | [`/hfl-corpus/timeline/ideas/maps/{identity}/promote`](../../frontend/modules/hfl_corpus/ideas_api.py#L321) | alias | `create_hfl_corpus_map_promotion` |
| GET | [`/hfl-corpus/timeline/ideas/goals/{identity}`](../../frontend/modules/hfl_corpus/ideas_api.py#L330) | alias | `get_hfl_corpus_goal` |
| POST | [`/hfl-corpus/timeline/ideas/maps/{identity}/promote-link`](../../frontend/modules/hfl_corpus/ideas_api.py#L336) | alias | `create_hfl_corpus_map_link_promotion` |
| POST | [`/hfl-corpus/timeline/ideas/maps/{identity}/connections`](../../frontend/modules/hfl_corpus/ideas_api.py#L352) | alias | `update_hfl_corpus_map_connection` |
| POST | [`/hfl-corpus/timeline/ideas/goals`](../../frontend/modules/hfl_corpus/ideas_api.py#L359) | alias | `create_hfl_corpus_goal` |
| PATCH | [`/hfl-corpus/timeline/ideas/goals/{identity}`](../../frontend/modules/hfl_corpus/ideas_api.py#L360) | alias | `update_hfl_corpus_goal` |
| GET | [`/hfl-corpus/timeline/ideas/objects/{identity}/conversion`](../../frontend/modules/hfl_corpus/ideas_api.py#L397) | alias | `get_hfl_corpus_idea_conversion` |
| POST | [`/hfl-corpus/timeline/ideas/objects/{identity}/convert`](../../frontend/modules/hfl_corpus/ideas_api.py#L423) | alias | `create_hfl_corpus_idea_conversion` |
| GET | [`/hfl-corpus/timeline/ideas/objects/{identity}/attachments`](../../frontend/modules/hfl_corpus/ideas_api.py#L484) | alias | `list_hfl_corpus_idea_attachments` |
| GET | [`/hfl-corpus/timeline/ideas/objects/{identity}/attachments/{attachment_id}`](../../frontend/modules/hfl_corpus/ideas_api.py#L485) | alias | `download_hfl_corpus_idea_attachment` |
| POST | [`/hfl-corpus/timeline/ideas/objects/{identity}/attachments`](../../frontend/modules/hfl_corpus/ideas_api.py#L497) | alias | `upload_hfl_corpus_idea_attachments` |
| DELETE | [`/hfl-corpus/timeline/ideas/objects/{identity}/attachments/{attachment_id}`](../../frontend/modules/hfl_corpus/ideas_api.py#L506) | alias | `delete_hfl_corpus_idea_attachment` |
| POST | [`/hfl-corpus/timeline/ideas/maps/{identity}/accept-proposal`](../../frontend/modules/hfl_corpus/ideas_api.py#L546) | alias | `create_hfl_corpus_map_proposal` |

### frontend/modules/hfl_corpus/intent_reuse.py

| Method | Path | Coverage | Tool / rationale |
| --- | --- | --- | --- |
| GET | [`/api/hfl/timeline/ideas/reuse/options`](../../frontend/modules/hfl_corpus/intent_reuse.py#L37) | covered | `list_hfl_corpus_reuse_options` |
| GET | [`/hfl-corpus/timeline/ideas/reuse/options`](../../frontend/modules/hfl_corpus/intent_reuse.py#L37) | alias | `list_hfl_corpus_reuse_options` |
| GET | [`/api/hfl/timeline/ideas/reuse/board-ideas`](../../frontend/modules/hfl_corpus/intent_reuse.py#L52) | covered | `list_hfl_corpus_board_ideas` |
| GET | [`/hfl-corpus/timeline/ideas/reuse/board-ideas`](../../frontend/modules/hfl_corpus/intent_reuse.py#L52) | alias | `list_hfl_corpus_board_ideas` |
| GET | [`/api/hfl/timeline/ideas/reuse/clone/{kind}/{identity}`](../../frontend/modules/hfl_corpus/intent_reuse.py#L62) | covered | `get_hfl_corpus_clone_draft` |
| GET | [`/hfl-corpus/timeline/ideas/reuse/clone/{kind}/{identity}`](../../frontend/modules/hfl_corpus/intent_reuse.py#L62) | alias | `get_hfl_corpus_clone_draft` |
| POST | [`/api/hfl/timeline/ideas/reuse/clone/{kind}/{identity}`](../../frontend/modules/hfl_corpus/intent_reuse.py#L80) | covered | `create_hfl_corpus_clone` |
| POST | [`/hfl-corpus/timeline/ideas/reuse/clone/{kind}/{identity}`](../../frontend/modules/hfl_corpus/intent_reuse.py#L80) | alias | `create_hfl_corpus_clone` |
| POST | [`/api/hfl/timeline/ideas/reuse/copy-list`](../../frontend/modules/hfl_corpus/intent_reuse.py#L116) | covered | `create_hfl_corpus_list_copy` |
| POST | [`/hfl-corpus/timeline/ideas/reuse/copy-list`](../../frontend/modules/hfl_corpus/intent_reuse.py#L116) | alias | `create_hfl_corpus_list_copy` |
| POST | [`/api/hfl/timeline/ideas/maps/{identity}/paste`](../../frontend/modules/hfl_corpus/intent_reuse.py#L141) | covered | `create_hfl_corpus_map_paste` |
| POST | [`/hfl-corpus/timeline/ideas/maps/{identity}/paste`](../../frontend/modules/hfl_corpus/intent_reuse.py#L141) | alias | `create_hfl_corpus_map_paste` |
| GET | [`/api/hfl/timeline/ideas/lists/{identity:path}`](../../frontend/modules/hfl_corpus/intent_reuse.py#L231) | covered | `get_hfl_corpus_list` |
| GET | [`/hfl-corpus/timeline/ideas/lists/{identity:path}`](../../frontend/modules/hfl_corpus/intent_reuse.py#L231) | alias | `get_hfl_corpus_list` |
| POST | [`/api/hfl/timeline/ideas/lists`](../../frontend/modules/hfl_corpus/intent_reuse.py#L243) | covered | `create_hfl_corpus_list` |
| POST | [`/hfl-corpus/timeline/ideas/lists`](../../frontend/modules/hfl_corpus/intent_reuse.py#L243) | alias | `create_hfl_corpus_list` |
| PATCH | [`/api/hfl/timeline/ideas/lists/{identity:path}`](../../frontend/modules/hfl_corpus/intent_reuse.py#L244) | covered | `update_hfl_corpus_list` |
| PATCH | [`/hfl-corpus/timeline/ideas/lists/{identity:path}`](../../frontend/modules/hfl_corpus/intent_reuse.py#L244) | alias | `update_hfl_corpus_list` |

### frontend/modules/hfl_corpus/management_api.py

| Method | Path | Coverage | Tool / rationale |
| --- | --- | --- | --- |
| GET | [`/api/hfl/{resource}/{source_id}/attachments`](../../frontend/modules/hfl_corpus/management_api.py#L30) | covered | `list_hfl_corpus_attachments` |
| POST | [`/api/hfl/{resource}/{source_id}/attachments`](../../frontend/modules/hfl_corpus/management_api.py#L38) | covered | `upload_hfl_corpus_attachments` |
| GET | [`/api/hfl/{resource}/{source_id}/attachments/{attachment_id}`](../../frontend/modules/hfl_corpus/management_api.py#L47) | covered | `download_hfl_corpus_attachment` |
| DELETE | [`/api/hfl/{resource}/{source_id}/attachments/{attachment_id}`](../../frontend/modules/hfl_corpus/management_api.py#L56) | covered | `delete_hfl_corpus_attachment` |
| GET | [`/api/hfl/actions`](../../frontend/modules/hfl_corpus/management_api.py#L158) | covered | `list_hfl_corpus_actions` |
| POST | [`/api/hfl/actions`](../../frontend/modules/hfl_corpus/management_api.py#L164) | covered | `create_hfl_corpus_action` |
| GET | [`/api/hfl/actions/{action_id}`](../../frontend/modules/hfl_corpus/management_api.py#L177) | covered | `get_hfl_corpus_action` |
| PATCH | [`/api/hfl/actions/{action_id}`](../../frontend/modules/hfl_corpus/management_api.py#L182) | covered | `update_hfl_corpus_action` |
| GET | [`/api/hfl/actions/{action_id}/history`](../../frontend/modules/hfl_corpus/management_api.py#L192) | covered | `get_hfl_corpus_action_history` |
| GET | [`/api/hfl/categories`](../../frontend/modules/hfl_corpus/management_api.py#L205) | covered | `list_hfl_corpus_categories` |
| POST | [`/api/hfl/categories`](../../frontend/modules/hfl_corpus/management_api.py#L211) | covered | `create_hfl_corpus_category` |
| GET | [`/api/hfl/categories/{category_id}`](../../frontend/modules/hfl_corpus/management_api.py#L218) | covered | `get_hfl_corpus_category` |
| PATCH | [`/api/hfl/categories/{category_id}`](../../frontend/modules/hfl_corpus/management_api.py#L223) | covered | `update_hfl_corpus_category` |
| POST | [`/api/hfl/categories/{category_id}/archive`](../../frontend/modules/hfl_corpus/management_api.py#L232) | covered | `archive_hfl_corpus_category` |
| GET | [`/api/hfl/pins`](../../frontend/modules/hfl_corpus/management_api.py#L262) | covered | `list_hfl_corpus_pins` |
| POST | [`/api/hfl/pins`](../../frontend/modules/hfl_corpus/management_api.py#L268) | covered | `create_hfl_corpus_pin` |
| GET | [`/api/hfl/pins/{pin_id}`](../../frontend/modules/hfl_corpus/management_api.py#L278) | covered | `get_hfl_corpus_pin` |
| PATCH | [`/api/hfl/pins/{pin_id}`](../../frontend/modules/hfl_corpus/management_api.py#L283) | covered | `update_hfl_corpus_pin` |
| DELETE | [`/api/hfl/pins/{pin_id}`](../../frontend/modules/hfl_corpus/management_api.py#L294) | covered | `delete_hfl_corpus_pin` |

### frontend/modules/hfl_corpus/entities_api.py

| Method | Path | Coverage | Tool / rationale |
| --- | --- | --- | --- |
| GET | [`/api/hfl/graph-views`](../../frontend/modules/hfl_corpus/entities_api.py#L17) | covered | `list_hfl_corpus_graph_views` |
| POST | [`/api/hfl/graph-views`](../../frontend/modules/hfl_corpus/entities_api.py#L23) | covered | `create_hfl_corpus_graph_view` |
| PUT | [`/api/hfl/graph-views/{identity}`](../../frontend/modules/hfl_corpus/entities_api.py#L29) | covered | `update_hfl_corpus_graph_view` |
| POST | [`/api/hfl/graph-views/{identity}/select`](../../frontend/modules/hfl_corpus/entities_api.py#L35) | covered | `update_hfl_corpus_graph_view_selection` |
| DELETE | [`/api/hfl/graph-views/{identity}`](../../frontend/modules/hfl_corpus/entities_api.py#L42) | covered | `delete_hfl_corpus_graph_view` |
| GET | [`/knowledge`](../../frontend/modules/hfl_corpus/entities_api.py#L62) | ui | Presentation, redirect, authentication/session or host-desktop flow; browser-specific. |
| GET | [`/knowledge/graph`](../../frontend/modules/hfl_corpus/entities_api.py#L63) | ui | Presentation, redirect, authentication/session or host-desktop flow; browser-specific. |
| GET | [`/hfl-corpus/actions`](../../frontend/modules/hfl_corpus/entities_api.py#L68) | ui | Actions Board presentation; browser-specific. |
| GET | [`/hfl-corpus/graph`](../../frontend/modules/hfl_corpus/entities_api.py#L68) | ui | Presentation, redirect, authentication/session or host-desktop flow; browser-specific. |
| GET | [`/hfl-corpus/ideas`](../../frontend/modules/hfl_corpus/entities_api.py#L69) | ui | Presentation, redirect, authentication/session or host-desktop flow; browser-specific. |
| GET | [`/hfl-corpus/entities`](../../frontend/modules/hfl_corpus/entities_api.py#L70) | alias | `list_hfl_corpus_entities` |
| GET | [`/api/hfl/entities/graph`](../../frontend/modules/hfl_corpus/entities_api.py#L81) | covered | `get_hfl_corpus_entity_graph` |
| GET | [`/api/hfl/entities`](../../frontend/modules/hfl_corpus/entities_api.py#L90) | covered | `list_hfl_corpus_entities` |
| POST | [`/api/hfl/entities/profile/{identity}`](../../frontend/modules/hfl_corpus/entities_api.py#L143) | covered | `update_hfl_corpus_entity_profile` |
| GET | [`/api/hfl/entities/entry/{entry_id}`](../../frontend/modules/hfl_corpus/entities_api.py#L181) | covered | `get_hfl_corpus_entity_entry` |
| GET | [`/hfl-corpus/entities/entry/{entry_id}`](../../frontend/modules/hfl_corpus/entities_api.py#L231) | alias | `get_hfl_corpus_entity_entry` |
| GET | [`/api/hfl/entities/status`](../../frontend/modules/hfl_corpus/entities_api.py#L244) | covered | `get_hfl_corpus_entity_status` |
| POST | [`/api/hfl/entities/backfill`](../../frontend/modules/hfl_corpus/entities_api.py#L252) | covered | `create_hfl_corpus_entity_backfill` |
| POST | [`/api/hfl/entities/merge`](../../frontend/modules/hfl_corpus/entities_api.py#L265) | covered | `create_hfl_corpus_entity_legacy_merge` |
| POST | [`/api/hfl/entities/decisions/{decision_id}/undo`](../../frontend/modules/hfl_corpus/entities_api.py#L280) | covered | `update_hfl_corpus_entity_legacy_undo` |
| POST | [`/api/hfl/entities/export`](../../frontend/modules/hfl_corpus/entities_api.py#L290) | covered | `create_hfl_corpus_entity_export` |

### frontend/modules/hfl_corpus/entity_merge_api.py

| Method | Path | Coverage | Tool / rationale |
| --- | --- | --- | --- |
| POST | [`/api/hfl/entities/merge-preview`](../../frontend/modules/hfl_corpus/entity_merge_api.py#L96) | covered | `analyze_hfl_corpus_entity_selection` |
| POST | [`/api/hfl/entities/merges`](../../frontend/modules/hfl_corpus/entity_merge_api.py#L104) | covered | `create_hfl_corpus_entity_merge` |
| POST | [`/api/hfl/entities/merges/{identity}/unmerge`](../../frontend/modules/hfl_corpus/entity_merge_api.py#L129) | covered | `update_hfl_corpus_entity_unmerge` |
| GET | [`/api/hfl/entities/operations/{request_id}`](../../frontend/modules/hfl_corpus/entity_merge_api.py#L138) | covered | `get_hfl_corpus_entity_operation` |
| GET | [`/api/hfl/entities/audit/{identity}`](../../frontend/modules/hfl_corpus/entity_merge_api.py#L152) | covered | `get_hfl_corpus_entity_audit` |
| GET | [`/api/hfl/entities/matching`](../../frontend/modules/hfl_corpus/entity_merge_api.py#L158) | covered | `get_hfl_corpus_entity_matching` |
| POST | [`/api/hfl/entities/matching/scan`](../../frontend/modules/hfl_corpus/entity_merge_api.py#L165) | covered | `create_hfl_corpus_entity_matching_scan` |
| POST | [`/api/hfl/entities/matching/suggestions/{identity}/dismiss`](../../frontend/modules/hfl_corpus/entity_merge_api.py#L172) | covered | `update_hfl_corpus_entity_matching_dismiss` |

### frontend/modules/hfl_corpus/router.py

| Method | Path | Coverage | Tool / rationale |
| --- | --- | --- | --- |
| GET | [`/hfl-corpus/workspace-views`](../../frontend/modules/hfl_corpus/router.py#L106) | deferred | Session-authenticated frontend operation; dedicated machine-facing service/auth contract is deferred. |
| PUT | [`/hfl-corpus/view-preferences`](../../frontend/modules/hfl_corpus/router.py#L112) | deferred | Session-authenticated frontend operation; dedicated machine-facing service/auth contract is deferred. |
| POST | [`/hfl-corpus/workspace-views`](../../frontend/modules/hfl_corpus/router.py#L118) | deferred | Session-authenticated frontend operation; dedicated machine-facing service/auth contract is deferred. |
| PUT | [`/hfl-corpus/workspace-views/{identity}`](../../frontend/modules/hfl_corpus/router.py#L124) | deferred | Session-authenticated frontend operation; dedicated machine-facing service/auth contract is deferred. |
| POST | [`/hfl-corpus/workspace-views/{identity}/select`](../../frontend/modules/hfl_corpus/router.py#L130) | deferred | Session-authenticated frontend operation; dedicated machine-facing service/auth contract is deferred. |
| DELETE | [`/hfl-corpus/workspace-views/{identity}`](../../frontend/modules/hfl_corpus/router.py#L137) | deferred | Session-authenticated frontend operation; dedicated machine-facing service/auth contract is deferred. |
| POST | [`/hfl-corpus/memory-pins`](../../frontend/modules/hfl_corpus/router.py#L180) | deferred | Session-authenticated frontend operation; dedicated machine-facing service/auth contract is deferred. |
| POST | [`/hfl-corpus/secrets/unlock`](../../frontend/modules/hfl_corpus/router.py#L258) | ui | Presentation, redirect, authentication/session or host-desktop flow; browser-specific. |
| GET | [`/hfl-corpus/activity-year/{activity_year}`](../../frontend/modules/hfl_corpus/router.py#L342) | deferred | Session-authenticated frontend operation; dedicated machine-facing service/auth contract is deferred. |
| GET | [`/hfl-corpus`](../../frontend/modules/hfl_corpus/router.py#L715) | ui | Presentation, redirect, authentication/session or host-desktop flow; browser-specific. |
| POST | [`/hfl-corpus/entries/preview`](../../frontend/modules/hfl_corpus/router.py#L1049) | alias | `preview_hfl_corpus_entry` |
| POST | [`/hfl-corpus/entries`](../../frontend/modules/hfl_corpus/router.py#L1068) | alias | `create_hfl_corpus_entry` |
| POST | [`/hfl-corpus/entries/upload`](../../frontend/modules/hfl_corpus/router.py#L1097) | alias | `upload_hfl_corpus_entry` |
| GET | [`/hfl-corpus/tree`](../../frontend/modules/hfl_corpus/router.py#L1139) | alias | `get_hfl_corpus_tree` |
| GET | [`/hfl-corpus/day-matches/{activity_day}`](../../frontend/modules/hfl_corpus/router.py#L1174) | alias | `list_hfl_corpus_day_matches` |
| GET | [`/hfl-corpus/matches/{relative_path:path}`](../../frontend/modules/hfl_corpus/router.py#L1251) | alias | `list_hfl_corpus_matches` |
| GET | [`/hfl-corpus/document/{relative_path:path}`](../../frontend/modules/hfl_corpus/router.py#L1341) | alias | `get_hfl_corpus_document` |
| POST | [`/hfl-corpus/entry-action/{relative_path:path}`](../../frontend/modules/hfl_corpus/router.py#L1447) | deferred | Session-authenticated frontend operation; dedicated machine-facing service/auth contract is deferred. |
| POST | [`/hfl-corpus/document/{relative_path:path}`](../../frontend/modules/hfl_corpus/router.py#L1476) | alias | `update_hfl_corpus_document` |
| GET | [`/hfl-corpus/references/{token}/download`](../../frontend/modules/hfl_corpus/router.py#L1543) | deferred | Session-authenticated frontend operation; dedicated machine-facing service/auth contract is deferred. |
| GET | [`/hfl-corpus/references/{token}/preview`](../../frontend/modules/hfl_corpus/router.py#L1555) | deferred | Session-authenticated frontend operation; dedicated machine-facing service/auth contract is deferred. |
| GET | [`/hfl-corpus/references/{token}/media`](../../frontend/modules/hfl_corpus/router.py#L1564) | deferred | Session-authenticated frontend operation; dedicated machine-facing service/auth contract is deferred. |
| GET | [`/hfl-corpus/references/{token}/thumbnail`](../../frontend/modules/hfl_corpus/router.py#L1573) | deferred | Session-authenticated frontend operation; dedicated machine-facing service/auth contract is deferred. |
| GET | [`/hfl-corpus/remote-references/{token}/download`](../../frontend/modules/hfl_corpus/router.py#L1594) | ui | Presentation, redirect, authentication/session or host-desktop flow; browser-specific. |
| GET | [`/hfl-corpus/remote-references/{token}/preview`](../../frontend/modules/hfl_corpus/router.py#L1638) | deferred | Session-authenticated frontend operation; dedicated machine-facing service/auth contract is deferred. |
| GET | [`/hfl-corpus/remote-references/{token}/media`](../../frontend/modules/hfl_corpus/router.py#L1643) | deferred | Session-authenticated frontend operation; dedicated machine-facing service/auth contract is deferred. |
| GET | [`/hfl-corpus/remote-references/{token}/thumbnail`](../../frontend/modules/hfl_corpus/router.py#L1648) | deferred | Session-authenticated frontend operation; dedicated machine-facing service/auth contract is deferred. |

### frontend/modules/hfl_corpus/agent_bridge.py

| Method | Path | Coverage | Tool / rationale |
| --- | --- | --- | --- |
| GET | [`/hfl-corpus/agent-bridge/inputs/{kind}/{source_id}`](../../frontend/modules/hfl_corpus/agent_bridge.py#L450) | deferred | Session-authenticated frontend operation; dedicated machine-facing service/auth contract is deferred. |
| POST | [`/hfl-corpus/agent-bridge/inputs/{kind}/{source_id}`](../../frontend/modules/hfl_corpus/agent_bridge.py#L455) | deferred | Session-authenticated frontend operation; dedicated machine-facing service/auth contract is deferred. |
| GET | [`/hfl-corpus/agent-bridge/inputs/{kind}/{source_id}/{attachment_id}`](../../frontend/modules/hfl_corpus/agent_bridge.py#L470) | deferred | Session-authenticated frontend operation; dedicated machine-facing service/auth contract is deferred. |
| DELETE | [`/hfl-corpus/agent-bridge/inputs/{kind}/{source_id}/{attachment_id}`](../../frontend/modules/hfl_corpus/agent_bridge.py#L475) | deferred | Session-authenticated frontend operation; dedicated machine-facing service/auth contract is deferred. |
| GET | [`/hfl-corpus/agent-bridge/artifacts/{run_id}/{name}`](../../frontend/modules/hfl_corpus/agent_bridge.py#L542) | deferred | Session-authenticated frontend operation; dedicated machine-facing service/auth contract is deferred. |
| GET | [`/hfl-corpus/agent-bridge/sources/{kind}/{source_id}`](../../frontend/modules/hfl_corpus/agent_bridge.py#L578) | deferred | Session-authenticated frontend operation; dedicated machine-facing service/auth contract is deferred. |
| POST | [`/hfl-corpus/agent-bridge/sources/{kind}/{source_id}/configure`](../../frontend/modules/hfl_corpus/agent_bridge.py#L612) | deferred | Session-authenticated frontend operation; dedicated machine-facing service/auth contract is deferred. |
| POST | [`/hfl-corpus/agent-bridge/sources/{kind}/{source_id}/run`](../../frontend/modules/hfl_corpus/agent_bridge.py#L624) | deferred | Session-authenticated frontend operation; dedicated machine-facing service/auth contract is deferred. |
| POST | [`/hfl-corpus/agent-bridge/mindmaps/{identity}/accept-proposal`](../../frontend/modules/hfl_corpus/agent_bridge.py#L632) | deferred | Session-authenticated frontend operation; dedicated machine-facing service/auth contract is deferred. |
| POST | [`/hfl-corpus/agent-bridge/runs/{run_id}/{decision}`](../../frontend/modules/hfl_corpus/agent_bridge.py#L653) | deferred | Session-authenticated frontend operation; dedicated machine-facing service/auth contract is deferred. |
| GET | [`/api/hfl-agent/runs/{run_id}/inputs/{attachment_id}`](../../frontend/modules/hfl_corpus/agent_bridge.py#L486) | protocol | Guest session/redemption or worker identity/lease protocol; not an owner CRUD operation. |
| POST | [`/api/hfl-agent/runs/{run_id}/artifacts/{name}`](../../frontend/modules/hfl_corpus/agent_bridge.py#L506) | protocol | Guest session/redemption or worker identity/lease protocol; not an owner CRUD operation. |
| GET | [`/api/hfl-agent/runs/{run_id}/prior-artifacts/{name}`](../../frontend/modules/hfl_corpus/agent_bridge.py#L700) | protocol | Guest session/redemption or worker identity/lease protocol; not an owner CRUD operation. |
| GET | [`/api/hfl-agent/queue`](../../frontend/modules/hfl_corpus/agent_bridge.py#L715) | protocol | Guest session/redemption or worker identity/lease protocol; not an owner CRUD operation. |
| GET | [`/api/hfl-agent/settings`](../../frontend/modules/hfl_corpus/agent_bridge.py#L722) | protocol | Guest session/redemption or worker identity/lease protocol; not an owner CRUD operation. |
| POST | [`/api/hfl-agent/sweep`](../../frontend/modules/hfl_corpus/agent_bridge.py#L727) | protocol | Guest session/redemption or worker identity/lease protocol; not an owner CRUD operation. |
| POST | [`/api/hfl-agent/deliver`](../../frontend/modules/hfl_corpus/agent_bridge.py#L732) | protocol | Guest session/redemption or worker identity/lease protocol; not an owner CRUD operation. |
| POST | [`/api/hfl-agent/runs/{run_id}/claim`](../../frontend/modules/hfl_corpus/agent_bridge.py#L738) | protocol | Guest session/redemption or worker identity/lease protocol; not an owner CRUD operation. |
| POST | [`/api/hfl-agent/runs/{run_id}/events`](../../frontend/modules/hfl_corpus/agent_bridge.py#L763) | protocol | Guest session/redemption or worker identity/lease protocol; not an owner CRUD operation. |

### frontend/modules/hfl_corpus/action_agents.py

| Method | Path | Coverage | Tool / rationale |
| --- | --- | --- | --- |
| GET | [`/api/hfl-agent/terminals`](../../frontend/modules/hfl_corpus/action_agents.py#L149) | protocol | Authenticated worker terminal transport; not an owner MCP operation. |
| GET | [`/api/hfl-agent/terminals/{identity}/inputs/{attachment_id}`](../../frontend/modules/hfl_corpus/action_agents.py#L168) | protocol | Authenticated worker terminal transport; not an owner MCP operation. |
| GET | [`/hfl-corpus/agent-bridge/actions/{source_id}/configuration`](../../frontend/modules/hfl_corpus/action_agents.py#L40) | deferred | Owner session-authenticated terminal/configuration operation; machine-facing contract deferred. |
| GET | [`/hfl-corpus/agent-bridge/actions/{source_id}/sessions`](../../frontend/modules/hfl_corpus/action_agents.py#L70) | deferred | Owner session-authenticated terminal/configuration operation; machine-facing contract deferred. |
| GET | [`/hfl-corpus/agent-bridge/sessions/{identity}`](../../frontend/modules/hfl_corpus/action_agents.py#L92) | deferred | Owner session-authenticated terminal/configuration operation; machine-facing contract deferred. |
| GET | [`/hfl-corpus/agent-bridge/sessions/{identity}/transcript`](../../frontend/modules/hfl_corpus/action_agents.py#L135) | deferred | Owner session-authenticated terminal/configuration operation; machine-facing contract deferred. |
| POST | [`/api/hfl-agent/terminals/{identity}/claim`](../../frontend/modules/hfl_corpus/action_agents.py#L156) | protocol | Authenticated worker terminal transport; not an owner MCP operation. |
| POST | [`/api/hfl-agent/terminals/{identity}/files/{name}`](../../frontend/modules/hfl_corpus/action_agents.py#L207) | protocol | Authenticated worker terminal transport; not an owner MCP operation. |
| POST | [`/api/hfl-agent/terminals/{identity}/output`](../../frontend/modules/hfl_corpus/action_agents.py#L191) | protocol | Authenticated worker terminal transport; not an owner MCP operation. |
| POST | [`/api/hfl-agent/terminals/{identity}/poll`](../../frontend/modules/hfl_corpus/action_agents.py#L174) | protocol | Authenticated worker terminal transport; not an owner MCP operation. |
| POST | [`/hfl-corpus/agent-bridge/actions/{source_id}/configuration`](../../frontend/modules/hfl_corpus/action_agents.py#L51) | deferred | Owner session-authenticated terminal/configuration operation; machine-facing contract deferred. |
| POST | [`/hfl-corpus/agent-bridge/actions/{source_id}/sessions`](../../frontend/modules/hfl_corpus/action_agents.py#L80) | deferred | Owner session-authenticated terminal/configuration operation; machine-facing contract deferred. |
| POST | [`/hfl-corpus/agent-bridge/presets`](../../frontend/modules/hfl_corpus/action_agents.py#L61) | deferred | Owner session-authenticated terminal/configuration operation; machine-facing contract deferred. |
| POST | [`/hfl-corpus/agent-bridge/sessions/{identity}`](../../frontend/modules/hfl_corpus/action_agents.py#L99) | deferred | Owner session-authenticated terminal/configuration operation; machine-facing contract deferred. |
| POST | [`/hfl-corpus/agent-bridge/sessions/{identity}/forget`](../../frontend/modules/hfl_corpus/action_agents.py#L143) | deferred | Owner session-authenticated terminal/configuration operation; machine-facing contract deferred. |
| POST | [`/hfl-corpus/agent-bridge/sessions/{identity}/input`](../../frontend/modules/hfl_corpus/action_agents.py#L115) | deferred | Owner session-authenticated terminal/configuration operation; machine-facing contract deferred. |
| POST | [`/hfl-corpus/agent-bridge/sessions/{identity}/images`](../../frontend/modules/hfl_corpus/action_agents.py#L121) | deferred | Owner session-authenticated terminal image input; machine-facing contract deferred. |

### frontend/modules/hfl_shares/router.py

| Method | Path | Coverage | Tool / rationale |
| --- | --- | --- | --- |
| GET | [`/sharing/filter-options`](../../frontend/modules/hfl_shares/router.py#L581) | deferred | Session-authenticated frontend operation; dedicated machine-facing service/auth contract is deferred. |
| GET | [`/sharing`](../../frontend/modules/hfl_shares/router.py#L597) | ui | Presentation, redirect, authentication/session or host-desktop flow; browser-specific. |
| GET | [`/sharing/generated-shares`](../../frontend/modules/hfl_shares/router.py#L638) | ui | Presentation, redirect, authentication/session or host-desktop flow; browser-specific. |
| POST | [`/sharing/configurations`](../../frontend/modules/hfl_shares/router.py#L655) | deferred | Session-authenticated frontend operation; dedicated machine-facing service/auth contract is deferred. |
| POST | [`/sharing/configurations/{configuration_id}/delete`](../../frontend/modules/hfl_shares/router.py#L681) | deferred | Session-authenticated frontend operation; dedicated machine-facing service/auth contract is deferred. |
| POST | [`/sharing/from-corpus`](../../frontend/modules/hfl_shares/router.py#L796) | deferred | Session-authenticated frontend operation; dedicated machine-facing service/auth contract is deferred. |
| POST | [`/sharing/preview`](../../frontend/modules/hfl_shares/router.py#L872) | deferred | Session-authenticated frontend operation; dedicated machine-facing service/auth contract is deferred. |
| POST | [`/sharing/preview/chat`](../../frontend/modules/hfl_shares/router.py#L885) | deferred | Session-authenticated frontend operation; dedicated machine-facing service/auth contract is deferred. |
| POST | [`/sharing/generate`](../../frontend/modules/hfl_shares/router.py#L966) | deferred | Session-authenticated frontend operation; dedicated machine-facing service/auth contract is deferred. |
| POST | [`/sharing/shares/{share_id}/revoke`](../../frontend/modules/hfl_shares/router.py#L1056) | deferred | Session-authenticated frontend operation; dedicated machine-facing service/auth contract is deferred. |
| GET | [`/sharing/shares/{share_id}/preview`](../../frontend/modules/hfl_shares/router.py#L1068) | ui | Presentation, redirect, authentication/session or host-desktop flow; browser-specific. |
| POST | [`/sharing/configurations/{configuration_id}/instant`](../../frontend/modules/hfl_shares/router.py#L1109) | deferred | Session-authenticated frontend operation; dedicated machine-facing service/auth contract is deferred. |
| GET | [`/sharing/shares/{share_id}/preview/manifesto`](../../frontend/modules/hfl_shares/router.py#L1201) | ui | Presentation, redirect, authentication/session or host-desktop flow; browser-specific. |
| POST | [`/sharing/shares/{share_id}/preview/chat`](../../frontend/modules/hfl_shares/router.py#L1226) | deferred | Session-authenticated frontend operation; dedicated machine-facing service/auth contract is deferred. |
| POST | [`/sharing/requests/{request_id}/approve`](../../frontend/modules/hfl_shares/router.py#L1284) | deferred | Session-authenticated frontend operation; dedicated machine-facing service/auth contract is deferred. |
| GET | [`/sharing/shares/{share_id}/preview/references/{reference_id}`](../../frontend/modules/hfl_shares/router.py#L2133) | deferred | Session-authenticated frontend operation; dedicated machine-facing service/auth contract is deferred. |
| GET | [`/sharing/shares/{share_id}/preview/references/{reference_id}/preview`](../../frontend/modules/hfl_shares/router.py#L2142) | deferred | Session-authenticated frontend operation; dedicated machine-facing service/auth contract is deferred. |
| GET | [`/sharing/shares/{share_id}/preview/references/{reference_id}/media`](../../frontend/modules/hfl_shares/router.py#L2151) | deferred | Session-authenticated frontend operation; dedicated machine-facing service/auth contract is deferred. |
| GET | [`/sharing/shares/{share_id}/preview/references/{reference_id}/thumbnail`](../../frontend/modules/hfl_shares/router.py#L2164) | deferred | Session-authenticated frontend operation; dedicated machine-facing service/auth contract is deferred. |
| GET | [`/share/access/{token}`](../../frontend/modules/hfl_shares/router.py#L1345) | protocol | Guest session/redemption or worker identity/lease protocol; not an owner CRUD operation. |
| GET | [`/share/email/{token}`](../../frontend/modules/hfl_shares/router.py#L1346) | protocol | Guest session/redemption or worker identity/lease protocol; not an owner CRUD operation. |
| POST | [`/share/access/{token}/redeem`](../../frontend/modules/hfl_shares/router.py#L1360) | protocol | Guest session/redemption or worker identity/lease protocol; not an owner CRUD operation. |
| POST | [`/share/email/{token}/redeem`](../../frontend/modules/hfl_shares/router.py#L1361) | protocol | Guest session/redemption or worker identity/lease protocol; not an owner CRUD operation. |
| GET | [`/share/pending`](../../frontend/modules/hfl_shares/router.py#L1450) | protocol | Guest session/redemption or worker identity/lease protocol; not an owner CRUD operation. |
| GET | [`/share/session`](../../frontend/modules/hfl_shares/router.py#L1806) | protocol | Guest session/redemption or worker identity/lease protocol; not an owner CRUD operation. |
| GET | [`/share/session/manifesto`](../../frontend/modules/hfl_shares/router.py#L1847) | protocol | Guest session/redemption or worker identity/lease protocol; not an owner CRUD operation. |
| POST | [`/share/session/chat`](../../frontend/modules/hfl_shares/router.py#L1859) | protocol | Guest session/redemption or worker identity/lease protocol; not an owner CRUD operation. |
| GET | [`/share/session/references/{reference_id}`](../../frontend/modules/hfl_shares/router.py#L2176) | protocol | Guest session/redemption or worker identity/lease protocol; not an owner CRUD operation. |
| GET | [`/share/session/references/{reference_id}/preview`](../../frontend/modules/hfl_shares/router.py#L2184) | protocol | Guest session/redemption or worker identity/lease protocol; not an owner CRUD operation. |
| GET | [`/share/session/references/{reference_id}/media`](../../frontend/modules/hfl_shares/router.py#L2192) | protocol | Guest session/redemption or worker identity/lease protocol; not an owner CRUD operation. |
| GET | [`/share/session/references/{reference_id}/thumbnail`](../../frontend/modules/hfl_shares/router.py#L2200) | protocol | Guest session/redemption or worker identity/lease protocol; not an owner CRUD operation. |
| POST | [`/share/session/logout`](../../frontend/modules/hfl_shares/router.py#L2208) | protocol | Guest session/redemption or worker identity/lease protocol; not an owner CRUD operation. |
| GET | [`/share/unavailable`](../../frontend/modules/hfl_shares/router.py#L2220) | protocol | Guest session/redemption or worker identity/lease protocol; not an owner CRUD operation. |

### frontend/modules/git_forks/router.py

| Method | Path | Coverage | Tool / rationale |
| --- | --- | --- | --- |
| GET | [`/git-forks`](../../frontend/modules/git_forks/router.py#L28) | service | `fork_fleet_latest` |
| POST | [`/git-forks/scan`](../../frontend/modules/git_forks/router.py#L40) | service | `fork_fleet_scan`, `fork_fleet_write_hfl_scan` |
| POST | [`/git-forks/sync`](../../frontend/modules/git_forks/router.py#L55) | service | `fork_fleet_sync` |
| POST | [`/git-forks/test`](../../frontend/modules/git_forks/router.py#L80) | service | `fork_fleet_test` |
| POST | [`/git-forks/deploy`](../../frontend/modules/git_forks/router.py#L100) | service | `fork_fleet_deploy` |

### frontend/modules/profile/router.py

| Method | Path | Coverage | Tool / rationale |
| --- | --- | --- | --- |
| GET | [`/profile`](../../frontend/modules/profile/router.py#L49) | ui | Presentation, redirect, authentication/session or host-desktop flow; browser-specific. |
| POST | [`/profile`](../../frontend/modules/profile/router.py#L61) | deferred | Session-authenticated frontend operation; dedicated machine-facing service/auth contract is deferred. |

### frontend/modules/app_settings/router.py

| Method | Path | Coverage | Tool / rationale |
| --- | --- | --- | --- |
| GET | [`/settings`](../../frontend/modules/app_settings/router.py#L12) | ui | Presentation, redirect, authentication/session or host-desktop flow; browser-specific. |
| POST | [`/settings`](../../frontend/modules/app_settings/router.py#L22) | deferred | Session-authenticated frontend operation; dedicated machine-facing service/auth contract is deferred. |

### frontend/modules/second_brain/router.py

| Method | Path | Coverage | Tool / rationale |
| --- | --- | --- | --- |
| GET | [`/second-brain`](../../frontend/modules/second_brain/router.py#L100) | ui | Presentation, redirect, authentication/session or host-desktop flow; browser-specific. |
| GET | [`/second-brain/feed-fragment`](../../frontend/modules/second_brain/router.py#L112) | ui | Presentation, redirect, authentication/session or host-desktop flow; browser-specific. |
| GET | [`/second-brain/api/feed`](../../frontend/modules/second_brain/router.py#L124) | deferred | Session-authenticated frontend operation; dedicated machine-facing service/auth contract is deferred. |
| GET | [`/second-brain/api/events`](../../frontend/modules/second_brain/router.py#L138) | deferred | Session-authenticated frontend operation; dedicated machine-facing service/auth contract is deferred. |
| POST | [`/second-brain/mode`](../../frontend/modules/second_brain/router.py#L174) | deferred | Session-authenticated frontend operation; dedicated machine-facing service/auth contract is deferred. |
| POST | [`/second-brain/mode/auto`](../../frontend/modules/second_brain/router.py#L201) | deferred | Session-authenticated frontend operation; dedicated machine-facing service/auth contract is deferred. |
| POST | [`/second-brain/refresh`](../../frontend/modules/second_brain/router.py#L216) | deferred | Session-authenticated frontend operation; dedicated machine-facing service/auth contract is deferred. |
| POST | [`/second-brain/settings`](../../frontend/modules/second_brain/router.py#L228) | deferred | Session-authenticated frontend operation; dedicated machine-facing service/auth contract is deferred. |
| POST | [`/second-brain/automatic`](../../frontend/modules/second_brain/router.py#L255) | deferred | Session-authenticated frontend operation; dedicated machine-facing service/auth contract is deferred. |
| POST | [`/second-brain/selection`](../../frontend/modules/second_brain/router.py#L279) | deferred | Session-authenticated frontend operation; dedicated machine-facing service/auth contract is deferred. |
| POST | [`/second-brain/delivery/{client}`](../../frontend/modules/second_brain/router.py#L298) | deferred | Session-authenticated frontend operation; dedicated machine-facing service/auth contract is deferred. |
| POST | [`/second-brain/categories`](../../frontend/modules/second_brain/router.py#L327) | deferred | Session-authenticated frontend operation; dedicated machine-facing service/auth contract is deferred. |
| POST | [`/second-brain/categories/{mode_id}/archive`](../../frontend/modules/second_brain/router.py#L392) | deferred | Session-authenticated frontend operation; dedicated machine-facing service/auth contract is deferred. |
| POST | [`/second-brain/agent-settings`](../../frontend/modules/second_brain/router.py#L406) | deferred | Session-authenticated frontend operation; dedicated machine-facing service/auth contract is deferred. |
| POST | [`/second-brain/chat`](../../frontend/modules/second_brain/router.py#L421) | deferred | Session-authenticated frontend operation; dedicated machine-facing service/auth contract is deferred. |
| POST | [`/second-brain/api/commands`](../../frontend/modules/second_brain/router.py#L458) | deferred | Session-authenticated frontend operation; dedicated machine-facing service/auth contract is deferred. |
