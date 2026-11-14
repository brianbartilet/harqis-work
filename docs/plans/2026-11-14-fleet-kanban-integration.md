# Second Brain Fleet and Kanban integration

## Approved scope

Second Brain links to a separate Kanban page, like the HUD. Kanban has a loading
splash until its first refresh completes (including errors), and a robot icon beside
Ideas returns to Fleet. The Fleet toolbar is not rendered on Kanban. Both pages use the existing canonical
actions, ideas, Spaces, editors, connections and agent-session dialogs. Existing
Kanban URLs remain valid. Distill links to Second Brain.

- Butler briefings request Markdown and render through the shared sanitizer.
  Playback starts automatically, loops after a pause at the bottom, pauses on manual
  interaction, and respects reduced motion. A play/pause control sits beside Refresh.
- Fleet includes assigned actions, generated ideas monitored by Butler, manual
  orphans, explicit graph connections, and attributable corpus entries.
- Action colors: yellow for In Review/Ready/In Progress, red for Incomplete,
  green for Done, grey for dismissed items. Inactive agent orbs are grey.
- Shared action/idea controls open locally, including history, connections and
  sessions. Kanban Agents buttons show current assignment avatars.
- Sharing is a persistent child of Butler representing the existing shared-page
  Hermes assistant. Sanitized sharing-audit entries provide its historical and
  future activity. It cannot launch a second worker through the fleet session API.
- Create offers Entry, Action and Idea. Add agent uses the blue button style.

## Reused implementation

| Surface | Existing source |
| --- | --- |
| Sanitized Markdown | `frontend/services/markdown.py` |
| Action cards and dialogs | `frontend/static/js/hfl-timeline.js` |
| Ideas, promotion, cloning and connected actions | `frontend/static/js/hfl-ideas.js` |
| Kanban | `frontend/static/js/hfl-followups.js` and `partials/followups_board.html` |
| Entry capture | `partials/entry_capture.html` and `entry-capture.js` |
| Avatars | `frontend/static/js/agent-avatar.js` |
| Corpus permissions | `ideas_api.permitted_snapshot` and `entities.current_entries` |

`fleet-intent.jsx` adapts these controls without introducing another command API.
`corpus_projection.py` overlays canonical status on recorded execution history.
Refreshes are serialized; failed corpus refreshes retain the last displayed records
with a warning. Local mutations trigger refreshes, in addition to periodic polling.

## Review: risks, gaps and requirements drift

| Finding | Resolution / remaining limit |
| --- | --- |
| Raw briefing text and unsafe HTML | Markdown rendered and sanitized on the server; script-tag regression checked. |
| Legacy scheduled deliveries identified by exact prompt | Both old and Markdown prompts remain recognized. |
| Very small scrolling increments rounded to zero | Accumulate fractional movement before updating scroll position. |
| Duplicated Space picker and shortcut selector collision | Standalone Kanban retains the original Space controls; Add agent shortcut targets its button specifically. |
| Mobile inspector overlapped controls | Compact toolbar and larger selected-item scroll region; desktop/mobile browser checks. |
| Native dialogs inert in fullscreen | Dialog elements excluded from fullscreen background inert handling. |
| Promoted ideas disappeared; manual connections omitted | Fleet requests promoted ideas and includes canonical shared relationships. |
| Stale assignment/status receipts | Canonical status wins; current assignments replace old assignment edges while producer history remains. |
| Invented historical attribution | Only agents-activity receipts are parsed as JSON; top-level IDs or unique legacy names establish attribution. Nested/quoted IDs and ordinary notes are ignored. Sharing uses its dedicated audit source. |
| Canonical-host version mismatch | Deploy the snapshot API update with the frontend so `include_promoted=true` is supported remotely. |
| Large corpus cost | Permission-context-keyed corpus cache coalesces concurrent reads for 30 seconds per process on both Fleet and canonical snapshot hosts. Intent records remain live. Assignment edges are reconciled in one pass. Production corpus I/O latency remains unmeasured. |
| Changes outside scope | No voice, “me” node, unused-entity deletion, new external gateway surface, or new schedule was added. |

Sharing access boundaries and sanitization remain unchanged. Existing assignment
storage selects one agent per action; the thumbnail presentation accepts the returned
list and does not invent additional assignees.

## Validation and delivery

Focused Python suites cover fleet, ecosystem, briefings, shortcuts, intent projections,
board behavior and Distill. JavaScript tests cover graph filtering, orphan visibility
and source links. Browser checks cover desktop/mobile layouts, inline edits, status
updates, history, sessions, idea editing, entry capture opening, Markdown, playback
looping and manual pause. Existing board menu assertions were updated to the labels
already present on main: Edit, Dismiss, Promote and Clone.

The isolated local mock runs at `http://127.0.0.1:8097/preview`, with data and its launcher
under the ignored `.harqis-data/fleet-review/` directory. It uses synthetic records,
separate stores, no workers and blocked external HTTP calls. Mock entry capture writes
only to its local corpus; file uploads are disabled in that preview.

Implementation is on local `main`. Action `item-3aea00d9efcb44428b8d0856025a7b03`
must remain open until the changes are merged; its additional requested extras were
explicitly deferred by the owner.

## P2 remediation validation

- Assignment thumbnail polling runs only on Kanban. Page replacement clears its
  timer, removes its listener, aborts its request and discards late results.
  Overlapping refresh triggers coalesce into a single follow-up request.
- Cache hits avoid corpus scans; expiry and source/credential/profile/secret-tag
  context changes reload. Failed reloads propagate instead of returning expired data.
  The canonical snapshot API uses the same cache only for Fleet's promoted-inclusive
  request; current action/idea records are still fetched on every request.
- Newly ingested activity and entry-level changes can take up to 30 seconds of
  cache lifetime plus the next 15-second Fleet poll to appear. Profile secret-tag
  changes invalidate the cache immediately on the next read. Each server process
  has its own single-entry cache; deploy both hosts for the remote-path benefit.
- Eight focused non-browser checks pass, including eight concurrent readers sharing
  one scan, expiry, permission-context changes, source failure, and live statuses.
  Browser validation observes zero assignment requests after lifecycle cleanup.
- A synthetic 10,000-action/10,000-edge projection measured 99 ms initially and
  128 ms on repeat locally. These timings exclude corpus I/O and are not a
  production-load benchmark.
