# HARQIS-Work Manifesto

> The guiding principles for everything built inside this repo.
> Read this before scoping a feature, opening a PR, or letting an LLM agent change code.
> If a decision contradicts this document, the document wins — or the document gets updated.

---

## Mission

Eliminate repetitive manual work by turning every recurring decision, observation, and action into a captured, queryable, automatable artifact. The repo is the substrate; humans and LLMs are the operators.

## Vision

A self-hosted **second brain on steroids** — every app integration, scheduled workflow, HUD signal, and AI agent feeds a single growing corpus of personal and operational knowledge. Over time, anything the operator has done, decided, observed, or built becomes recallable by prompt, reusable by workflow, and reviewable by ritual.

## Why this exists

This project is not "yet another automation framework." It is a deliberate accumulator. Every integration under `apps/`, every Celery routine under `workflows/`, every agent under `agents/`, and every HUD widget under `workflows/hud/` exists for one of two reasons:

1. **Capture** — pull useful state out of an external system into a place we control.
2. **Express** — push reasoned action back into the world, on a schedule or in response to a signal.

Anything that does neither is a candidate for deletion.

---

## Core operating principles

Four frameworks shape every choice in this repo. They are listed in the order they apply to a typical piece of work.

### 1. Build a second brain — Tiago Forte (CODE + PARA)

The repo is the operator's externalized memory. Two mental models govern how knowledge moves through it.

**CODE — the lifecycle of any captured signal:**

| Step         | What it means              | Where it lives in this repo                                                                  |
| ------------ | -------------------------- | --------------------------------------------------------------------------------------------- |
| **Capture**  | Save useful information    | `apps/*` integrations pulling state; HUD feeds; Hermes memory; scheduled syncs                |
| **Organize** | Sort for action            | `workflows/*` chaining captures into pipelines; Trello/Jira boards routed through the Kanban agent |
| **Distill**  | Make notes easier to reuse | Tagged feed entries; summarization tasks; structured DTOs over raw API blobs                  |
| **Express**  | Create output              | Posts, decisions, reports, code changes, HUD updates, Telegram/Discord/WhatsApp replies       |

**PARA — how anything in the system is filed:**

| Category      | Use it for                                          | Examples here                                                  |
| ------------- | --------------------------------------------------- | --------------------------------------------------------------- |
| **Projects**  | Active goals with deadlines                         | An active app integration, a workflow in progress, a refactor   |
| **Areas**     | Ongoing responsibilities                            | Finance HUDs, oncall agents, repo hygiene, deploy infra         |
| **Resources** | Topics of reference                                 | `docs/info/*`, `docs/thesis/*`, story banks, debugging journals |
| **Archive**   | Inactive but possibly useful                        | Removed forks, deprecated apps, old workflows                   |

**Rules for builders (human or LLM):**

- Anything captured must have a defined Express path within one hop. Captures that never get expressed are dead weight.
- When in doubt where something goes, it is a Resource, not a Project.
- Don't create a fifth bucket. The four are deliberately small.

### 2. Homework for Life — Matthew Dicks

The daily storytelling habit from *Storyworthy*: every day, write down one small moment that could become a story.

This repo treats Homework for Life as a **first-class data source**, not a journaling app. Daily dumps, work stories, debugging lessons, observations, and small wins all flow through the same capture + index pipeline. Over time the corpus becomes queryable by prompt:

- "What was I working on the week of 2026-04-12?"
- "Show me debugging stories tagged `#root-cause`."
- "Pull together my LinkedIn-idea moments from the last 90 days."
- "Reconstruct the timeline for the OANDA forex agent rollout."

Three capabilities follow from treating lived signal as queryable data, not prose:

- **Retrospective curation.** Past entries — and on-demand sweeps of an archive by date — let the operator reconstruct the events and timeline of any period by looking *back* over it, not just recall a single day. Recall is a first-class read path, not a side effect of capture.
- **Artifact retrieval.** Entries anchor to the files, commits, media, and links behind each moment (the `References` block below), so the corpus doubles as a retrieval index for the *artifacts* of the past — the source dump, the screenshot, the commit — not only the words about them.
- **Enrichment from integrations.** The same `apps/` integrations that capture state can be queried at recall time to enrich a period with context the corpus never stored on its own — the surrounding commits, the browsing trail, the media sitting in the inbox.

**Daily entry shape (the format we standardize on):**

```text
## YYYY-MM-DD

Moment:
What happened:
Why it stayed with me:
Possible use:
Tags:  #work-story #debugging #automation #career #personal #funny #lesson #linkedin-idea
References:            (optional — URLs / host paths to source material;
                        rendered only when present; resolved by the weekly
                        summarizer to ground the rollup in the source)
```

**Rules for builders:**

- Any new integration that produces personal signal (calendar, location, finance, comms) should consider how its output participates in the HFL corpus — both as a scheduled feed-in *and* as a live source the recall path can query to enrich a period on demand.
- Workflows that summarize, tag, or surface entries are first-class — they are the "Distill" half of CODE applied to lived experience.
- The smallest useful entry is one line. Don't gate capture on having something profound to say.
- **Provenance convention:** an `hfl_signal` entry-writer should set `References` to its source artifact (the `express_target` it distilled — a dump file path, commit URL, conversation link). This closes the Capture→Distill→Express loop within one hop: references are not dead weight because the weekly summarizer resolves them. The `manifesto` metadata block on beat entries stays pure intent-routing — this convention lives in the entry, not that block.

### 3. The 7 Habits — Stephen R. Covey

Covey gives the principles for **deciding what matters**; Forte gives the system for **capturing it**. Together they decide what gets built next.

| Habit                                                  | How it applies inside this repo                                                                  |
| ------------------------------------------------------ | ------------------------------------------------------------------------------------------------- |
| **1. Be Proactive**                                    | Automate the things you control; don't wait for an external system to remind you they're broken.  |
| **2. Begin with the End in Mind**                      | Every new app/workflow/agent starts from a defined output — Express path before Capture path.     |
| **3. Put First Things First**                          | Important > urgent: refactors that compound > one-off fixes; durable infra > clever hacks.        |
| **4. Think Win-Win**                                   | Skills, apps, and configs are designed to be reused by forked deployments — not bespoke one-offs. |
| **5. Seek First to Understand, Then to Be Understood** | LLMs: read existing code before generating new code. Humans: read the diff before reviewing.      |
| **6. Synergize**                                       | Compose existing apps into workflows; compose existing skills into agents. Don't re-implement.    |
| **7. Sharpen the Saw**                                 | Maintain the platform: tests, deploys, dependency hygiene, observability, periodic doc sweeps.    |

**Rules for builders:**

- Habit 5 is non-negotiable for LLMs. No generation without exploration first.
- Habit 2 kills feature creep before it lands: if you can't name the Express output, don't start building.

### 4. The PAER operating loop — Plan, Analyze, Execute, Review

The unit of work in this repo. Every non-trivial change cycles through it.

```text
1. PLAN
   Decide what outcome you want.
   Question: What am I trying to achieve?
   Output:   A clear goal, scope, and next action.

2. ANALYZE
   Understand the situation before acting.
   Question: What do I know, what is missing, and what could go wrong?
   Output:   Key facts, risks, assumptions, options, and decision.

3. EXECUTE
   Do the work and capture the result.
   Question: What is the next concrete action?
   Output:   Completed task, notes, blockers, and follow-up items.

4. REVIEW
   Close the loop by learning from the run.
   Question: What worked, what didn't, what should I save for next time?
   Output:   Lessons, updated principles or docs, follow-ups filed, memory entries written.
```

**Rules for builders:**

- LLM agents should externalize PLAN and ANALYZE as artifacts (plans, task lists, scratch notes) before EXECUTE.
- REVIEW is not optional. A workflow that runs without producing a reviewable artifact (log, feed entry, dashboard tile, memory write) is half-built.
- Skip the loop only for trivial single-step changes. Anything multi-step gets all four phases.

---

## How LLMs working in this repo should use this manifesto

When an LLM (Claude Code, an agent under `agents/`, a skill invocation, a workflow generator) is asked to build, change, or recommend something:

1. **Frame the work in CODE.** Is this a Capture, Organize, Distill, or Express piece? If it's none, push back on the request.
2. **File the output in PARA.** Decide which bucket it belongs to. If it's a Project, name the deadline / done-state. If it's a Resource, link from the relevant index.
3. **Apply Habit 5 first.** Read the existing apps, workflows, skills, and configs that touch this area before generating anything. Don't invent abstractions that already exist.
4. **Apply Habit 2 next.** State the Express output in one sentence before designing the Capture. If you can't, stop and ask.
5. **Run PAER explicitly.** Plan → Analyze → Execute → Review, with artifacts at each step. The Review step writes back into memory, docs, or this manifesto if a principle needs updating.
6. **Favor reuse over reinvention.** Existing app integrations, skills, and helpers always win over freshly generated code.
7. **Default to no comments, no extra docs, no speculative abstractions.** Add only what the immediate task requires. (This rule is already in `CLAUDE.md`; this manifesto restates it because it is load-bearing.)

## How humans working in this repo should use this manifesto

1. **Before opening a skill, workflow, or app branch:** name the Express output. If you can't, the work isn't ready.
2. **At the end of each working day:** drop one Homework-for-Life entry. The corpus is only useful if it accumulates.
3. **Each week:** sweep one Resource doc (`docs/info/*`, this manifesto, root `README.md`) — Habit 7 in practice.
4. **When a principle stops applying:** edit this file. Stale principles are worse than no principles.

---

## Non-goals

This manifesto is not:

- A roadmap. Roadmaps live in Kanban boards and `TODO.md` files.
- A style guide. Code conventions live in `CLAUDE.md` and `docs/info/COMMIT-MESSAGE-GUIDE.md`.
- A product spec. Specs live next to the feature they describe.
- Comprehensive. It captures the load-bearing operating principles, nothing more.

---

## Related reading

- [`README.md`](../README.md) — what the platform is and what it integrates with.
- [`docs/info/SKILLS-INVENTORY.md`](info/SKILLS-INVENTORY.md) — the slash commands that operationalize this manifesto into builds.
- [`docs/info/AGENTS-TASKS-KANBAN.md`](info/AGENTS-TASKS-KANBAN.md) — how Projects in PARA flow through the Kanban agent.
- [`docs/info/COMMIT-MESSAGE-GUIDE.md`](info/COMMIT-MESSAGE-GUIDE.md) — how Express-level changes get recorded.
