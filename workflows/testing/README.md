# `testing` workflow

QA / test-automation workflows.

### `run_test_farm`  (`tasks/test_farm.py`)

**Goal:** Maintain a living "BDD test case farm" — a single markdown file of
Gherkin scenarios for the active-sprint Bug/Story tickets, so they can be copied
straight into a feature file or test plan.

**Apps chained:**
1. `apps/jira` (`ApiServiceJiraBoards.get_board_issues`) → pulls active-sprint
   Bug/Story tickets from the same board `workflows/hud/tasks/hud_jira` reads.
2. **Local Claude Code CLI** (`claude -p`, headless) → runs the real
   `/generate-gherkin-scenarios` skill against each ticket, using the **Max
   subscription** (no API token cost) and a **thinking model**.

**Data flow:**
```
Jira board (sprint, statuses, Bug/Story)
   → for each ticket, one at a time:
        get ticket data → run /generate-gherkin-scenarios (claude -p) → append
        → rate-limit pause → repeat
   → logs/BDD-TEST-FARM.md   (summary nav table + one section per ticket)
```

**Schedule:** weekdays at 09:00 — `crontab(hour=9, minute=0, day_of_week='mon-fri')`.

**Queue:** `WorkflowQueue.PEON`, pinned to `os: ['windows']` (the
`windows-work-all` host, where `claude` is installed + logged in). `expires`: 8h.

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
seconds (default 5) pause between consecutive Claude generations.

**Required config keys:** `JIRA`
**Required env vars:** `JIRA_DOMAIN`, `JIRA_API_TOKEN`, `JIRA_USER`
**Prerequisite:** `claude` CLI installed and logged in (Max subscription) on the
worker host.

**Key kwargs:** `board_id` (required, the rapidView id), `cfg_id__jira`,
`statuses`, `claude_model` (`'sonnet'` default), `claude_bin`,
`max_thinking_tokens`, `per_ticket_timeout` (420s), `inter_ticket_delay` (5s),
`max_results` (200), `force`.

**AI prompt:** `workflows/testing/prompts/test_farm.md` (headless wrapper that
invokes the `/generate-gherkin-scenarios` skill unattended).
