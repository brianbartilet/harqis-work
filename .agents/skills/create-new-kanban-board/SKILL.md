---
name: create-new-kanban-board
description: >
  Create a new Trello board scaffolded for the harqis-work Kanban orchestrator with
  canonical lists, labels, a template card, and env-file board registration.
user-invocable: true
allowed-tools: Bash Read Glob Grep Edit Write
---

Create a new Trello board scaffolded for the harqis-work Kanban orchestrator: 9 canonical lists in order, the standard label set for routing, a README template card in `Templates` with every label attached, and an env-file update that adds the new board id to `TRELLO_BOARD_IDS` (preserving its commented/uncommented state).

The argument `$ARGUMENTS` is the board name. If empty, infer from the open editor / current conversation topic; if no clear inference is possible, **ask the user** before proceeding. Never auto-fill a placeholder.

## Required env (read from `.env/apps.env`)

| Variable | Purpose |
|---|---|
| `TRELLO_API_KEY` | Bearer key for Trello REST API |
| `TRELLO_API_TOKEN` | OAuth token paired with the key |
| `TRELLO_WORKSPACE_ID` | Workspace (organization) the new board lives under |

If any are missing or empty, **stop** and tell the user which one. Don't print the values.

## Source of truth — canonical schema

### Lists (in this exact order; orchestrator behaviour from `agents/projects/README.md`)

| # | List | Orchestrator behaviour |
|---|---|---|
| 1 | `Templates` | Card templates the team copies from. Orchestrator never reads or writes here. |
| 2 | `Draft` | Cards being refined / spec'd. Orchestrator ignores. |
| 3 | `Ready` | Intake list. Orchestrator polls this every `KANBAN_POLL_INTERVAL` seconds. |
| 4 | `Pending` | Orchestrator claimed the card and is about to start. |
| 5 | `In Progress` | Agent is actively working. |
| 6 | `In Review` | Agent finished; awaiting human (or reviewer-agent) approval. |
| 7 | `Blocked` | Hard-stop dependency unmet. Re-queued to `Ready` when resolved. |
| 8 | `Done` | Reviewed + accepted. |
| 9 | `Failed` | Unrecoverable error (rate limit / 4xx-5xx / unhandled). Comment header surfaces the kind. |

> Note on order: `agents/projects/README.md` documents `Blocked` between `In Progress` and `In Review`. The user-requested order for **this skill** places `In Review` before `Blocked` (positions 6 and 7). Use the user-requested order. Trello renders lists left-to-right in creation order.

### Labels

| Label | Color | Purpose |
|---|---|---|
| `human` | red | Off-limits to agents. Card needs a human. |
| `manual` | red | Same as `human`. |
| `input` | red | Same — card needs human input. |
| `agent:default` | blue | Fallback profile when no other `agent:*` matches. |
| `agent:code` | blue | Routes to the code agent (bash, git, write_file, MCP). |
| `agent:write` | blue | Routes to the writing agent (write_file only). |
| `agent:write:article` | blue | Routes to the article-specialised write agent. |
| `os:any` | green | Any orchestrator host can claim. |
| `os:linux` | green | Linux hosts only. |
| `os:macos` | green | macOS hosts only (also matched by `os:darwin` / `os:mac`). |
| `os:windows` | green | Windows hosts only (also matched by `os:win`). |

**Don't pre-create** — the orchestrator manages these dynamically: `claimed-by:*`, `agent:question`, `agent:remember`.

## Steps

### Step 1 — Resolve env + board name

Parse `.env/apps.env` for `TRELLO_API_KEY`, `TRELLO_API_TOKEN`, `TRELLO_WORKSPACE_ID`. If any unset, surface and stop. Resolve the board name from `$ARGUMENTS`, then context, then ask. Sanitize: keep alphanumerics, spaces, dashes, underscores; reject anything else (Trello's display is forgiving but the env-file update relies on simple characters).

### Step 2 — Pre-flight

- Confirm the workspace is reachable: `GET /1/organizations/{workspace}?key=...&token=...` should return 200.
- Confirm no board with this exact name already exists in the workspace (`GET /1/organizations/{workspace}/boards?fields=name`). If a duplicate exists, stop and tell the user — running again would create a confusing second board with the same name.

### Step 3 — Create the board

Use `apps.trello.references.web.api.boards.create_board(name, id_organization=TRELLO_WORKSPACE_ID, desc="...")`. Set `desc` to a one-liner: `"harqis-work Kanban orchestrator board — see README card in Templates"`. Capture the returned board id.

**Trello creates two default lists** (`To Do`, `Doing`, `Done` typically) on every new board. Either:

- **Option A** — pass `prefs_permissionLevel=org&defaultLists=false` at create time so no defaults get created, OR
- **Option B** — list the board's lists after creation and `archive` (close) the defaults via `PUT /1/lists/{id}/closed`.

Use Option A if `apps.trello.create_board` supports the parameter; otherwise Option B.

### Step 4 — Create the 9 canonical lists in order

For each list name in the canonical order (Step 0), call `POST /1/lists` with `pos=bottom` so they append left-to-right in the order created. Trello uses ascending `pos` floats internally — creating in order with `pos=bottom` is the simplest way to lock the order. Capture each list's id; you'll need `Templates` for the README card.

After all 9 are created, sanity-check by listing the board's lists and verifying the names + order match the canonical schema. If any drift, surface it and stop — don't try to auto-correct.

### Step 5 — Create the canonical labels

For each label in the table above, call `POST /1/labels` with `idBoard=<new-board-id>`, `name=<label-name>`, `color=<color>`. Capture each label's id — you'll attach all of them to the README card in Step 6.

If `apps.trello` doesn't expose label creation, use direct REST. Same auth (key/token).

### Step 6 — Create the README card in `Templates`

Card name: `README — How this board works`

Card description (Trello-friendly Markdown — headers/lists/bold/italic/inline-code render natively, but **tables don't**, so every table is wrapped in a triple-backtick code block for monospace alignment):

```markdown
# 📌 README — How this board works

> **TL;DR** — Drop a card in **Ready** with an `agent:*` label. The orchestrator picks it up, runs an agent, posts a comment, and moves the card to **In Review** (or **Done** if the agent's profile has `auto_approve`). Use `human` / `manual` / `input` to lock a card to humans.

This board is driven by the **harqis-work Kanban orchestrator**.
Full reference: [`agents/projects/README.md`](https://github.com/brianbartilet/harqis-work/blob/main/agents/projects/README.md).

> ⚠️ **Trello tip:** Markdown tables don't render here, so every table below is wrapped in a triple-backtick code block. Agents on this board follow the same rule when posting comments.

---

## 🚦 Lifecycle — what each list means

```
| List           | Moved by                  | Notes                                          |
|----------------|---------------------------|------------------------------------------------|
| Templates      | Humans                    | Card templates. Orchestrator never touches.    |
| Draft          | Humans                    | Refining specs. Orchestrator ignores.          |
| Ready          | Humans -> orchestrator    | Intake. Drop here when ready to be picked up.  |
| Pending        | Orchestrator              | Card claimed, about to start.                  |
| In Progress    | Orchestrator              | Agent is working. May pause for input.         |
| In Review      | Orchestrator -> reviewer  | Agent finished; awaiting approval.             |
| Blocked        | Orchestrator              | Required secret/dep missing. Re-queues later.  |
| Done           | Reviewer                  | Accepted. Terminal.                            |
| Failed         | Orchestrator              | Unrecoverable error. See first comment.        |
```

`In Review` is **skipped** when the agent's profile has `lifecycle.auto_approve: true` — the card goes `In Progress -> Done` directly.

For `Failed` cards, the first comment header names the failure kind: `api_usage_limit`, `api_rate_limit`, `api_error`, or `unknown`.

---

## 🏷️ Labels — what they do

> **Three groups by colour:** 🔴 red = off-limits to agents · 🔵 blue = profile routing · 🟢 green = OS routing.

### 🔴 Off-limits to agents

These three labels trump every other label — `human, agent:code` is **still skipped**, no claim, no comment, no move.

```
| Label    | Effect                                                   |
|----------|----------------------------------------------------------|
| human    | Skipped by every orchestrator. Stays put until a human   |
|          | moves it.                                                |
| manual   | Same as human.                                           |
| input    | Same — signals the card needs human input.               |
```

### 🔵 Profile routing — which agent handles the card

```
| Label                  | Resolves to                                    |
|------------------------|------------------------------------------------|
| agent:default          | Fallback profile (no agent:* label set).       |
| agent:code             | Code agent — bash, git, write_file, MCP apps.  |
| agent:write            | Writing agent — write_file only, no bash.      |
| agent:write:article    | Article writer (most-specific prefix wins).    |
```

> ⚠️ A card with a typo (e.g. `agent:typo` with no matching profile) is **skipped**, not silently routed. Typos surface as ignored cards.

### 🟢 OS routing — which orchestrator host can claim

Multiple `os:*` labels are OR'd. The host's labels are auto-detected from `platform.system()`; override with `--os` flag or `KANBAN_OS_LABELS`.

```
| Label                                  | Eligible hosts             |
|----------------------------------------|----------------------------|
| (no os:* label)                        | Any                        |
| os:any                                 | Any (always satisfied)     |
| os:linux                               | Linux only                 |
| os:macos    (also os:darwin, os:mac)   | macOS only                 |
| os:windows  (also os:win)              | Windows only               |
```

### 🤖 Managed by the orchestrator — **do not add manually**

```
| Label                       | When it's added                              |
|-----------------------------|----------------------------------------------|
| claimed-by:<profile_name>   | On claim — audit trail of who picked it up.  |
| agent:question              | When the agent calls ask_human() and pauses. |
| agent:remember              | Pair with agent:question for stateful resume |
|                             | (full prior message history reloaded).       |
```

Both `agent:question` and `agent:remember` are auto-removed when a human replies in the comments.

---

## 📝 Card template — what agents see

```
| Source                                | How it reaches the agent             |
|---------------------------------------|--------------------------------------|
| Title                                 | Fallback prompt if description empty.|
| Description                           | Main task prompt under "# Task".     |
| Checklists                            | Listed under "# Sub-tasks"; agent    |
|                                       | ticks via the check_item tool.       |
| Custom field: required_secrets        | Hard dep check. Card -> Blocked if   |
|                                       | any listed secret is missing.        |
| Custom field: system_prompt_addon     | One-off prepended to system prompt   |
|                                       | for this card only.                  |
| Text attachments                      | Fetched + inlined under              |
|                                       | "# Attached Files".                  |
| URL attachments                       | Appended verbatim at the bottom.     |
```

---

## ⚡ Quick examples

**Single-agent task:**

```
Title:  Summarise this repo
Label:  agent:write
Body:   Read CLAUDE.md and write a 1-paragraph summary as a comment.
```

**OS-pinned code task:**

```
Title:  Build a status dashboard
Labels: agent:code, os:linux
Body:   Add a /status endpoint to frontend/ that returns worker counts.
```

**Locked to humans:**

```
Title:  Approve Q3 budget changes
Label:  human
Body:   Review the attached spreadsheet and post sign-off as a comment.
```

---

## 🛠️ Operations cheat-sheet

```
| Need to...                          | Do                                       |
|-------------------------------------|------------------------------------------|
| Pause an agent for input            | Agent calls ask_human(question);         |
|                                     | orchestrator adds agent:question and     |
|                                     | leaves card in In Progress. Reply in     |
|                                     | comments to resume.                      |
| Resume statefully (full history)    | Pair with agent:remember; agent reloads  |
|                                     | its prior turn history on resume.        |
| Send card back to humans mid-flight | Add the human label and move to Ready.   |
|                                     | Orchestrator skips it on next poll.      |
| Inspect what happened               | Read card comments + the orchestrator    |
|                                     | log at logs/projects_audit.jsonl.        |
| Check which profile claimed a card  | Look for the claimed-by:<profile>        |
|                                     | comment posted on claim.                 |
```

---

> 📚 **Full docs:** [`agents/projects/README.md`](https://github.com/brianbartilet/harqis-work/blob/main/agents/projects/README.md) — covers profile inheritance, Discord integration, Elasticsearch telemetry, MCP tool scoping, Hermes memory wiring, and the production scaling path.
```

Create the card via `apps.trello.references.web.api.cards.create_card(list_id=<templates-id>, name=..., desc=..., id_labels=<every-label-id-from-step-5>)`. Attaching every label gives the user a one-stop visual reference for the colour scheme without having to open Board → Labels.

### Step 7 — Update `.env/apps.env`

Find the `TRELLO_BOARD_IDS` line (active **or** commented). Logic:

1. **No `TRELLO_BOARD_IDS` line at all** — append a new line right after the existing `TRELLO_WORKSPACE_ID` block, **commented**, with just the new id: `# TRELLO_BOARD_IDS=<new-id>`.
2. **Line exists, currently commented** — preserve the leading `#` and the inline comment (everything after the `#` past the `=`). If the value is the placeholder list (`board1,board2,board3`), **replace** the value with just `<new-id>`. Otherwise **append** `,<new-id>` to the existing value.
3. **Line exists, currently active** (uncommented) — append `,<new-id>` to the value. Don't touch the comment state. Note this loudly in the post-summary because the orchestrator will start polling this board immediately on next restart.

In all cases, leave `TRELLO_WORKSPACE_ID` and `KANBAN_BOARD_ID` lines untouched. Don't reorder or reformat surrounding lines.

### Step 8 — Summary

Print:

```
Created board: <name>
  URL:        https://trello.com/b/<short-id>/<slug>
  Workspace:  <workspace-id>
  Board id:   <new-board-id>

Lists (9):
  Templates → Draft → Ready → Pending → In Progress → In Review → Blocked → Done → Failed

Labels (11):
  red    : human, manual, input
  blue   : agent:default, agent:code, agent:write, agent:write:article
  green  : os:any, os:linux, os:macos, os:windows

Template card: README — How this board works  (in Templates, all 11 labels attached)

Env update (.env/apps.env):
  <state before>
  → <state after>
  <commented | active> — <one line on what this means for orchestrator polling>

Next:
  - Open the board URL and verify the layout looks right
  - To activate this board, uncomment the TRELLO_BOARD_IDS line if it's commented
  - Restart the orchestrator: python -m agents.projects.orchestrator.local
```

## Hard rules

- **Never log API keys or tokens.** Print `***` placeholders if you must reference them.
- **Don't commit.** The user calls `/commit` when they're satisfied.
- **Don't re-run on an existing board.** If a board with the same name already exists in the workspace, stop with a clear error pointing the user at the existing board. Idempotent re-run isn't supported — Trello has no native dedupe and partial state is worse than none.
- **Preserve the env line's comment state.** A commented line stays commented; an active line stays active. The user's choice of "this board is active" vs "this board is queued for activation" lives in that single character.
- **Don't auto-fill the board name.** A bad inferred name leaves debris (the new board can't easily be deleted via Trello's UI without confirmation).

## Failure modes

- **Missing `TRELLO_API_KEY` / `TRELLO_API_TOKEN` / `TRELLO_WORKSPACE_ID`** — name which one is missing, suggest the apps.env section to populate.
- **Workspace 404** — workspace id is wrong or the API token doesn't have access to it. Re-check `TRELLO_WORKSPACE_ID` against the workspace short-name in your Trello URL.
- **Duplicate board name** — another board in the workspace already has this name. Either rename or delete the old one before re-running.
- **Default-list cleanup failed** (Option B fallback in Step 3) — the board was created but Trello's defaults are still there. Print their ids so the user can archive them manually via the Trello UI.
- **List order drift** (Step 4) — Trello returned a list order that doesn't match the canonical 9. Surface the actual order and stop. Don't try to fix it programmatically; manual reordering in the UI is fine.
- **Label or card creation 4xx** — partial state. Print which step succeeded and the board id so the user can finish manually or delete the board via Trello UI before re-running.
