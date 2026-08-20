---
name: choose-automation-runtime
description: >
  Classify a proposed HARQIS automation as Celery, an external agent
  orchestrator, or a hybrid before implementation or scheduling.
allowed-tools: Bash Read Glob Grep
---

# Choose Automation Runtime

Use this skill before creating or materially changing scheduled automation when
the execution boundary is not already explicit. The governing principle is:

> **Agents own adaptive judgment; Celery owns durable execution.**

Read [`docs/info/AUTOMATION-RUNTIME-GUIDE.md`](../../../docs/info/AUTOMATION-RUNTIME-GUIDE.md)
before classifying the work.

## Decision workflow

1. Identify the goal, trigger, inputs, Express output, failure behavior, and
   external side effects.
2. Determine whether the run needs adaptive planning, clarification, tool
   selection, or interpretation of open-ended evidence.
3. Determine whether it needs durable queueing, retries, expiry, host affinity,
   fanout, idempotent persistence, or high-volume execution.
4. Select exactly one classification:
   - **`celery`** — fixed, bounded, schema-driven work whose execution must be
     durable. A bounded LLM transformation does not by itself make it an agent.
   - **`agent`** — open-ended work whose value comes from adaptive judgment and
     which does not need Celery's execution guarantees.
   - **`hybrid`** — an agent decides or plans; Celery performs deterministic,
     retryable collection, persistence, delivery, or fanout.
5. Name one execution owner for each operation and exactly one schedule owner
   for the overall automation. Hermes machine-local cron must not be the sole
   source of truth for a reliability-critical platform schedule.
6. Specify the controls required before implementation: skill name and version
   hash, idempotency key, scoped permissions, approval evidence for risky
   actions, correlation and child-task IDs, and PAER review artifacts.

For a pure `agent` result reached from `/create-new-workflow`, stop the Celery
scaffold and hand off to the relevant agent or skill implementation. For a
`hybrid` result, scaffold only the deterministic Celery operations and document
the agent boundary. Do not silently override an explicit user runtime choice;
record the conflict and its risks.

## Required output

```markdown
## Automation Runtime Decision

**Classification:** celery | agent | hybrid
**Confidence:** high | medium | low
**Reasoning:** <why this boundary fits>
**Execution owner:** <owner for each operation>
**Schedule owner:** Celery Beat | Hermes | Kanban | manual
**Celery operations:** <deterministic operations, or none>
**Agent responsibilities:** <adaptive decisions, or none>
**Required controls:** <idempotency, permissions, approvals, hashes, correlation>
**Review artifact:** <log, report, HFL entry, dashboard, or other evidence>
**Open questions:** <remaining ambiguity, or none>
```

Do not implement until low-confidence or materially consequential open questions
have been resolved through the active clarification workflow.
