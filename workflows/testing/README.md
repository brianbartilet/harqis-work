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

**Schedule:** Mondays at 10:00 — `crontab(hour=10, minute=0, day_of_week='mon')`.

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
