# `testing` workflow

QA / test-automation workflows.

### `run_test_farm`  (`tasks/test_farm.py`)

**Goal:** Maintain a living "BDD test case farm" — a single markdown file of
Gherkin scenarios for the active-sprint Bug/Story tickets, so they can be copied
straight into a feature file or test plan.

**Apps chained:**
1. `apps/jira` (`ApiServiceJiraBoards.get_board_issues`) → pulls active-sprint
   Bug/Story tickets from the same board `workflows/hud/tasks/hud_jira` reads.
2. **Anthropic API** (`apps/antropic`, `BaseApiServiceAnthropic.send_message`) →
   sends a self-contained Gherkin-generation prompt (Sonnet, bounded
   `max_tokens`) per ticket. The `/generate-gherkin-scenarios` conventions are
   inlined into the system prompt, so the call needs no skill/tool runtime.
   Auth is `ANTHROPIC_API_KEY`: this task is unattended, so it bills the
   commercial API rather than the interactive-only Claude Max subscription.

**Data flow:**
```
Jira board (sprint, statuses, Bug/Story)
   → for each ticket, one at a time:
        get ticket data → Anthropic API (send_message) → append
        → rate-limit pause → repeat
   → logs/BDD-TEST-FARM.md   (summary nav table + one section per ticket)
```

**Runtime decision:** Hybrid migration. Hermes is the designated schedule and
agent-reasoning owner; the canonical Celery task remains the durable execution
boundary for Jira collection, bounded generation, incremental persistence, and
logging. The agent-reasoning split itself is not implemented by this change.

**Schedule:** The former Monday 10:00 Celery Beat entry is disabled and retained
as a line-commented migration reference in `tasks_config.py`. Until the Hermes
job is configured, generation is manual/on-demand. Hermes must be the only
recurring initiator and dispatch
`workflows.testing.tasks.test_farm.run_test_farm` to `WorkflowQueue.PEON`; do not
re-enable the Beat entry at the same time.

**Queue:** `WorkflowQueue.PEON`, pinned to `os: ['windows']` (the
`windows-work-all` host, alongside the email/report half). `expires`: 8h.

**Statuses / types:** `In Review`, `In Progress`, `Ready`, `In Analysis`;
issue types `Bug`, `Story` (mirrors `hud_jira`).

**Output document** — `logs/BDD-TEST-FARM.md`:
- A top **summary nav table** (active tickets only): Summary · FixVersion ·
  Issue Type · Status · link to the ticket's test section. Sorted by **issue
  type** (Story → Bug), then **status** (Quality Review → In Progress → New →
  other).
- One **section per ticket** (same order as the summary): Ticket Id, Name,
  Priority, Assignee, Issue Type, Status, Fix Version(s), Last generated —
  followed by the generated Gherkin (+ AC↔scenario mapping and coverage tally).
- **Retention:** when a ticket leaves the active focus columns (closed / moved /
  out of sprint), its scenarios are kept under a **"Retained"** group at the
  bottom (marked, last-known status) but dropped from the summary table. State
  is never pruned, so retained scenarios persist across runs.

**Change detection (idempotency):** a sidecar `logs/.bdd-test-farm.state.json`
maps each ticket key → a fingerprint (hash of the tracked fields + description).
A ticket is regenerated only when its fingerprint changes; otherwise the cached
scenarios are reused. Pass `force=True` to regenerate everything.

**Rate limiting:** tickets are processed strictly one at a time; the document is
rewritten after each ticket (crash-safe / resumable), and `inter_ticket_delay`
seconds (default 5) pause between consecutive API generations.

**Required config keys:** `JIRA`, `ANTHROPIC`
**Required env vars:** `JIRA_DOMAIN`, `JIRA_API_TOKEN`, `JIRA_USER`,
`ANTHROPIC_API_KEY`

**Key kwargs:** `board_id` (required, the rapidView id), `cfg_id__jira`,
`cfg_id__anthropic` (`'ANTHROPIC'` default), `statuses`, `model`
(`'claude-sonnet-4-6'` default), `max_tokens` (4000), `inter_ticket_delay` (5s),
`max_results` (200), `limit`, `force`.

**AI prompt:** `workflows/testing/prompts/test_farm.md` (per-ticket user message;
the durable Gherkin conventions live in `_SYSTEM_PROMPT` in `tasks/test_farm.py`).

**Hermes activation controls:** record the invoked skill/version hash, use a
stable weekly idempotency/correlation key, retain the dispatched Celery task ID,
keep Jira and execution permissions scoped, and preserve `es_log` plus
`logs/BDD-TEST-FARM.md` as the PAER review evidence.

### `send_test_farm_report` (`tasks/test_farm_email.py`)

**Goal:** Deliver the existing `logs/BDD-TEST-FARM.md` without performing a
second model-generation pass.

**Data flow:** The task runs
`scripts/agents/testing/daily_test_farm_email.py --skip-generate
--no-claude-preflight`, renders the current Markdown, emails it through
`GOOGLE_GMAIL_SEND`, and posts a Telegram completion notice.

**Schedule:** Celery Beat remains active Mondays at 10:30 as a separate Express
operation. During migration it delivers the latest available Markdown, so the
Hermes generation job should complete before 10:30 to avoid sending stale output.

**Queue/OS:** `WorkflowQueue.PEON`, pinned to Windows so generation and delivery
share the same file and credentials. The Beat entry expires after eight hours.

**Key kwargs:** `skip_generate` (default `True`), `dry_run`, `timeout` (default
300 seconds), and `extra_args`. A missing script, timeout, or non-zero process
exit raises so `@log_result` records the failure. Use `dry_run=True` to render
without sending.
