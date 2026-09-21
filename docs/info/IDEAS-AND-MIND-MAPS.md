# Graph, boards, and Goals

Open Activity Corpus → Explore → Graph. The existing graph canvas, filters,
presets, and inspector now share one workspace with saved boards in a collapsible
sidebar. **All activity** returns to exploration. `/hfl-corpus/ideas` and old
`?map=<id>` links remain compatible; new board selections use `?board=<id>`.

## Boards

A board has a name, required purpose, starting object, optional primary Goal,
chosen shared objects, draft thoughts, local connections, agent instructions,
and saved positions. Start from a graph node or **New board**. A question or
idea is sufficient: a Goal is optional. Choose **Save layout** after arranging.

**Add thought** creates a board-only draft. **Attach existing** references shared
context without copying it. **Connect on this board** creates a tentative
relationship that stays local. **Promote to shared Idea** atomically creates an
Idea and replaces the draft reference, root, layout, and local connections.
Connections remain local after thought promotion. Dashed lines identify local connections. Once both endpoints are shared, **Board connections → Promote shared connection** explicitly publishes a relationship to the graph. Use the existing Idea editor and
**Make actionable** to develop a promoted thought into committed work.

Removing a member or deleting a board never deletes shared objects. Deleting a
board deletes its local drafts. Shared object edits apply everywhere. Existing
maps retain IDs, layouts, members, and prompts; purpose defaults to their name.
The old Ideas navigation and map toolbar are replaced by the board sidebar.

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

Validation: targeted Ideas/boards/Goals, agent bridge, timeline and graph API tests,
plus browser coverage at mobile and desktop sizes and graph layout tests.
