# HFL Memory Signal as a Calendar, Idea Board, and Agent Action Layer

The strongest direction is to evolve Memory Signal into a **temporal memory and
intent layer**: one place that shows what was planned, what actually happened,
what ideas emerged, and what agents can do next.

The differentiator should not be "another calendar" or "another Trello." It
should be the feedback loop between personal history, future intent, and
verified action.

## What exists today

The repository already provides a strong foundation:

- Immutable, provenance-rich HFL entries with timestamps, source, stable entry
  ID, tags, references, and synthesized status in
  [`workflows/hfl/dto/entry.py`](../../workflows/hfl/dto/entry.py).
- A multi-year activity heatmap with day-level entry recall and filtering in
  [`frontend/modules/hfl_corpus/corpus.py`](../../frontend/modules/hfl_corpus/corpus.py).
- Owner-local Memory Signal categories and date ranges, including dates up to
  five years ahead, in
  [`frontend/modules/hfl_corpus/memory_pins.py`](../../frontend/modules/hfl_corpus/memory_pins.py).
- Manual capture with attachments, location enrichment, Markdown persistence,
  and Elasticsearch projection.
- Period-based, agent-readable recall through read-only MCP tools in
  [`workflows/hfl/mcp.py`](../../workflows/hfl/mcp.py).
- Granular, idempotent Trello action ingestion and a read-only activity preview.
- An operational Trello agent framework that can claim cards, move them,
  comment, complete checklist items, and pause for human input.
- Second Brain feed items already have `actions`, confidence, priority, expiry,
  source references, and correlation IDs, although the workflow remains
  intentionally advisory-only in
  [`workflows/second_brain/models.py`](../../workflows/second_brain/models.py).

The important gaps are:

- Memory pins are annotations, not real events or tasks.
- `HflEntry` describes what happened; it has no lifecycle, due date,
  recurrence, reminder, or dependency.
- Corpus MCP tools are intentionally read-only.
- Calendar access is currently retrieval-focused; Google Tasks already
  supports writes.
- Trello actions enter HFL as history, but HFL ideas cannot yet become Trello
  work.
- There is no explicit planned-versus-actual reconciliation.

## Recommended architecture

Keep three distinct layers:

```text
Evidence / Memory
Immutable HFL entries and references
            |
            v
Intent / Planning
Ideas, events, tasks, commitments, reminders
            |
            v
Action Plane
Agent proposals -> approval policy -> external action
            |
            v
Action Receipt
Result, failure, or completion written back to HFL
```

Do not add mutable task state directly to `HflEntry`. Historical entries should
remain trustworthy evidence.

Instead, introduce a `MemoryObject` or `TemporalObject` model:

```text
id
kind: idea | event | task | commitment | reminder | milestone | habit
title, description
start_at, end_at, due_at, timezone
status: inbox | clarified | ready | active | waiting | done | dismissed
recurrence_rule
priority, confidence, sensitivity
source_entry_ids[]
parent_id
assignee: human | agent profile
external_bindings[]     # Google event, Trello card, Google Task
created_by: human | rule | agent
version, created_at, updated_at
```

Supporting models:

- `MemoryLink`: relates objects and HFL entries with typed relationships such
  as `supports`, `caused_by`, `follow_up_to`, `contradicts`, and `same_project`.
- `Reminder`: channel, offset, delivery state, and acknowledgment.
- `ActionProposal`: proposed operation, reason, evidence, risk, and approval
  state.
- `ActionExecution`: idempotency key, lease owner, attempts, outcome, and
  external ID.
- `ExternalBinding`: provider, account, external object ID, sync cursor, and
  last observed version.
- `RecurrenceRule`: RRULE-like rule, exceptions, and bounded occurrence
  expansion.

Markdown remains the evidence source of truth. A transactional relational store
owns mutable intent and action state. Elasticsearch and future vector indexes
remain rebuildable projections.

## Calendar-like features worth adding

### 1. Layered timeline

Give the calendar four independently toggled layers:

- **Planned:** events, deadlines, reminders, and habits.
- **Observed:** HFL entries and ingested activity.
- **Inferred:** detected focus periods, travel, meetings, and project bursts.
- **Follow-ups:** ideas, open commitments, and agent proposals.

This is much more valuable than displaying HFL entries as ordinary events.

### 2. Day, week, month, agenda, and life views

The current heatmap is already an excellent life view. Add:

- **Day view:** chronological evidence and scheduled intent.
- **Week view:** time blocks, tasks, capacity, and unresolved commitments.
- **Month view:** milestones and patterns.
- **Agenda view:** next actionable items.
- **Life view:** retain the existing multi-year Memory Signal heatmap.

Clicking a date should open one unified day sheet rather than only matching
corpus entries.

### 3. Planned-versus-actual reconciliation

At the end of a time block, HARQIS can compare:

- What was scheduled.
- Which apps or projects were actually active.
- Related Git, Jira, Trello, location, notes, and agent activity.
- Whether the intended outcome occurred.

Possible results:

- Completed as planned.
- Completed differently.
- Interrupted or displaced.
- No evidence of work.
- Evidence exists but attribution is uncertain.

This is a compelling moat because normal calendars generally stop at
intention.

### 4. Memory-aware scheduling

Use historical evidence to answer:

- How long do similar tasks usually take?
- At what time of day was this kind of work successful?
- Which meetings commonly generate follow-ups?
- What usually displaces planned deep work?
- Is this week overloaded compared with previous successful weeks?

Recommendations should always show their supporting past entries.

### 5. Commitments and follow-up extraction

Detect phrases from notes, conversations, meeting descriptions, and agent
sessions:

- "I'll send this Friday."
- "Follow up next month."
- "We should investigate..."
- "Waiting for Alice."
- "Remind me when..."

Create a proposal, not an automatic task, unless the source and rule are
explicitly trusted.

### 6. Recurrence and routines

Support:

- Standard recurrence rules.
- "After completion" recurrence.
- Context-triggered recurrence: after returning to a location, after a card
  moves, or after receiving a reply.
- Review cadence: resurface an idea in seven days unless promoted or dismissed.
- Habit evidence: infer completion from Activity Corpus sources rather than
  relying only on a checkbox.

### 7. Calendar synchronization

Start with one-way Google Calendar ingestion, then add controlled export.

Every imported event needs a stable external binding, version token, timezone,
and deletion or cancellation handling. Avoid copying Calendar events into HFL
repeatedly; maintain the mutable event in the intent store and create HFL
evidence only for meaningful changes or completed-event retrospectives.

## Trello-like idea capture

A lightweight native workflow would fit the corpus better than immediately
requiring every idea to become a Trello card:

```text
Inbox -> Clarify -> Ready -> Active -> Waiting -> Done
           `-----------------------> Incubating / Dismissed
```

Useful capabilities:

- One-line quick capture from web, voice, Telegram, MCP, or a corpus entry.
- "Promote to idea" on any HFL moment.
- Automatic backlinks to the originating entries and files.
- Suggested title, outcome, checklist, project, and next action.
- Idea merging when semantically similar captures recur.
- Evidence counter: "This idea resurfaced five times over eight months."
- Incubation date rather than an artificial due date.
- Project grouping and dependencies.
- Native board view plus agenda or calendar projection.
- Export to Trello only when an idea becomes execution-ready.
- Continue ingesting Trello actions back into HFL, closing the loop.

A promoted Trello card should contain a machine-readable provenance block:

```yaml
harqis:
  object_id: memobj_...
  source_entry_ids:
    - hfl_...
  objective: ...
  approval_policy: review
  completion_evidence: ...
```

When the card changes, the existing Trello ingest can associate the action with
the originating idea instead of treating it as an isolated event.

## Agent-readable and agent-actionable design

Agents should receive narrow tools rather than unrestricted corpus mutation:

- `memory_object_search`
- `memory_object_get`
- `memory_object_capture_idea`
- `memory_object_propose_update`
- `memory_object_propose_action`
- `memory_action_approve`
- `memory_action_execute`
- `memory_action_status`
- `memory_object_link_evidence`

Use three action policies:

| Policy | Example | Behavior |
| --- | --- | --- |
| Automatic | Tag an idea, calculate a reminder, add an internal link | Execute with receipt |
| Approval required | Create a Trello card or Google Task | Prepare preview, await approval |
| Restricted | Send messages, alter meetings, financial action | Explicit allowlist and approval |

Every execution should have:

- A stable idempotency key.
- A short lease so two agents cannot claim the same item.
- Evidence and reason codes.
- Agent or profile attribution.
- Before-and-after state.
- External response ID.
- A compensating action where feasible.
- An HFL action receipt for important outcomes.

This can reuse the Trello agent framework's card-claim, permission, audit, and
human-question patterns rather than building a second orchestration system.

## Strong moat opportunities

### Autobiographical plan-versus-reality

HARQIS knows both the intended calendar and the observed activity. Over time it
can show which plans repeatedly work, drift, or fail.

### Evidence-grounded agent decisions

An agent does not merely say "you should follow up." It can explain:

> This resembles three prior unresolved commitments, links the evidence, and
> proposes a concrete action.

### Longitudinal idea development

Track the complete ancestry of an idea:

```text
Voice thought
-> repeated browsing/research
-> note
-> clarified idea
-> Trello project
-> agent execution
-> completed artifact
-> retrospective
```

That provenance graph is hard for a generic calendar or task manager to
reproduce.

### Commitment closure

Detect open loops across meetings, notes, email, Trello, and agent sessions,
then recognize evidence that they were resolved, even when the resolution
happened in another system.

### Counterfactual calendar

Answer questions such as:

- What work was repeatedly scheduled but never evidenced?
- Which meetings produced no observable outcome?
- What unexpected activities generated the best later results?
- What plans were abandoned but kept resurfacing as ideas?

### Personal operating model

Learn individual duration, energy, context-switching, travel, collaboration,
and follow-through patterns. This becomes a durable personalized scheduling
model rather than generic productivity advice.

### Memory compounding

A normal task loses relevance after completion. In Activity Corpus, its value
increases because later memories, decisions, and outcomes link back to it.

## Suggested implementation order

| Phase | Deliverable | Why first |
| --- | --- | --- |
| 1 | `MemoryObject`, links, statuses, CRUD API, and Inbox or Agenda UI | Establishes the missing mutable intent layer |
| 2 | Promote HFL entry to idea or task; day sheet combining pins, entries, and objects | Immediately connects current Memory Signal to planning |
| 3 | Google Calendar read synchronization and native recurrence or reminders | Adds dependable calendar utility |
| 4 | Trello export with provenance plus action receipts | Connects ideas to the existing agent execution system |
| 5 | Approval-gated agent proposal and execution tools | Enables safe autonomous work |
| 6 | Planned-versus-actual reconciliation | First major product moat |
| 7 | Hybrid semantic retrieval and typed relationship graph | Enables cross-source memory intelligence at scale |
| 8 | Personalized duration, capacity, and resurfacing models | Compounding long-term moat |

## Recommended first vertical slice

1. Capture an idea from an HFL entry.
2. Clarify it in a small board.
3. Schedule or incubate it.
4. Promote it to a provenance-linked Trello card.
5. Let an agent execute the card.
6. Write the action outcome back to HFL.
7. Display the entire chain on the original date and completion date.

That slice would demonstrate the full **memory -> intent -> action -> new
memory** loop without prematurely rebuilding all of Google Calendar or Trello.
