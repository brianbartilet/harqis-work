# Automation Runtime Decision Guide

Use this guide to decide whether a HARQIS automation belongs in Celery, an
external agent orchestrator such as Hermes or the Kanban agent, or both.

> **Agents own adaptive judgment; Celery owns durable execution.**

The choice is about execution semantics, not whether an LLM appears somewhere
in the workflow. A bounded prompt with a fixed schema can remain a Celery task;
an agent is a runtime that can interpret context, choose tools, revise a plan,
or ask for clarification.

## The three classifications

| Runtime | Choose it when | Typical responsibilities |
|---|---|---|
| **Celery** | The contract and step graph are known before the run and require durable operational guarantees. | Scheduled capture, schema validation, persistence, retries, expiry, host routing, delivery, fanout, and bounded LLM transforms. |
| **Agent orchestrator** | The useful work depends on adaptive judgment and does not need Celery's queue semantics. | Clarification, investigation, planning, tool selection, exception handling that changes the plan, and conversational work. |
| **Hybrid** | Adaptive judgment and durable execution are both essential. | The agent decides what should happen; Celery performs canonical, idempotent operations and reports correlated results. |

## Decision sequence

1. **Name the Express output.** If the observable result and reviewer are not
   known, clarify the feature before choosing a runtime.
2. **Test for adaptive judgment.** Does the run need to ask questions, interpret
   ambiguous evidence, select tools dynamically, or change its plan? If yes,
   assign that portion to an agent.
3. **Test for durable execution.** Does it require queueing, retries, expiry,
   host affinity, fanout, high throughput, or durable persistence? If yes,
   assign those operations to Celery.
4. **Separate decisions from commands.** When both tests are true, choose
   hybrid. Define a typed command/result boundary instead of embedding the
   whole agent loop inside a Celery task or letting an agent duplicate the data
   plane.
5. **Choose one schedule owner.** A run may cross runtimes, but Celery Beat,
   Hermes, Kanban, or a manual trigger must be the single authority that starts
   it. Downstream dispatches are correlated child work, not additional schedules.

## Judgment signals

| Prefer Celery | Prefer an agent |
|---|---|
| Fixed inputs, outputs, and ordered steps | Ambiguous goal or evidence |
| Schema-driven validation or transformation | Clarification or human dialogue |
| Repeatable side effects with idempotency | Dynamic tool or strategy selection |
| Retries, expiry, rate control, routing, or fanout | A plan that may change during execution |
| Canonical collection, storage, or delivery | Open-ended research, triage, or synthesis |
| Large or frequent workloads | Low-volume, context-rich judgment |

Neither column automatically wins. A workload with signals in both columns is
usually hybrid.

## Required ownership and controls

Every non-trivial automation decision record must define:

- **Execution ownership:** one owner for each decision and operation. Agents
  must call canonical app/MCP/Celery interfaces rather than reproduce service
  integration or persistence logic.
- **Schedule ownership:** exactly one initiator. Reliability-critical schedules
  must have a repository-controlled definition or reconciliation artifact;
  machine-local Hermes cron state cannot be their only source of truth.
- **Idempotency and correlation:** stable run/idempotency keys, one correlation
  ID across runtime boundaries, and recorded Celery child task IDs.
- **Skill provenance:** the invoked skill name and content/version hash when an
  agent's behavior depends on repository instructions.
- **Scoped authority:** least-privilege tools and credentials. Irreversible or
  high-impact actions require deterministic validation and durable approval
  evidence before execution.
- **Failure and fallback behavior:** timeouts, retries, partial-result rules,
  duplicate suppression, and what happens when the agent runtime is offline.
- **PAER evidence:** a Plan/Analyze artifact before consequential execution and
  a reviewable log, report, HFL entry, or dashboard result afterward.

## Manifesto alignment

- **CODE:** define the Capture input and Express output first. Celery commonly
  owns repeatable Capture/Organize/Express operations; agents commonly own
  context-sensitive Distill and decision work. These are tendencies, not rigid
  layer rules.
- **PARA:** store the decision record with the owning project or operational
  area; keep this guide as the reusable Resource.
- **Habit 2:** begin with the observable output and success condition.
- **Habit 5:** inspect existing tasks, skills, and integrations before creating
  a new execution path.
- **Habit 6:** compose skills and canonical app operations instead of duplicating
  them inside an agent.
- **PAER:** make the runtime decision during Plan/Analyze, execute through the
  selected owners, then retain a Review artifact.

## Reference examples

- **Activity Radar — hybrid reference:** Hermes owns scheduling and contextual
  agent reasoning; canonical Celery/HFL operations own durable execution and
  persistence. Its repository-managed reconciliation artifacts keep local cron
  state from becoming an unreviewable source of truth, and no Beat schedule
  duplicates the Hermes trigger.
- **Test Farm — hybrid migration in progress:** the generation Beat entry is
  disabled while Hermes becomes the sole schedule and agent-reasoning owner.
  The canonical Celery task remains the durable Jira collection, bounded
  generation, incremental persistence, and logging boundary. The Hermes job
  and adaptive reasoning split must be configured before the migration is
  complete; the separate report-delivery Beat task remains active.
- **Dumps Summary and bounded summaries — Celery:** a fixed prompt and output
  schema are bounded transformations, not autonomous agents.
- **Fork Fleet scanning, Meta ingestion, Time Capsule collection, agent-session
  ingestion, and inventory commands — Celery data plane:** retain deterministic
  scanning, validation, collection, and persistence in Celery even when a skill
  or agent controls or interprets the run.

## Decision record

Use `/choose-automation-runtime` and retain its output in the feature spec,
workflow documentation, card, or PR. Revisit the classification when the step
graph, side-effect risk, scheduling authority, or durability requirements change.
