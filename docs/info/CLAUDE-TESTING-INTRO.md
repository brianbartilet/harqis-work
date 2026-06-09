# Claude for Testers — An Introduction

A practical introduction to using **Claude** in your testing workflows. This guide is for
QA engineers, SDETs, and test leads who want to go beyond chatting with an AI and actually
wire Claude into how they design, run, and triage tests.

## What is Claude?

**Claude** is Anthropic's family of large language models (the current generation is
Claude 4.x, available in Opus, Sonnet, and Haiku tiers — roughly "most capable",
"balanced", and "fast/cheap"). On its own, a model reads text and writes text. What makes
it useful for testing is the tooling *around* it that lets it take actions: read your repo,
run your suite, call your test-management system, and reason over the results.

For testers, Claude typically shows up in three forms:

- **Claude Code** — an agentic command-line / IDE assistant. It can read your codebase,
  run commands, edit files, and execute **skills** (saved procedures). This is where you'd
  interactively generate test cases, run a suite, or review a change.
- **The Claude API** — Claude called from your own scripts or pipelines for unattended
  automation (e.g. a nightly job that drafts test cases for new tickets). You usually
  pick a model tier per task to balance quality against cost.
- **A scheduled / hosted agent** — Claude running on its own in a loop, on a schedule,
  with access to your tools (see *Orchestration* below).

The shift to internalize: Claude doesn't just *answer questions about* testing — given the
right tools it can *derive* tests from a spec, *run* them, *triage* failures, and *record*
the outcome.

## Key concepts

These four ideas — skills, MCP, agents, and orchestration — are the building blocks. They
compose: skills are the procedures, MCP is the access, agents add judgement, and
orchestration runs it all on a schedule.

### 1. Skills

A **skill** is a packaged, repeatable procedure that Claude runs on command (in Claude
Code, typically a slash-command like `/run-tests`). Instead of re-typing the same
multi-step instructions every time, you capture them once so the behaviour is consistent
no matter who runs it — or whether a human or a scheduled job triggers it.

Skills testers commonly build or use:

| Skill (example) | What it does for testing |
|---|---|
| Generate test scenarios | Turn a spec — a ticket, acceptance criteria, or a card — into BDD/Gherkin `.feature` files with positive, negative, and edge coverage, plus an AC↔scenario mapping table. |
| Run tests | Run a suite for a specific module or the whole project and report results. |
| Review a change | Review a diff for correctness bugs and risky edge cases before it merges. |
| Verify behaviour | Launch the app and observe it actually working — not just unit tests passing. |

The key property is reuse: the *same* "generate test scenarios" skill a tester runs by
hand can be invoked unattended by a nightly job, so manual and automated testing stay in
lockstep.

### 2. MCP (Model Context Protocol)

**MCP** is an open standard from Anthropic that lets Claude call your live systems as
tools. Rather than you hard-coding "call this API, then paste the result into the prompt",
Claude decides *which* tool fits the task, calls it, and reasons over the real result.

```
Claude (AI) ←──── MCP protocol ────→ MCP server ←───→ your tools / services
```

| Regular API integration | MCP tool |
|---|---|
| You decide when to call it | Claude decides when it's relevant |
| Fixed call sequence in code | Claude reasons about which tool fits |
| Result manually wired into the prompt | Claude reads the result and keeps going |

For testers this is what closes the loop. With MCP servers connected to your stack, Claude
can pull tickets from your **issue tracker** (Jira, Trello, Linear, GitHub Issues), read
the acceptance criteria, draft scenarios, and write results back — all as tool calls, with
no glue code per task. Many vendors ship MCP servers already; you can also write your own
to expose an internal test system.

### 3. Agents

An **agent** is Claude running an autonomous *reasoning loop* with access to tools: it
plans, calls a tool, reads the result, decides the next step, and repeats — rather than
executing one fixed command. That makes agents the right choice for tasks that need
judgement across several steps, for example:

- Triaging a batch of test failures and grouping likely-related ones.
- Reading a new spec, checking existing coverage, and proposing only the *missing* tests.
- Investigating a flaky test by inspecting recent runs and the surrounding code.

Rule of thumb: use an **agent** when the task needs judgement and the steps aren't known
in advance; use a plain **script** (or a non-reasoning scheduled job) when the steps are
deterministic and reasoning would only add cost.

### 4. Orchestration

**Orchestration** is the layer that *hosts and schedules* agents so testing automation runs
on its own — nightly, per-commit, or on a sprint cadence — instead of only when a person
is at the keyboard. An orchestrator typically:

- **Hosts the agent** and connects it to your MCP tools.
- **Schedules recurring work** in two flavours: an **agent loop** for tasks that need
  judgement, and a **plain scheduled job** that just runs a script and delivers the output
  for deterministic tasks.
- **Persists memory and logs** so the agent improves over time and runs are auditable.

You don't have to build this from scratch — frameworks and runtimes exist for it, and some
teams build a thin in-house orchestrator (for example, *Hermes* in this repository fills
that role). The concept matters more than the tool: orchestration is what turns one-off
interactive help into unattended, repeatable QA automation.

## Putting it together — a worked example

A common end-to-end testing pipeline combines all four concepts:

```
Issue tracker (active-sprint Bug/Story tickets)     ← MCP (issue-tracker tool)
   → for each ticket, one at a time:
        run the "generate test scenarios" skill      ← Skill (the same one you run by hand)
        → append to a living BDD test-case document
   → on a daily schedule                             ← Orchestration (scheduled agent / job)
```

The result is a continuously updated set of Gherkin scenarios for the current sprint:
generated by the same skill a tester uses interactively, fed by live data through MCP, and
kept current by the orchestrator — no one has to remember to run it.

---

**The model to keep in mind:** *skills* are the repeatable procedures, *MCP* gives Claude
live access to your test systems, *agents* add autonomous judgement, and *orchestration*
runs it all on a schedule — together turning one-off AI help into dependable, repeatable
testing automation.

## Where to go next

- **Claude Code** — Anthropic's agentic CLI/IDE assistant and how to define skills:
  <https://docs.claude.com/en/docs/claude-code>
- **Model Context Protocol** — the open standard, plus available and custom servers:
  <https://modelcontextprotocol.io>
- **Claude API & models** — model tiers, pricing, and tool use for building your own
  automation: <https://docs.claude.com>
