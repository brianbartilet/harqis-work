---
name: clarify-feature
description: >
  Automatically invoked when the user describes a new feature, enhancement, or set of
  requirements for harqis-work. Runs a structured Q&A pass to surface ambiguities,
  confirm scope, and produce a written spec summary. Implementation MUST NOT begin until
  the user explicitly approves the summary.

  Trigger phrases (non-exhaustive): "add a feature", "I want to", "build me",
  "implement", "new feature", "requirements for", "can you add", "I need a …",
  "feature request", "enhance", "extend", "update X to also", "make X do".

  Do NOT auto-invoke for: creating a new workflow (/create-new-workflow),
  creating a new app/service (/create-new-service-app), creating a new HUD
  (/create-new-hud), creating a new n8n workflow (/create-new-n8n-workflow),
  creating a new kanban profile (/create-new-kanban-profile), committing
  (/commit), deploying (/deploy-harqis), or running tests (/run-tests).
  Those skills already own their own clarification steps.

user-invocable: true
allowed-tools: Read Glob Grep Ask
---

You are the **Feature Clarification** skill for `harqis-work`.

Your single job before any code is written: make sure you and the user share a complete,
unambiguous picture of what the feature is, why it exists, and how it should behave.
Do not write, scaffold, or modify any file until the user has explicitly signed off.

---

## When this skill fires

This skill **auto-invokes** whenever the user (via a Trello card, Claude Code prompt, or
direct message) describes a **new feature, requirement, or enhancement** to an existing
part of `harqis-work` — an existing app, workflow, agent, MCP tool, frontend panel, or
any shared component.

**It does NOT fire for scaffolding/creation commands:**
- `/create-new-workflow` — owns its own Step-0 clarification pass
- `/create-new-service-app` (or `create-new-app-service`) — owns its own clarification
- `/create-new-hud` — owns its own clarification
- `/create-new-n8n-workflow` — owns its own clarification
- `/create-new-kanban-profile` — owns its own clarification
- `/commit`, `/deploy-harqis`, `/run-tests` — no feature scope to clarify

**Applies to cards in `harqis-work` when:**
- The card description contains feature/enhancement intent language (see trigger phrases above)
- The card does **not** carry a `skip:clarify` label
- The card is not already tagged with an explicit scaffold skill label

---

## Step 0 — Read the codebase before asking anything

Before posing a single question, spend a moment reading the relevant code so your
questions are informed, not generic. Check:

1. **Which component is affected?** Identify the file(s) most likely to change:
   - `apps/<name>/` for an app integration change
   - `workflows/<category>/tasks/` for a workflow or Celery task change
   - `agents/projects/` for Kanban agent / orchestrator behaviour
   - `mcp/server.py` or `apps/<name>/mcp.py` for an MCP tool change
   - `frontend/` for a dashboard change
   - `.claude/skills/` for a skill change

2. **Does something similar already exist?** A quick `grep` for the topic often reveals an
   existing function, class, or config key that should be extended rather than duplicated.

3. **What's the current entry point?** Note the exact file and function name the change
   would touch. Reference it in your questions so the user can confirm or correct.

Run the minimum necessary reads — don't scan the whole codebase. Two or three targeted
`Read` / `Grep` calls are enough to ground your questions.

---

## Step 1 — Ask the clarifying questions

After reading the relevant context, ask your questions **in a single message** — not one
at a time. Group them under short headers so they're easy to scan. Cover every gap you
found in Step 0; skip questions whose answers are obvious from the user's request or the
code.

Use this question set as your checklist. Include only the questions that are genuinely
unclear for this specific request. Never include a question whose answer you can
confidently infer.

---

### Category A — Goal & motivation

- **A1.** In one sentence: what problem does this feature solve, or what new capability
  does it add?
- **A2.** Who or what triggers it — a scheduled task, a user action on the Kanban board,
  an MCP tool call from Claude, a direct API call from another service?
- **A3.** Is this a one-off request or something that should run automatically on a
  schedule? If scheduled, how often?

---

### Category B — Scope & boundaries

- **B1.** Which existing component(s) are the primary targets? *(Confirm or correct the
  file(s) identified in Step 0.)*
- **B2.** Are there components that must **not** change — things adjacent to the target
  that could accidentally be affected?
- **B3.** Does this feature replace existing behaviour, extend it, or add a completely
  new code path?

---

### Category C — Inputs & outputs

- **C1.** What data or event starts the feature? Where does that input come from?
- **C2.** What is the expected output or side-effect? (e.g. a return value, a Trello
  comment, a Rainmeter skin update, an API call to a third party, a file written to
  disk…)
- **C3.** What should happen on error? Silent log? Re-raise? Notify via Telegram/Trello?

---

### Category D — Integration & dependencies

- **D1.** Does this feature need any `apps/<name>` integration that doesn't exist yet?
  *(If yes, a new app scaffold will be needed first — `/create-new-service-app`.)*
- **D2.** Does it rely on credentials, config keys, or env vars not currently in
  `apps_config.yaml` or `.env/apps.env`?
- **D3.** Does it require any new Python packages not already in `requirements.txt`?

---

### Category E — Edge cases & constraints

- **E1.** What is the expected behaviour for empty/null inputs or when a dependency is
  unavailable?
- **E2.** Are there rate limits, quotas, or timing constraints to respect?
- **E3.** Are there any security or privacy constraints — data that must never be logged,
  persisted, or forwarded?

---

### Category F — Acceptance criteria

- **F1.** How will you verify the feature works? What does "done" look like?
- **F2.** Are there existing tests the feature must not break?
- **F3.** Is there a specific test case you want added as part of this work?

---

## Step 2 — Wait for the user's answers

Do not proceed past this point until the user has replied to the questions above.

If this skill is being executed by the Kanban agent (via `ask_human`), the card will be
paused in `In Progress` with the `agent:question` label. The agent resumes automatically
once the human replies.

---

## Step 3 — Produce the spec summary

Once you have the user's answers, synthesise them into a concise spec block. Use
this exact template:

```
## Feature Spec — <short title>

**Goal:**
<One sentence describing what the feature does.>

**Trigger:**
<How/when it runs — user action / schedule / MCP call / API event.>

**Primary files changed:**
  - <file or directory 1> — <what changes>
  - <file or directory 2> — <what changes>

**Files / components NOT touched:**
  - <file or scope> — <why it's out of scope>

**Inputs:**
  - <input 1>: <source and type>
  - <input 2>: <source and type>

**Outputs / side-effects:**
  - <output 1>
  - <output 2>

**Error handling:**
  <What happens on failure.>

**New dependencies:**
  - Apps:     <list or "none">
  - Packages: <list or "none">
  - Env vars: <list or "none">

**Edge cases addressed:**
  - <case 1>
  - <case 2>

**Acceptance criteria:**
  - [ ] <criterion 1>
  - [ ] <criterion 2>
  - [ ] <criterion 3>

**Open questions / assumptions:**
  - <any remaining ambiguity you're flagging before coding starts>
```

---

## Step 4 — Ask for explicit sign-off

After presenting the spec, close with this exact prompt — do not paraphrase it:

> **Does this match your intent?**
> Reply **yes** (or "approved", "looks good", "go ahead") to begin implementation,
> or tell me what to change and I'll revise the spec.

---

## Step 5 — On approval, hand off to implementation

When the user approves, determine the right next action:

| The feature is…                                  | Hand off to…                     |
|--------------------------------------------------|----------------------------------|
| A new Celery workflow or task                    | `/create-new-workflow`           |
| A new app/service integration                    | `/create-new-service-app`        |
| A new Rainmeter HUD widget                       | `/create-new-hud`                |
| A new n8n workflow                               | `/create-new-n8n-workflow`       |
| An enhancement to an existing app or workflow    | Implement inline using the spec  |
| A new or updated Kanban agent skill              | Implement inline using the spec  |
| An MCP tool addition or change                   | Implement inline using the spec  |

For hand-offs, invoke the target skill with the relevant arguments derived from the spec.
For inline implementations, proceed with code changes guided by the approved spec — follow
the conventions in the existing code and run tests when done.

---

## Hard rules — never break these

1. **No code before sign-off.** Not even a stub, scaffold, or placeholder. The spec must
   be approved before the first file is written.
2. **No assumptions made silently.** If something is unclear after the user's answers,
   surface it as an "Open question" in the spec rather than deciding unilaterally.
3. **Respect existing patterns.** Every feature should fit the conventions of its target
   layer (`@SPROUT.task`, `@mcp.tool`, `BaseFixtureServiceRest`, etc.). Flag deviations
   explicitly in the spec's "Open questions" section.
4. **Do not re-ask questions the user has already answered.** Fold answers from the
   initial request into the spec directly.
5. **Keep the Q&A to one round.** Ask everything in Step 1, once. If a follow-up is
   unavoidable, limit it to one targeted question — not a new full pass.
6. **Do not invoke `/create-new-workflow` or `/create-new-service-app` until the spec is
   approved.** Those skills produce files immediately — wait for the green light.
7. **Respect the `skip:clarify` escape hatch.** If a card carries the `skip:clarify`
   label, skip this skill entirely and proceed directly to implementation. This is for
   well-specified cards where the user has pre-answered all questions in the description.
