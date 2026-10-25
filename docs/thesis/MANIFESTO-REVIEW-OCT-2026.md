# Manifesto Review — October 2026

The direction remains strongly aligned: HARQIS is becoming a usable, contextual second brain with paths from memory to actions, outcomes, and sharing. The main strategic risk is spending more effort on accumulating and arranging knowledge than on demonstrating its usefulness. This is a prioritization risk, not evidence that the recent UI work is wasteful.

Audited at: 2026-10-25T16:10:41.140222+08:00. Branch: main. Commit: `e98eff245c84b6ea8dc0214d619ad44e939ed364`. Scope: October 1–25 feature history, with current implementation traces. Initial tracked working tree clean. The audit was read-only apart from its reports; no implementation, scheduling, deployment, or manifesto changes were made.

This review compares the [current manifesto](../MANIFESTO.md) with recent features, identifies possible drift, and proposes the next useful capabilities. PARA: Resource. Evidence paths are relative to the repository root; line numbers refer to the audited commit.

**Findings: 0 Critical, 0 High, 5 Medium.** Metadata validation passes: 74 entries, zero violations/warnings. That establishes declaration completeness, not production health.

## Recent features and alignment

| Feature | Dated changes | Manifesto alignment | Assessment | Evidence |
|---|---|---|---|---|
| Portable Second Brain HUD | Oct 24–25; e7dc001e, 48b673ef | Capture → Express; Habits 4, 6, 7 | Reuses existing collectors and projections, shared Spaces, canonical feed, and existing agent workspace. Removes desktop dependence for portable sources. | docs/info/SECOND-BRAIN-HUD-MIGRATION.md:24; frontend/modules/second_brain/hud.py:132 |
| Ideas → actions and automatic thought memories | Oct 13–20; 157891b7, 5c734794 | Organize → Express → Capture; PAER | Promotion, deduplication, completion receipts, and transactional memory capture turn thoughts into work and return outcomes to memory. | frontend/modules/hfl_corpus/ideas_api.py:504; workflows/hfl/board_memory.py:15; workflows/hfl/timeline.py:287 |
| Scoped sharing, workspace context, persona facets | Oct 6–12; 474f5a12, 827ef720, 09c922b2 | Distill → Express; Habit 2 | Stored snapshots and bounded guest context are concrete outputs for an audience. Share audit events create review evidence, although access is not proof of usefulness. | frontend/modules/hfl_shares/scope.py:150; frontend/modules/hfl_shares/store.py:407; frontend/modules/hfl_shares/audit.py:27 |
| Entity identity, souls, relationships, reversible consolidation | Oct 12–24; 5087ab55, a2f7cb01, efeff99f, a399eb7f | Organize → Distill; Habits 5 and 7 | Makes recall coherent across aliases; explicitly labels user-authored soul context separately from independent evidence. | workflows/hfl/entity_soul.py:21; workflows/hfl/entity_soul.py:86; frontend/modules/hfl_corpus/entity_soul_api.py:275 |
| Filtered timelines, corpus queries, live card search | Oct 15–25; fba9b2e4, 19b718eb, f046347e | Organize → Distill → Express | Improves the first-class recall path and moves the corpus beyond passive accumulation. | workflows/hfl/timeline.py:240; frontend/modules/hfl_corpus/ideas_api.py:48 |
| Isolated n8n public demo deployment | Oct 25; e7b80a18 | Potential Express / reuse enabler | Isolation and persistent demo storage support reuse. The commit supplies deployment configuration, not a demonstrated demo outcome; name the audience and reusable workflow before expanding it. | workflows/n8n/deploy/demo/compose.yaml:1 |

## Possible drift from goals

1. **Review is less visible than capture and organization.** `/distill` redirects to the corpus (`frontend/modules/home/router.py:14`), while the registry calls the corpus Capture and files Organize (`frontend/modules/registry.py:30`). This does not remove distillation: timeline synthesis, duplicate review, entity context, persona audit, and on-demand summaries remain. A unified review affordance may make the operating ritual easier than restoring a decorative landing page.

2. **UI polish can outrun outcome evidence.** October 24 history contains extensive HUD layout, typography, animation, and control refinements alongside the substantive portable-HUD migration. These may improve adoption; commit counts do not measure effort or value. Habit 3 suggests the next increment should show reduced decision time, completed commitments, or useful recalled evidence before further cosmetic expansion.

3. **Spaces, categories, entities, boards, and souls need a clear relationship to PARA.** Their existence is not a forbidden fifth bucket: they serve different dimensions. The risk is user confusion and organizational maintenance. Explain how existing objects support Projects, Areas, Resources, and Archive; avoid imposing PARA on every low-level record.

4. **The platform can become a self-observation loop.** Thought memories and entity audits improve recall, but generated records can consume attention and feed further analysis. Existing duplicate suppression and entity-audit exclusion are countermeasures (157891b7; fd084b0d). Measure downstream usefulness rather than treating corpus growth as success.

5. **Reuse infrastructure still needs a named output.** The n8n demo is a reasonable Express enabler, but this commit alone does not identify a user outcome. Start with one reusable demo workflow and success condition before broadening the deployment surface.

## Evidence-backed findings

### M01 — Medium: Manifesto assumes an automatic weekly provenance consumer that is deliberately disabled.

**Classification:** Observed documentation drift.
**Evidence:** `docs/MANIFESTO.md:106`; `docs/MANIFESTO.md:116`; `workflows/hfl/tasks_config.py:293`; `workflows/hfl/tasks/summarize.py:170`.
**Principle:** HFL provenance; defined Express path; update stale principles.
**Impact:** Builders may assume reference enrichment happens automatically. On-demand summarization and recall remain available; disabling the schedule is authorized, not a defect.
**Express output:** Accurate provenance guidance naming current consumers and manual review paths.
**Smallest next action:** Replace the unconditional weekly-summarizer claim with consumer-neutral provenance guidance and identify on-demand summary/recall. Preserve disabled schedules.
**Effort:** 1–2 hours; low uncertainty.

### M02 — Medium: Scheduled Git ingestion omits structured source references.

**Classification:** Observed implementation gap.
**Evidence:** `workflows/hfl/tasks/ingest_git.py:139`; `workflows/hfl/tasks/ingest_git.py:279`; `workflows/hfl/tasks_config.py:189`; `docs/MANIFESTO.md:116`.
**Principle:** Artifact retrieval and source References for hfl_signal writers.
**Impact:** Repository and abbreviated commit IDs are collected, but _build_entry receives no references. Summaries cannot reliably serve as a direct retrieval index for the underlying commits; prose may retain some identifiers.
**Express output:** Git memories with bounded, stable commit links or a linked durable source manifest.
**Smallest next action:** Preserve full commit identity/URLs at collection and pass bounded references into _build_entry; verify fallback and synthesized entries retain them.
**Effort:** 0.5–1 day; moderate uncertainty around link limits and DTO fields.

### M03 — Medium: Git task reports a write without propagating the persistence delivery state.

**Classification:** Observed review-evidence gap.
**Evidence:** `workflows/hfl/tasks/capture.py:133`; `workflows/hfl/tasks/ingest_git.py:288`; `workflows/hfl/persistence.py:436`.
**Principle:** PAER Review must describe the result of execution.
**Impact:** append_entry reduces the submission result to a tuple, and Git ingestion ignores it and returns entries_written=1. Forwarded/outbox delivery can therefore look like a completed write. The outbox exists; this is not evidence of lost data.
**Express output:** A receipt distinguishing queued, persisted, indexed, and failed/pending delivery.
**Smallest next action:** Expose the existing structured submission receipt to this caller while preserving compatibility for other append_entry callers; report actual delivery status.
**Effort:** 0.5–1 day; moderate uncertainty around existing callers and task result contracts.

### M04 — Medium: Metadata audit validates declaration shape, not the declared consumer or artifact.

**Classification:** Observed assurance limitation; proposed enhancement.
**Evidence:** `scripts/agents/repo-quality/manifesto_audit.py:88`; `scripts/agents/repo-quality/manifesto_audit.py:110`; `scripts/agents/repo-quality/manifesto_audit.py:124`; `workflows/hfl/tasks_config.py:98`.
**Principle:** Express path within one hop and reviewable execution.
**Impact:** The green 74-entry result does not establish actual production schedules, successful output delivery, reference coverage, or external agent schedule health. The loader includes declarations such as the nominally ad-hoc capture entry.
**Express output:** A sampled, evidence-backed producer-to-consumer assurance report.
**Smallest next action:** Label the current check declaration-only and add a small optional receipt/provenance check for representative active paths, reusing source-health checks.
**Effort:** 1–3 days; moderate uncertainty around runtime access and receipts.

### M05 — Medium: HUD projection publication is best-effort after collector success.

**Classification:** Observed resilience tradeoff; no observed outage.
**Evidence:** `workflows/second_brain/hud_projection.py:123`; `workflows/second_brain/hud_projection.py:253`; `frontend/modules/second_brain/hud.py:132`.
**Principle:** Review whether the Express output landed; proactive failure detection.
**Impact:** Projection exceptions log a warning and return the collector result. Stale-state handling mitigates this, but collector success does not prove dashboard delivery and the wrapper has no durable replay.
**Express output:** A visible delivery-failure signal, with bounded replay where needed.
**Smallest next action:** First distinguish last collection success from last projection success in health evidence; only add retry/outbox if observed failures justify it.
**Effort:** 1–2 days for visibility; replay adds scope and uncertainty.

## Five Capture → Organize → Distill → Express traces

| Flow | Producer | Durable organization | Transformation | Consumer / Express | Review receipt | Evidence |
|---|---|---|---|---|---|---|
| Git activity | GitHub service → bounded author/date-filtered commits | Canonical HFL Markdown + Elasticsearch via append_entry / submit_hfl_entry | Bounded model summary with fallback | Corpus recall / on-demand summary | Task log exists, but delivery state and structured source links are weak (M02/M03). | workflows/hfl/tasks/ingest_git.py:85; workflows/hfl/tasks/ingest_git.py:168; workflows/hfl/persistence.py:283 |
| Idea/checklist memory | Owner edits or checklist changes | board_memories in the owning transaction → file outbox → canonical corpus | Changed-field extraction; stable revision-based deduplication | Recallable thought/goal memory with graph link | staged flag acknowledges outbox handoff, not final indexing; canonical persistence provides later delivery state. | workflows/hfl/board_memory.py:15; workflows/hfl/board_memory.py:81; workflows/hfl/persistence.py:485 |
| Timeline → completed action | Period evidence and related corpus entries | FollowUpStore history, suggestions, and receipts | Evidence validation and duplicate review | Action completion → HFL outcome entry | Versioned completion receipt; daily task retries pending receipts. | workflows/hfl/timeline.py:240; workflows/hfl/timeline.py:287; workflows/hfl/tasks/timeline_suggestions.py:36 |
| HUD signal | Existing scheduled app collectors | Elasticsearch HUD projection; canonical feed for Context feed | Bounded/redacted projection, freshness/ranking | Space-aware dashboard widget | Timestamp and stale/fresh state; projection exceptions best-effort (M05). | workflows/second_brain/hud_projection.py:93; workflows/second_brain/hud_projection.py:211; frontend/modules/second_brain/hud.py:166 |
| Shared context | Owner-selected corpus scope and linked objects | SQLite snapshot + saved configuration / grant | Scope intersection, snapshot projection, evidence-bounded chat | Guest portal and answers | Stored grant/session state and sanitized HFL sharing audit; no claim of guest usefulness measurement. | frontend/modules/hfl_shares/scope.py:150; frontend/modules/hfl_shares/store.py:407; frontend/modules/hfl_shares/agent.py:100; frontend/modules/hfl_shares/audit.py:27 |

PAER across these stages: Capture plans bound sources/windows, analyzes source scope, executes collection, and reviews counts/delivery; Organize uses canonical stores, stable IDs, revisions, and deduplication; Distill uses bounded prompts, evidence validation, and fallbacks; Express uses explicit destinations, stored outcomes, grants, and freshness. These are implementation controls, not proof that every production run retains separate Plan/Analyze artifacts or that outputs were useful. The clearest weak points in sampled stage-level Review are the Git receipt and best-effort HUD projection.

The service/orchestration boundary generally holds in the sample: Git capture reuses the GitHub app service, HFL submission is canonical, HUD reads projections instead of launching collectors on page load, and HUD agent creation uses the existing Kanban workspace. Static schedule ownership is coherent (`machines.toml:73`, `workflows/hfl/tasks_config.py:67`); live single-Beat operation remains unknown.

## Possible new features, in suggested order

1. **A review workspace over existing evidence.** One on-demand review showing what changed, what matters, open commitments, completed outcomes, and one lesson to retain.
   Reuse: Timeline, radar, ideas, completion receipts, source health, and existing Spaces; do not add another autonomous agent or re-enable email schedules.
   Done-state: Every recommendation links to evidence and an existing action or explicit dismiss/defer decision. Save a review receipt.
   Estimate: 3–5 days; moderate uncertainty.

2. **Provenance and delivery inspection.** From a memory or widget, inspect source artifact, transformation, persistence state, last consumer output, and unresolved failures.
   Reuse: References, task IDs, HFL outbox, timeline receipts, HUD captured_at and stale status.
   Done-state: Begin with Git, timeline outcomes, and HUD. Distinguish missing evidence from failure and queued delivery from persistence.
   Estimate: 2–4 days after M02/M03; moderate uncertainty.

3. **Goal-linked Spaces and a simple PARA lens.** A Space view showing its Project/Area/Resource/Archive role, intended outcome, next action, and done-state or review cadence.
   Reuse: Existing goals, boards, target dates, success criteria, and workspace membership.
   Done-state: Map existing concepts without making Space or entity type a fifth PARA bucket; keep intake friction low and default reference material to Resource.
   Estimate: 2–4 days; depends on UX and migration choices.

4. **Outcome-aware signal tuning.** A reviewable suggestion to reduce noisy signals or increase useful ones, based on downstream reuse and owner feedback.
   Reuse: Existing memories, action promotions/completions, shares, and source-health data.
   Done-state: Show why a signal is considered useful or noisy; require an explicit owner choice for schedule changes. Track qualitative value alongside counts.
   Estimate: 3–5 days for a pilot; high uncertainty until usage evidence is available.

5. **Source-grounded expression recipes.** Turn a selected period or Space into a standup, retrospective, debugging lesson, or story draft with source links.
   Reuse: On-demand summarize/retrieve, sharing snapshots, timeline selection, and existing draft surfaces.
   Done-state: One useful template first, preserving references and allowing corrections; do not create a parallel corpus or publish automatically.
   Estimate: 2–3 days for one template; moderate uncertainty.

## Suggested next sequence

First correct manifesto wording and Git provenance/receipts (M01–M03). Then build one on-demand review workspace using existing timeline and completion infrastructure. Add minimal delivery inspection before deciding whether more HUD replay machinery is warranted. Pilot goal-linked Spaces and outcome feedback with one operational area. Do not add another ingestion source or agent solely to fill a CODE label.

Possible manifesto clarification: describe one-hop expression as an identifiable consumer or retrieval surface with provenance; distinguish delivery evidence from usefulness review; explain that Space/category/entity are orthogonal to PARA. Keep product implementation details in feature docs rather than expanding the manifesto into a roadmap.

## Validation and limitations

- repository: main at e98eff245c84b6ea8dc0214d619ad44e939ed364; initial tracked working tree clean
- metadata_audit: PASS: 74 entries; 0 hard violations, 0 soft warnings; exit 0; repository .venv and canonical machine bootstrap
- representative_traces: 5 static traces completed
- schedule_ownership: Static config documents canonical Beat host; Activity Radar Beat trigger disabled for Hermes ownership. Runtime uniqueness unknown.
- runtime_health: Not checked
- report_validation: Markdown and JSON generated from shared data; JSON parse and evidence path/line validation performed by report writer

- Static repository audit, not a production health check; no private corpus, usage analytics, guest conversations, or secret values inspected.
- History window is 2026-10-01 through 2026-10-25 using actual commit dates. Older implementation inspected when necessary to trace current paths.
- 74 is the count loaded by the metadata script, not a claim that all 74 entries currently run in production. External agent schedules and host liveness were not queried.
- Existing regression test files were inspected/discovered but not executed; no code changes justify a broad regression run. Historical deployment verification is documentation, not fresh validation.
- Root AGENTS.md and CLAUDE.md are absent. The manifesto still points to CLAUDE.md; audit followed the available skill and current architecture documents.
- No demonstrated critical or high-severity failure. Opportunity estimates are rough engineering days, not delivery commitments.

Relevant existing tests include `frontend/tests/test_board_memory.py`, `frontend/tests/test_hfl_timeline.py`, `frontend/tests/test_idea_promotion_drop.py`, `frontend/tests/test_unified_soul.py`, `frontend/tests/test_workspace_sharing.py`, `frontend/tests/test_second_brain_hud.py`, and `workflows/hfl/tests/test_timeline_model.py`. Their existence provides a starting point for remediation validation, not a new passing-test claim.
