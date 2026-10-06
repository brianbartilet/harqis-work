# Graph, boards, and Goals

Open Activity Corpus → Explore → Graph. The existing graph canvas, filters,
presets, and inspector now share one workspace with saved boards in a persistent
sidebar. **Explore Activity Graph** returns to exploration. Only the saved-board
list collapses; **Add Board**, **Add Goal**, and active-board controls stay available. `/hfl-corpus/ideas` and old
`?map=<id>` links remain compatible; new board selections use `?board=<id>`.

## Boards

A board has a name, required purpose, starting object, optional primary Goal,
chosen shared objects, draft thoughts, local connections, agent instructions,
and saved positions. Start from a graph node or **Add Board**. A question or
idea is sufficient: a Goal is optional. Thoughts, connections, and drag layouts
update immediately and save in the background. **Save now** flushes pending edits;
the status distinguishes **Saving**, **Saved**, and **Unsaved**. A failed save
keeps edits in the open tab with **Retry save**. Conflicts never silently overwrite
another revision; **Resolve unsaved changes** lets you copy pending edits before
explicitly discarding them and reloading the saved board. Wait for **Saved** before
closing the workspace. **Save layout** captures current node positions and queues autosave; dragging
already captures positions automatically. **Save now** sends all pending content
and layout changes immediately.

Choose a board color from the shared Memory Signal pin palette at creation or in
**Settings**. The card indicator and active-board panel use that color. Drag board
cards to reorder them, or focus a card and use Alt + Up/Down. Order is saved on
the server independently of board content revisions. Color indicators sit on the
left of each card. A separate collapsible **Goals** list uses the same palette
and drag/Alt + Up/Down ordering. Click a Goal to edit it and its color; editing
an existing Goal does not attach it to the active board. Colors and ordering
are presentation settings and do not produce HFL memory entries.

New boards have creation/update timestamps and an editable **Board date** (today
by default). The Activity Graph shows a board node linked to that date and its
optional primary Goal. **Open board** enters its workspace. Legacy boards retain
unknown creation timestamps; set their Board date in settings to place them on
the timeline. Board-only drafts never appear as shared graph nodes.

**Add thought** creates a board-only draft. **Attach existing** references shared
context without copying it. **Connect on this board** creates a tentative
relationship that stays local. **Promote to shared Idea** atomically creates an
Idea and replaces the draft reference, root, layout, and local connections.
Connections remain local after thought promotion. Dashed lines identify local connections. Once both endpoints are shared, **Board connections → Promote shared connection** explicitly publishes a relationship to the graph. Use the existing Idea editor and
**Make actionable** to develop a promoted thought into committed work.
Alternatively, **Create linked Idea** or **Create linked Actionable** on a thought
opens the existing editor, retaining the thought and adding the saved object
with a board-local connection. Creating an Actionable does not execute it.

Board lists and Goal choices use a dedicated metadata endpoint. Board edits use
cached member data and update the canvas without a full graph reload or viewport
reset. Attaching existing objects and initially loading uncached shared members
still perform permission-checked server reads. **Refresh** revalidates shared
members against the server.

The Attach existing picker searches on the server and shows 50 objects per page,
excluding current members. Results sort by latest update, using the latest
supporting entry date when an entity has no newer profile update. Loading has a
spinner and failed requests can be retried. The picker and attachment validation
reuse a permission-filtered catalogue without constructing the full corpus graph;
each request still reads the permitted corpus to keep access checks current.

Removing a member or deleting a board never deletes shared objects. Deleting a
board deletes its local drafts. Shared object edits apply everywhere.
Deletion waits only for an in-flight save, skips unsent edits, and shows progress
through the return to All activity. A failed deletion retains the board and its
pending edits so the owner can retry.
Existing maps retain IDs, layouts, members, and prompts; purpose defaults to their name.
The old Ideas navigation and map toolbar are replaced by the board sidebar.

## Activity workspaces

Activity Graph shares Workspace selection and Dynamic mode with Corpus and Kanban.
Selected workspaces include explicitly assigned boards; All activity also includes
unassigned boards. New boards default to every currently selected workspace.
Use Add → Existing board to add a board to those workspaces, or Settings to edit
its assignments. Removing an assignment preserves the board and its contents.

Opening an assigned board shows all authorized members, including members outside
the selected workspace filters. Those members are dimmed and labeled in the
inspector and node list. Changing workspace finishes pending board saves first;
if the board is excluded, Graph returns to exploration. A save failure retains
edits and offers Retry. Goals remain workspace-agnostic, and Entities opens the
full authorized directory. Presets and animations remain graph controls.

Future recipient sharing is intended to include full assigned-board contents,
including drafts, local connections, and attachments. This workspace integration
does not implement that sharing or broaden existing recipient access.

## Goals

Goals are shared graph objects with a title, description, success criteria,
status (proposed, active, paused, achieved, dropped), optional target date,
progress notes, supporting Ideas/Actions, and embedded milestones. Each milestone
has a stable ID, title, status, optional date, and links to Actions. Milestones
are intermediate outcomes, not duplicate task checklists. Achievement is explicit:
completed milestones or Actions never automatically mark a Goal achieved.
A Goal can be referenced by multiple boards and optionally serve as their root.

Ideas and actions have one Markdown description, supporting
files, and named interactive checklists. Checklist items can be edited, checked,
reordered, and removed. Dismissal retains an idea and all its connections; edit
its status to restore it. Dismissed graph nodes remain visible with muted styling.

Checklist ordering supports dragging an item row (including touch) and arrow keys
while focused on a row. Click item text to edit it. Delete and conversion icons
appear on hover or keyboard focus, and remain visible on touch devices. Each
checklist shows percentage progress and has a **Checklist cover** preference. Enabled
covers show progress and up to five interactive items on corpus cards, with
**See full list** for longer lists. Existing records receive `checklists: []` and
`cover: false` defaults through an additive, repeatable migration; IDs, versions,
and historical audit snapshots are retained.

Graph action forms reuse the existing Create Actionable template. Ideas use the
same form styling with Details, Checklists, and Attachments sections. Markdown
renders on blur and returns to editing when clicked. Uploads use one shared picker.
The `object_content` module owns shared description/body/checklist validation;
Ideas and Actionables retain distinct status and execution fields.
Legacy descriptions are consolidated into Markdown without changing IDs, versions,
or historical snapshots. Distinct description text precedes the existing Markdown;
identical descriptions appear once. The combined field accepts 60,000 characters.
Actionable forms place Prompt after Markdown, followed by supporting files. The **Action plan**
section starts collapsed and contains Expected outcome, Review on, Complete by,
and Notes. Validation opens it when required information is missing.

## Conversion

**Make actionable** opens an editable draft and copies descriptions, checklist
structure, applicable priority/outcome fields, evidence, topic links, and selected
attachments. Checklist completion resets. The action receives a fresh identity,
creation date, and `open` status. Agent execution is disabled for the new action.
One idea can produce several actions. The idea stays editable and each action
has an explicit `develops-into` link.

An individual checklist item's **Make actionable** is enabled only for a saved Idea
with no pending edits. Save and reopen the Idea after editing to enable it. It
opens a draft titled from that item (up to 200 characters), preserving its
full text as the expected outcome. Parent descriptions and selectable attachments
are inherited; sibling checklist items are omitted. Saving atomically records both
the Idea-to-Actionable graph edge and stable checklist/item provenance in
`idea_item_actions`. Reopening the Idea offers **Open actionable** beside the item.
Checklist completion and action status remain independent; removing an item does
not delete its action or provenance. Conversion query/body fields `checklist_id`
and `item_id` select this mode. Retries include that provenance in their receipt.

Files are immutable content-addressed blobs. Conversion creates independent
attachment ownership records in the same SQLite transaction as the action and
relationship. A missing/detached file aborts conversion. Retrying the same request
reuses the action; removing files from either object preserves the other's files.
Additional uploads and map membership are retryable subsequent operations; the
editor reports a saved object when these remaining operations need retrying.

Creation/generation dates and historical source dates use separate graph edges.
Creation days are resolved in Asia/Singapore. Existing suggestions retain stable
IDs and their earliest recorded generation time. Owner edits are stored separately
from generated content, so a refresh cannot overwrite them.

## Persistence and APIs

The canonical `HFL_TIMELINE_STORE_PATH` database contains idea edit/history,
manual-topic, relationship, board, Goal, and Goal-history tables alongside existing follow-ups
and generated suggestions. These tables are initialized additively. Remote
frontends forward commands to the canonical host; they do not create local twins.

Owner endpoints live under `/hfl-corpus/timeline/ideas`; bearer-authenticated
canonical equivalents use `/api/hfl/timeline/ideas`. They cover `objects`,
`objects/{id}/conversion`, `objects/{id}/convert`, `topics`, `links`, `maps`,
`snapshot`, `goals`, `maps/{id}/promote`, board deletion, and source-scoped attachments. Updates require the current version.
Content access and node linking are checked against the permitted corpus
projection. The existing action APIs accept description, body, and checklists.

## Automation Runtime Decision

**Classification:** agent (existing bridge; no new workflow or schedule).

**Confidence:** high.

**Reasoning:** the agent interprets the map and proposes useful branches. The
canonical API performs validated, retryable persistence only after owner review.

**Execution owner:** the existing leased agent bridge runs brainstorming; owner
API handlers save accepted board-only thoughts and local relationships.

**Schedule owner:** manual. Saving an object or map never queues brainstorming.

**Celery operations:** existing bridge infrastructure may dispatch/deliver runs;
this feature adds no Celery task and no periodic schedule.

**Agent responsibilities:** plan, interpret selected context, propose up to 12
ideas with existing parent IDs, or request clarification. No corpus mutations or
external actions are authorized by the brainstorming prompt.

**Required controls:** owner authentication and CSRF for run commands; immutable
prompt hash and context snapshot; worker leases; run/request IDs; review-only
completion; validated parent IDs; deterministic per-proposal creation IDs.

**Review artifact:** bridge plan/progress/result history and the brainstorming
dialog. Review proposals individually or accept a complete set as draft thoughts; **Finish review** closes
the run. Agent availability is required for execution. Queued/failed/awaiting-input
states remain visible and can be cancelled or continued.

**Open questions:** none.

New boards can start with an agent-generated draft: enter the purpose, choose
that option, then request suggestions in the review dialog. The agent can support
personal decisions, feature design, or developing ideas into actions. Saving a
board alone does not run an agent. Accepted proposals remain drafts until promoted.

### Thought and Goal memory

Creating a thought or Goal, or changing its saved content, records a new immutable
HFL entry under **manual-entry**. Updates preserve earlier snapshots rather than
overwriting them. Thoughts capture title/body changes; Goals also capture status,
success criteria, target date, progress, milestones, and linked-object changes.
Unchanged saves, layout changes, connections, and delivery retries do not add entries.
Accepted agent thoughts use the same path; unaccepted proposals are not captured.
Existing objects are not backfilled merely by loading them.

Memory events commit atomically with the object in the intent database. The existing
Celery `flush_hfl_outbox` job (every five minutes) transfers them to the durable HFL
outbox for canonical daily Markdown and search indexing. Delivery failures retry;
board editing never waits for the broker, indexing, or corpus refresh. Runtime and
schedule ownership stay with that existing Celery job; no new schedule is added.

Entries use the save time in Asia/Singapore, independently of the board date or
Goal target date. Each contains a snapshot, stable object/revision reference, and
a link back to the thought's board or Goal. **View memory history** opens the
corpus search for that object's stable memory key. Goal and board graph nodes link
to their permitted memory entries and event dates after indexing. Draft nodes
remain board-local, but their saved text is searchable in HFL. Deleting an object
does not erase its historical memories; its old navigation link may no longer resolve.

Validation: targeted Ideas/boards/Goals, agent bridge, timeline and graph API tests,
plus browser coverage at mobile and desktop sizes and graph layout tests.
