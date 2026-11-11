# Second Brain web HUD

## Workspace navigation

**Express → Second Brain** opens the agent fleet workspace at `/agents`.
The highlighted brain icon at the start of the workspace toolbar opens the
full dashboard at `/second-brain`. Its robot-icon shortcut
returns to the workspace, preserving the originating agent when supplied.
Both pages show a full-screen loading splash with indeterminate progress during navigation and initial data loading. The splash clears on success or failure, leaving errors and retry controls accessible. Reduced-motion preferences are respected. The dashboard robot icon sits before Add widget and returns to the Second Brain workspace.
Build no longer contains an Agents entry. Existing routes and agent deep links
remain supported.

Activity Corpus, Activity Graph, Kanban, the workspace, and the dashboard use
shared saved Space preferences, including multiple Spaces, All activity, and
schedule-driven Dynamic mode. Fleet and dashboard retain separate controls,
widget ordering, sizing, and appearance; widget Space membership remains shared.
The advisory feed's categories and execution schedules are unchanged.

## Refresher: what Second Brain already does

Second Brain is an advisory context service, not a general-purpose agent runner.
`workflows/second_brain/store.py` holds versioned category configuration, typed
context events, decisions, temporary overrides, feed revisions, run history and
short-lived chat in SQLite. The canonical database belongs on local disk, not SMB.

The resolver combines current Calendar categories, keywords and configured
fallback windows. Manual category choices take precedence for 30Ã¢â‚¬â€œ720 minutes,
then expire back to Automatic Feed. Optional loopback Hermes proposes a typed
candidate; deterministic validation and the operation allowlist remain authoritative.
Celery Beat starts reconciliation every 15 minutes; due-operation checks avoid
unnecessary collection. One failed source does not remove other feed items.

The web client is always enabled. Telegram, CLI and Rainmeter delivery are opt-in
and structurally redacted. The existing feed/chat/category controls now live at
`/second-brain/feed` (Feed & settings). Their endpoints and SSE protocol remain
available. The main `/second-brain` route opens the new HUD.

## Capability comparison

| Capability | Previous Second Brain | Web HUD migration |
|---|---|---|
| Context resolution | Calendar, keywords, manual override, optional Hermes | Reused unchanged in Context feed |
| Presentation | Ranked cards in a feed dialog | Persistent six-column dashboard, ten sizes, scrolling |
| HUD inputs | 18 read-only projection adapters | All 18 in Add widget, independent of category attachment |
| Spaces | Separate Second Brain categories | Shared Corpus/Kanban manual/dynamic Space selection; widget membership |
| Customization | Category operation assignments | Add, hide/restore, remove, drag, keyboard reorder, snap resize |
| Mobile | Responsive feed | One column, preserved row spans, internal and page scrolling |
| Motion | Feed ticker | Per-widget static, marquee or typing; pause and reduced motion |
| Monitoring | Failed-job/schedule text | Same captures plus interactive Kibana dashboard embeds/links |
| Agent building | Advisory-only chat | Create a canonical action with skill hashes; open existing Kanban agent workspace |
| Desktop coupling | Rainmeter writes and local paths | Portable output default; desktop rendering is deprecated opt-in |

Spaces and categories are intentionally distinct: a Space selects which widgets
are visible; the Context feed still follows the Second Brain decision. No Space
links means visible everywhere. Dynamic mode uses existing Space schedules and
profile timezone. The dashboard polls shared preferences every 30 seconds and
reacts to the existing `corpus:workspace-change` cross-tab event. It does not
replace category settings or silently mutate their operation bindings.

## Source audit and data path

See [HUD source inventory](HUD-SOURCE-INVENTORY.md): 19 metered panels, 20 enabled
schedule entries, including ancillary capture/support work. Eighteen source
panels have explicit adapters; the nineteenth is the Second Brain Rainmeter
delivery client and is excluded from recursive ingestion.

```text
existing app collectors Ã¢â€ â€™ @feed dump / execution log Ã¢â€ â€™ redacted HUD projection
                                                     Ã¢â€ â€œ
                             /second-brain/hud/data Ã¢â€ â€™ dashboard
typed context Ã¢â€ â€™ resolver Ã¢â€ â€™ canonical feed snapshot Ã¢â€ â€™ Context feed widget
```

`init_meter` defaults to returning the original text, summary/metrics and HTTP(S)
header links without writing skins, starting Rainmeter, beeping or waiting for
desktop refreshes. Previously its return value could omit dump text, leaving
projections with only metadata. The legacy render path now preserves text too.
The daily-radar host fallback publishes with the original radar source identity.
Skipped collectors do not publish misleading successful captures.

`workflows.second_brain.migrate_hud_dumps` provides an explicit one-time backfill.
Its default is a metadata-only preview; `--publish` ingests bounded, redacted
`dump.txt` files only beneath the configured Rainmeter skin root and only for
registered sources. It preserves file timestamps and writes a separate
`harqis-second-brain-hud-migration` index, leaving live captures untouched. During
this implementation, 14 nonempty legacy dumps were ingested. Empty command-only
panels were skipped. Old workers can continue publishing metadata while the HUD
uses the migration text; new text-bearing captures take precedence.

The dashboard performs bounded reads of the live and optional migration projection indexes, cached for
30 seconds, using an eight-second request timeout. Missing data stays explicit;
old data is marked stale. It never imports a browser-supplied task path, executes
a collector on page load, or reads arbitrary local files. Initial historical
dump text is capped at 12,000 characters under the existing projection policy.

Windows foreground-window, mouse, AutoHotkey and screenshot sources still need
the Windows worker. Portable API collectors now use the host queue, while desktop and TCG fulfillment
retain Windows affinity. The duplicate radar fallback schedule has been removed. A stopped
source remains visible as a cached, stale capture. Existing desktop-only profile
and command launchers become read-only context; the browser does not execute INI
commands. Hotkeys is a starter control, with desktop bindings available as widgets.

## Layout and visual behavior

The screenshot reference is `docs/images/windows-hud-sample.png`: dark translucent
panels, blue rules, uppercase compact headers, and monospace body text. The web
implementation uses the existing HARQIS palette and navigation. Space colors,
selection preferences, CSRF and revision-conflict behavior come from
`frontend/modules/hfl_corpus/workspace_views.py`. Dialogs use native focus trapping;
selects use the established blue SVG chevron. Local SortableJS supplies touch drag.

Sizes: 1x1, 1x2, 1x3, 1x4, 2x1, 2x2, 2x4, 3x1, 3x3, 3x4. Arrange exposes a drag handle,
Earlier/Later controls and a resize corner that snaps to the closest allowed
size. Settings provides the keyboard/mobile size picker. Widget order packs into
six columns; overflow extends down the page. Mobile uses one column and preserves
the row count. Layouts persist in the profile SQLite database with atomic revision
checks; stale tabs cannot overwrite newer layouts unnoticed.

## Agent creation and reusable skills

Build with agent accepts a title and prompt, creates a canonical Activity Corpus
action, attaches current Space IDs, includes the build instructions and SHA-256
versions of `create-new-hud`, `create-new-service-app`, `create-new-workflow`, and
opens its existing Kanban agent workspace. That workspace owns Hermes/other
configured runtime selection, terminal sessions and execution. Creating the action
does not silently execute its prompt. No new unrestricted subprocess endpoint is
introduced into Second Brain chat.

`create-new-hud` now defaults to portable web widgets. The previous Rainmeter
instructions remain in its `references/rainmeter-legacy.md` for explicit legacy
maintenance. New integrations still use `create-new-service-app`; new deterministic
pipelines still use `create-new-workflow`. Existing integrations are reused here,
so this migration adds no new app or credentials.

## Monitoring / Kibana exploration

Add Monitoring / Kibana, then choose a saved dashboard's share URL in settings.
A read-only check of the configured stack on 2026-10-24 returned available status
and one saved dashboard. The origin must match the frontend host's `KIBANA_HOST`; credentials in URLs and
unrelated origins are rejected. The iframe supports Kibana interactions using
the browser's own Kibana session, with an Open Kibana fallback link. Cross-origin
dashboard filters cannot be controlled directly by HARQIS JavaScript. Space
membership can select different dashboard widgets; no automatic translation of
Corpus predicates into Kibana queries is claimed.

Elastic supports [interactive dashboard embeds](https://www.elastic.co/docs/explore-analyze/dashboards/sharing).
Cross-site sessions may require `xpack.security.sameSiteCookies: None` and secure
cookies; embedding must not be disabled by Kibana response headers. Review the
[authentication guidance](https://www.elastic.co/docs/deploy-manage/users-roles/cluster-or-deployment-auth/kibana-authentication)
and [security settings](https://www.elastic.co/docs/reference/kibana/configuration-reference/security-settings)
for the deployed stack. This feature does not change those server settings,
enable anonymous access, or proxy Kibana credentials into the page.

## Automation runtime decision

**Classification:** hybrid. **Confidence:** high.
**Reasoning:** existing deterministic collection and persistence are separate from
open-ended widget building and optional context interpretation.
**Execution owner:** Celery for source collection/reconciliation; frontend for
read-only projection and layout CRUD; existing Kanban/Hermes runtime for builds.
**Schedule owner:** existing Celery Beat schedules; widget builds are manual.
**Celery operations:** existing collectors, logging and reconciliation only; no
duplicate Beat initiator is added.
**Agent responsibilities:** implement requested widgets in reviewable branches;
advisory context interpretation retains its existing boundary.
**Controls:** source allowlist, projection redaction/caps, authenticated reads,
CSRF writes, revision checks, action request IDs and skill hashes. Existing agent
bridge records run correlation and execution evidence.
**Review artifacts:** this comparison, source inventory, tests, branch and PR.

## Rollout and rollback

Deploy this branch to the host worker and Windows worker for text-bearing captures,
then restart the single host Beat to activate the portable routes. Verify task
registration before Beat restarts. Keep the migration index until live sources
have usable text; each fresh live capture automatically supersedes its backfill.
Rollback requires restoring the previous worker code and Beat configuration together.

Legacy desktop rendering can be restored with `HARQIS_LEGACY_RAINMETER=1`, or
`render_legacy_hud=True` on a task invocation. Existing skins may stay visible
until manually unloaded; the migration does not erase user desktop layouts.
The canonical feed UI remains reachable at `/second-brain/feed` for comparison.

## Validation record

- 57 focused tests passed across the dashboard API, existing Second Brain feed,
  shared Spaces, Rainmeter portable return contract, projection policy and dump
  migration. A separate Windows process-lock/projection run passed 15 tests; the
  final projection/backfill/web-contract check passed 14 after adding source-alias
  coverage. These runs overlap; they are not additive unique-test counts.
- Browser validation used the locally installed Edge engine: all eight original sizes,
  authenticated persistence, hide/restore/remove, keyboard reorder, pointer drag,
  snap resize, full screen, mobile stacking/no page overflow, Hotkeys and agent
  handoff. The builder's final action creation was intercepted to avoid creating
  an artificial live action; its real skill context and request payload were checked.
- The configured Kibana dashboard rendered its dashboard panel and chart inside
  the HUD iframe. Typing, pause, reduced-motion switching and marquee scrolling
  passed in the browser.
- Initial UI validation used existing captures and the bounded backfill. The
  subsequent authorized backend rollout below exercised read-only collectors.

## Backend rollout verification — 2026-10-24

The feature branch was deployed to the macOS host worker, scheduler and frontend;
the Windows HUD and capture workers were restarted. Live inspection confirmed
portable task registration on macOS and the original desktop queue subscriptions
on Windows. Exactly one host Beat process was present. The draft PR remains
unmerged; the host runtime currently tracks its feature branch.

Nine server collectors produced fresh text-bearing web projections: Calendar,
YNAB, PC sales, forex, API costs, Jira, failed jobs, schedules and Hermes radar
refresh. The Windows mouse-binding collector also produced fresh web text. The
authenticated host HUD endpoint reported no source-read error and included the
canonical Context feed. A pre-existing directory at `workflows.mapping` blocked
both job-summary exports; the collector now writes inside that directory when
present, while preserving the legacy file path otherwise.

Portable output/routing/projection checks passed on Windows (20 tests) and macOS
(13 tests). The additional routing and directory-mount regression suite passed
four tests on each platform. These runs overlap and are not additive coverage.
The frontend task catalogs were regenerated on both hosts; retained portable
manual aliases use `host`, and the old radar twin is marked manual-only.

The 14-document migration index is retained for slower or not-yet-refreshed
sources. TCG fulfillment, desktop summaries and daily radar synthesis were not
manually forced during rollout; their existing schedules remain responsible.
No sell-cart operation or agent build was manually executed. Legacy Rainmeter
opt-in is Windows-only and does not relocate host collectors back to Windows;
full rollback must restore the old routes and scheduler configuration too.
