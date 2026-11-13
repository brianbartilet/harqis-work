# Agent activity, verified outcomes, and continuity

> HARQIS should know what Brian intended, what its agents attempted, what
> actually happened, and what still needs attention.

Date: 2026-11-12. Status: proposed direction, not an implementation commitment.

## 1. Thesis

The next useful step for HARQIS is to connect Activity Corpus evidence, Kanban
actions, and agent execution into a feedback loop. An agent should begin with
relevant history, produce a reviewable outcome, and leave evidence that makes
the next attempt better informed. Later observations should be able to confirm
or challenge that outcome.

Azaris prompted this exploration because its messaging, persistent memory,
scheduled work, and business-agent positioning overlap with HARQIS. The useful
lesson is continuity and understandable delegation. More channels or more agent
personas alone would not address the main gap.

Voice and phone briefings are secondary. Reading an existing Telegram message
aloud offers limited additional value. Hands-free follow-up and deliberately
configured urgent escalation could justify voice later, using the same durable
conversation and briefing records as text.

## 2. Existing foundations and branch boundaries

This thesis distinguishes available repository foundations from work inspected
on the agent-fleet feature branch. It does not imply that all fleet capabilities
are deployed or present on main.

| Foundation | Role and evidence |
| --- | --- |
| Activity Corpus | Canonical entries, evidence, versioned actions, entities, and connections; see [HFL integration](../../apps/hfl_corpus/README.md). |
| Kanban orchestration | Assignment, execution, review, and blocked-work lifecycles; see [orchestrator documentation](../../agents/projects/README.md). |
| Activity Radar | Evidence-backed commitments, risks, historical comparison, and finding feedback; see [radar skill](../../.agents/skills/activity-radar/SKILL.md). |
| Assistant cockpit direction | Shared conversation and proactive updates, with Telegram as an initial surface; see [cockpit thesis](RUNNING-ASSISTANT-COCKPIT.md). |
| Fleet activity receipts | Observed at feature-branch commit `e79fa208`, in `frontend/modules/agents/audit.py`: deduplicated fleet events delivered through the HFL outbox. |
| Fleet briefings | Observed at the same feature-branch commit, in `frontend/modules/agents/briefings.py`: opt-in daily/weekly read-only briefings through the existing Hermes sweep. |

The feature-branch receipt implementation writes structured event payloads.
The briefing prompt already asks for recent activity, commitments, upcoming work,
failures, evidence, and freshness. Proposed improvements should extend those
foundations when integrated, rather than create competing receipt or scheduling
systems. Runtime availability still requires separate verification.

## 3. Outcome records that explain the work

Every meaningful run should produce a concise outcome record linked to its
action and session:

- The requested outcome and relevant constraints.
- What the agent attempted, changed, or produced.
- What was verified, with evidence and observation times.
- Remaining uncertainty, blockers, and decisions needed from Brian.
- Links to artifacts, earlier attempts, and relevant corpus entries.

Example:

> Investigated missing ingestion. Found an expired credential, prepared a fix,
> and passed the relevant checks. Deployment remains pending. The missing dates
> have not been backfilled.

Keep detailed execution events available for inspection, but present one
versioned summary per run. Repeated delivery should not create duplicate corpus
entries. Updating a summary must preserve prior claims and the evidence that
changed them. Avoid copying raw transcripts and sensitive tool output into
every summary.

## 4. Separate execution status from outcome verification

A session ending successfully does not establish that the requested result
exists. Keep the execution lifecycle and the outcome assessment distinct.

| Agent claim | Evidence needed to establish the outcome |
| --- | --- |
| Fix implemented | Relevant checks passed against the intended change. |
| Deployment completed | The intended target is running the change and passes its health check. |
| Ingestion repaired | Expected records arrived for the relevant period. |
| Report generated | The artifact exists and is accessible to its intended reader. |
| Follow-up prepared | A draft exists; sending is a separate outcome only when requested. |

Proposed outcome assessments are **verified**, **partially verified**,
**awaiting review**, and **unknown**. They should include the criterion checked,
supporting evidence, and remaining gaps. Verification must match the requested
scope: a request to prepare a draft does not require sending it.

Later evidence can update the assessment. A successful ingestion run can confirm
a repair; recurrence of the same failure can challenge a completion claim.
Neither inference should silently rewrite the original execution record or
change a card's state without the applicable action policy.

## 5. Continuity across agents and attempts

When an action starts or resumes, assemble a bounded context packet:

1. Original request and current acceptance criteria.
2. Explicit decisions and constraints that still apply.
3. Previous attempts and their verified results.
4. Latest relevant observations, including contradictory evidence.
5. Remaining work and the reason this run is being started.

Each fact should retain a source, timestamp, and scope. Retrieval should prefer
explicit action links, project/Space relevance, and current evidence over broad
similarity alone. A previous agent's summary is a claim with provenance, not an
independent observation.

This should let Brian move a card back from review, switch agents, or resume
after several days without reconstructing the history manually. Avoid passing
entire conversation archives into every prompt. Organizational Space membership
must not be treated as authorization to disclose unrelated information.

## 6. Reconcile commitments with execution

Extend Activity Radar's existing finding model to connect observations with
actions and runs. Useful findings include:

- A repeated commitment has no linked action.
- A completed card has newer evidence of an unresolved problem.
- Two agents appear to be working toward the same outcome.
- A blocked action has new evidence that its dependency is resolved.
- An agent promised a follow-up, but no subsequent run is recorded.

Findings should explain the evidence, uncertainty, and a specific proposed next
step: attach evidence, link an existing action, resume work, revise the outcome,
or dismiss the finding. Missing evidence is not proof that something never
happened; source freshness and ingestion gaps must remain visible.

Reuse stable finding identities and feedback so repeated observations update
the same finding. Reconcile before proposing a new card. Detection alone should
not launch an agent, send a message, or reopen work; execution remains governed
by existing authority and scheduling controls.

## 7. Reviewable memory derived from corrections

Repeated corrections can become proposed memories:

> You have asked three times for unresolved decisions to appear first in a
> briefing. Save that as your briefing preference?

A memory should record its source evidence, applicable scope, last confirmation,
and any earlier memory it supersedes. Distinguish explicit user instructions,
agent inferences, and external observations. Project-specific conventions must
not silently become global preferences.

Brian should be able to accept, edit, reject, or retire a proposed memory.
Contradictions should surface for resolution rather than being blended into an
ambiguous instruction. A rejected inference should not repeatedly reappear
without materially new evidence.

## 8. Briefings centered on changes and decisions

Improve the briefing question to:

> What changed since my last briefing, what needs me, and what can continue
> without me?

Example:

> Three actions completed with verification. One needs review. The ingestion
> repair failed again. Two previously blocked tasks may now be ready to resume.

Every item should link to its action and evidence. Group related events, suppress
unchanged findings, and show stale-source limitations. Distinguish briefing
generation, delivery, and acknowledgement so an undelivered summary does not
cause an important change to disappear from subsequent briefings.

Telegram and the frontend should show the same underlying briefing. Follow-up
questions should resolve the referenced item instead of starting a disconnected
investigation. An acknowledgement is not approval to execute a proposed action.

## 9. Voice as an optional interaction mode

The cockpit thesis already describes voice and text interaction. This proposal
prioritizes usefulness before additional delivery channels:

1. Reuse available voice-message transcription for hands-free input.
2. Offer short audio versions of the same evidence-backed text briefings.
3. Support follow-up questions such as "why is that blocked?" against the same
   action and briefing context.
4. Consider phone calls only for requested interactive briefings or explicitly
   configured urgent escalation.

Do not create a separate memory store for phone or audio conversations. Preserve
references and confirmation behavior across channels. Speech recognition must
not silently broaden an instruction, and unanswered calls must not count as
acknowledgement. Provider selection, cost, and telephony implementation are
outside this thesis.

## 10. Suggested delivery sequence and success criteria

| Increment | Scope | Evidence of usefulness |
| --- | --- | --- |
| 1. Outcome records | Readable receipts, artifact links, explicit verification assessment. | Brian can distinguish completed execution from achieved outcomes without reading a transcript. |
| 2. Action continuity | Relevant history packet for resumed or reassigned actions. | A different agent can continue from the latest verified state without repeating resolved investigation. |
| 3. Radar reconciliation | Link commitments, duplicate efforts, and changed blockers to existing actions. | Findings lead to useful updates rather than duplicate cards or repeated alerts. |
| 4. Memory and briefings | Reviewable preferences and summaries of changes since prior delivery. | Corrections persist appropriately and briefings concentrate on decisions and material changes. |
| 5. Optional voice | Audio input/output over the same records. | Hands-free interaction completes a real task more conveniently than text. |

Before rollout, measure a small baseline: time spent reconstructing context,
duplicate investigations, completion claims later contradicted, useful versus
dismissed radar findings, and briefing items requiring a decision. Compare these
after each increment. More events, longer summaries, or more agent runs are not
success measures by themselves.

Implementation should preserve existing runtime owners: canonical services own
durable action state; agents interpret context and perform authorized work;
existing dispatchers own their schedules. This document introduces no new worker,
schedule, automatic execution permission, or replacement Kanban system.

## 11. Inspiration and related reading

Azaris was researched from public sources on 2026-11-12, without a hands-on
product test. Its advertised capabilities are inspiration, not verified
performance benchmarks or requirements for HARQIS. Public pages differed on
model billing and approval defaults, so those details should not be copied as
settled design assumptions.

- [Azaris product overview](https://azaris.ai/docs/what-is-azaris): memory,
  routines, channels, and delegated work.
- [Azaris runtime explanation](https://azaris.ai/docs/vs-hermes): hosted Hermes
  positioning.
- [Azaris FAQ](https://azaris.ai/docs/faq) and
  [terms](https://azaris.ai/terms): differing descriptions of usage and controls.
- [Connected HFL knowledge](CONNECTED-HFL-KNOWLEDGE.md): evidence connections.
- [Memory signals, calendar, and agent actions](HFL-MEMORY-SIGNAL-CALENDAR-AND-AGENT-ACTION.md): relationships between memory and work.
- [Running assistant cockpit](RUNNING-ASSISTANT-COCKPIT.md): shared conversation
  and proactive updates across surfaces.

The central product test is whether Brian can reliably answer: what did I ask
for, what happened, why do we believe it, and what should happen next?
