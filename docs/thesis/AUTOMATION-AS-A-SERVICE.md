# Automation-as-a-Service — Scaling harqis-work to Many Operators

> Brainstorm captured 2026-06-05. **Not approved. Not scheduled. Not committed
> work.** This is a vision/thesis document exploring how the single-operator
> harqis-work platform could become a multi-tenant, AI-driven *Automation-as-a-Service*
> (AaaS) product — where each client forks a minimal base, then grows their own
> `apps/` and `workflows/` continuously, assisted by an embedded AI builder.
> Ideas move from here into real PRs via `/clarify-feature`.

This document is governed by [`docs/MANIFESTO.md`](../MANIFESTO.md). The thesis is
deliberately **Express-first** (Habit 2): the whole product is one Express path —
*turn a client's natural-language intent into a running, reviewed, manifesto-aligned
automation* — and everything below works backward from that sentence.

---

## TL;DR

The platform is **already 70% of an AaaS product** and doesn't know it. The pieces
that look like internal tooling are the load-bearing walls of a multi-tenant SaaS:

| Existing asset | What it already is | What it becomes in AaaS |
| --- | --- | --- |
| `/create-new-fork-repository` skill | One-shot client baseline cloner (prunes apps, redacts creds, creates private repo) | **Tenant provisioning** — the "sign up a new client" button |
| `/create-new-service-app`, `/create-new-workflow` skills | Codegen that scaffolds integrations + RPA pipelines | **The build engine** behind the `/apps` and `/workflows` frontend modules |
| `frontend/` (FastAPI + Jinja2 + HTMX) + `registry.json` | Dashboard that lists & triggers tasks | **The tenant control plane** (apps / workflows / config / assistant / machines) |
| `agents/projects/` (BaseKanbanAgent, BoardOrchestrator, profiles, MCP bridge) | Claude tool-use loop that executes Trello cards | **The assistant** that drives the build skills from a chat box |
| `machines.toml` + `scripts/deploy.py` (host/node roles, queues) | Per-machine deployment topology | **The `machines` module** — fleet config per tenant |
| `apps_config.yaml` + `.env/apps.env` + `SecretStore` scoping + `CONFIG_SOURCE` | Externalized, env-var-referenced, per-profile-scoped secrets | **Tenant credential isolation** (already supports Redis/HTTP config sources) |
| `docs/MANIFESTO.md` + `manifesto_audit.py` | Operating principles + CI gate | **The quality contract** for AI-generated automation |
| `workflows/hfl/` (COLLECT→DISTILL→DUAL-WRITE corpus + ES) | Personal-signal capture | **Per-tenant operational memory** that makes the assistant smarter over time |

**The core thesis:** the scaffolding skills are the codegen engine; today a *developer*
invokes them through the Claude Code CLI. AaaS is the act of exposing that same engine
through the **frontend + an embedded assistant**, so a non-developer client operator
can drive it — with the **manifesto as the guardrail** that keeps AI-generated automation
from becoming dead weight, and **HFL as the memory** that grounds each new build in what
the tenant has already done.

**The single hard decision** (Section 4): how isolated is a tenant — separate fork/repo/deploy
(today), shared-core + tenant overlay, or true multi-tenant single deployment? This choice
gates everything else and is the one thing worth deciding before building.

---

## 1. Where we are today (Habit 5 — understand first)

A read of the current architecture, so the vision is grounded and not aspirational fiction.

### 1.1 The three-tier substrate

```
apps/        41 integrations   — REST/AI/RPA clients. Self-contained: config.py, mcp.py,
                                 references/{dto,web/api}, tests/. Template at apps/.template/.
workflows/   9 task groups      — Celery Beat schedules chaining apps. tasks_config.py is
                                 the contract; keys start "run-job--"; each carries a
                                 'manifesto' metadata block. Template at workflows/.template/.
agents/      Claude agents      — BaseKanbanAgent (tool-use loop), BoardOrchestrator (polls
                                 Trello, claims cards by label, scopes secrets, dispatches),
                                 YAML profiles under profiles/examples/.
frontend/    FastAPI dashboard  — generate_registry.py globs workflows/*/tasks_config.py →
                                 registry.json → dashboard tabs + trigger buttons.
```

### 1.2 The control surfaces that already exist

- **Registry pipeline** — `frontend/generate_registry.py` discovers every `run-job--*`
  entry, harvests `task`/`schedule`/`queue`/`kwargs`, and merges into `frontend/registry.json`
  (preserving UI-edited labels). The frontend renders tabs and `POST /tasks/{workflow}/{key}/trigger`
  dispatches to Celery. **This is already a metadata-driven UI** — exactly the shape a
  multi-module control plane needs.
- **Config layering** — `apps/apps_config.py` resolves `${VAR}` references and honours a
  `CONFIG_SOURCE` env var: **local file, Redis, or HTTP endpoint**. The Redis/HTTP modes were
  built for distributed workers but are *precisely* the mechanism a multi-tenant config service
  needs (per-tenant config served from a central store).
- **Secret scoping** — the orchestrator's `SecretStore` injects only a profile's *required*
  secrets into an agent's execution context; the full env is never passed. Tenant isolation
  primitive, already shipped.
- **Fleet topology** — `machines.toml` (+ gitignored `machines.local.toml`) declares each
  machine's `role` (host/node), `queues`, disabled services, and per-OS `env_vars`;
  `scripts/deploy.py` auto-detects the host by `socket.gethostname()`. Celery broadcast queues
  (`*_broadcast`) already do fleet-wide fanout.
- **The manifesto gate** — `scripts/agents/manifesto_audit.py` walks all `tasks_config.py`,
  enforces "every capture has an Express path within one hop," and exits non-zero on violation.

### 1.3 The gap

Everything above is driven by a **developer at a CLI**. To become AaaS, three gaps close:

1. **Driver gap** — the build skills are invoked by a human typing `/create-new-workflow`.
   AaaS needs the *assistant* to invoke them from a chat box, on behalf of a non-developer.
2. **Tenancy gap** — "a client" today means "a forked repo on a machine." AaaS needs a
   first-class tenant boundary (identity, config store, fleet, billing, isolation).
3. **Loop gap** — there is no closed *intent → build → review → deploy → observe → learn* loop
   surfaced to the client. The parts exist (skills, PR flow, deploy, ES logs, HFL); they aren't
   wired into one self-service product surface.

The rest of this document is about closing those three gaps without rewriting the substrate.

---

## 2. The product shape — five frontend modules

The user's proposed frontend maps cleanly onto existing machinery. Each module is a thin
control plane over an engine that already exists.

### 2.1 `/apps` — integrations

**What the client sees:** a catalogue of installed integrations, a "browse marketplace" of
available ones, and a **"+ New integration"** button.

**What it drives:** `/create-new-service-app`. The client pastes an OpenAPI spec URL or a docs
link (Mode B), or names a stub (Mode A). The assistant runs the skill, which scaffolds
`apps/<name>/` (config, mcp, dto, web/api, tests) and performs the **registration cascade**
(`mcp/server.py`, `mcp_bridge.py` `_APP_LOADERS`, `dependencies/detector.py`,
`apps_config.yaml`, `.env/apps.env`, READMEs). The output is a PR, not a silent mutation.

**New surface needed:**
- An **app registry** analogous to `registry.json` but for apps (today apps are discovered by
  import; a JSON manifest per tenant makes the catalogue UI cheap).
- A **connection-test** action per app (call one read-only endpoint, confirm creds work) — this
  already half-exists via the smoke tests `/create-new-service-app` generates.
- A **marketplace**: the 41 upstream apps become an installable catalogue (Section 6).

### 2.2 `/workflows` — the automations the client builds

**What the client sees:** their `tasks_config.py` rendered as cards (this is literally the
current dashboard), plus **"+ New workflow"** and per-task enable/disable, schedule edit, and
**Run now**.

**What it drives:** `/create-new-workflow`. The client describes the automation in prose
("every weekday at 9am, pull new Stripe charges and post a summary to Slack"); the assistant
runs the skill, which **resolves missing apps by chaining `/create-new-service-app`**, installs
packages, scaffolds the task + schedule + manifesto block + tests, and opens a PR.

**New surface needed:**
- **Schedule editing from the UI** writing back to `tasks_config.py` (the registry already
  round-trips labels; extend to schedule/kwargs via a structured editor → generated diff → PR).
- **Dry-run / backtest** — run a workflow once against real config in a sandbox queue and show
  the result + ES log before scheduling it. The `adhoc` queue + `*_data_only` fallback twins are
  the precedent.
- **The manifesto block becomes a first-class form field**, not hidden metadata (Section 5).

### 2.3 `config` — keys, auth, creds, per-app env

**What the client sees:** per-app credential forms (the `${VAR}` placeholders from
`apps_config.yaml.example` rendered as fields), per-environment overrides (read path, write
path, dump inbox), and connection status.

**What it drives:** writes to the **tenant config store**. The decisive reuse here: `CONFIG_SOURCE`
already supports `redis` and `http`. A tenant config service (Section 4.3) serves each tenant's
resolved config dict to its workers — **no code change to the loader**, just a new backend that
populates the same shape `apps_config.py` already consumes.

**New surface needed:**
- A **secrets vault** (not plaintext YAML) — env vars move into an encrypted store (Vault/SOPS/
  cloud KMS), and the config service injects them at worker boot. The `${VAR}` indirection
  already makes the values swappable without touching app code.
- **Per-app environment variables** (write path, read-from-file) already exist as
  `machines.toml::env_vars`; promote them to a per-tenant, per-app config table.
- **Connection health** surfaced from the dependency detector
  (`agents/projects/dependencies/detector.py`) which already knows which env var each app needs.

### 2.4 `assistant` — the AI builder

This is the **keystone module** and the answer to "how is this AI-driven." It is a chat box plus
a configuration panel, backed by either the **Hermes orchestrator** or the **native Claude Agent
SDK**.

**Configuration panel:**
- **Provider** — Anthropic API key vs. Claude Code/Max subscription. `agents/projects/agent/provider.py`
  already detects this via `HARQIS_PROVIDER` and returns a billing hint. (Memory: cost-sensitive
  generation shells out to the local `claude -p`; per-tenant this becomes a provider choice.)
- **Model tier** — Haiku/Sonnet/Opus, governed by `docs/info/MANIFESTO-MODEL-GUIDE.md`.
- **Additional system prompt** — appended to the assistant's base persona; this is where a tenant
  encodes their business context ("we're a logistics firm; default timezone AEST; never post to
  social without approval").
- **Tool/skill allow-list** — which build skills the assistant may invoke (mirrors the profile
  `tools.allowed` model already in `agent_code.yaml`).

**The chat box drives a build loop** (this is the AI-driven core):

```
client intent (NL)
   │
   ▼
ASSISTANT  ──PLAN──►  restate intent as an Express target (Habit 2). If it can't, ask.
   │                  (reuses /clarify-feature's structured Q&A)
   ▼
   ──ANALYZE──►  query the tenant's HFL corpus + existing apps/workflows: "have we built
   │             something like this? what creds exist? what's the precedent task?"
   ▼
   ──EXECUTE──►  invoke /create-new-workflow (+ /create-new-service-app as needed).
   │             Skill emits a plan → client approves → scaffold → PR.
   ▼
   ──REVIEW──►   run manifesto_audit + tests in CI on the PR. Surface the diff + audit
                 result + dry-run output in the chat. Client clicks Merge → deploy.
```

The assistant is **not** a free-form code generator — it is a **structured driver of the existing
skills**, which keeps output on the manifesto rails. Two backends, same interface:
- **Hermes (orchestrator)** — the existing `BaseKanbanAgent`/`BoardOrchestrator` loop, repurposed
  from "poll Trello" to "respond to chat." Cards become chat turns; the worktree-per-card isolation
  becomes worktree-per-build.
- **Native Claude Agent SDK** — a thinner path for tenants who want the latest SDK features
  (compaction, memory tool, sub-agents) without the Trello/Kanban scaffolding.

### 2.5 `machines` — the fleet

**What the client sees:** a list of their machines (host + connected nodes), each with role,
queues consumed, services enabled, and live health.

**What it drives:** `machines.toml` / `machines.local.toml` + `scripts/deploy.py`. The host/node
model is already exactly this: one `host` (broker + scheduler + Docker), N `node` workers listening
to a subset of queues, auto-detected by hostname.

**New surface needed:**
- A **machine-enrollment flow**: a new node runs a one-line installer that registers it with the
  tenant's host (writes its section to `machines.local.toml`, starts the worker against the host's
  broker). Today this is manual TOML editing.
- **Queue assignment from the UI** (the `/manage-queues` skill already manages task→queue mapping;
  extend to machine→queue subscription).
- **Health + telemetry** — Flower already runs as a service; surface its data per tenant.
- **A managed-cloud option**: tenants without their own hardware get a hosted worker pool
  (Section 4 — this is where the isolation decision bites hardest).

---

## 3. HFL as a core feature (manifesto §2, made central)

The user wants HFL promoted to a core feature following the manifesto model. In AaaS, HFL stops
being "the operator's storytelling journal" and becomes **the tenant's operational memory** — and
it is the single biggest force-multiplier on assistant quality.

### 3.1 Why HFL is the moat

Every tenant accumulates a COLLECT→DISTILL→DUAL-WRITE corpus (Markdown + Elasticsearch) of what
their automation has *done*: which workflows ran, what they produced, what broke, what the operator
decided. Three manifesto capabilities map directly onto AaaS value:

| Manifesto §2 capability | AaaS application |
| --- | --- |
| **Retrospective curation** | "What automations did we ship last quarter?" "Reconstruct the incident timeline for the Stripe sync outage." A queryable operational history per tenant. |
| **Artifact retrieval** | The `References` block anchors each entry to the commit/PR/log/dump that produced it — the corpus doubles as a retrieval index over the tenant's own build artifacts. |
| **Enrichment from integrations** | At recall time, the assistant queries the tenant's live `apps/` to enrich a period — the surrounding commits, the run logs, the produced reports. |

### 3.2 The assistant reads HFL before it builds

This is the concrete wiring that makes HFL "core." In the ANALYZE step of the build loop (§2.4),
the assistant runs `query_hfl_entries()` against the tenant's corpus:

- **De-duplication** — "you already have a workflow that posts Stripe summaries; want to extend it
  instead of building a new one?" (Habit 6 — synergize, enforced by memory.)
- **Context grounding** — the tenant's additional system prompt is *augmented* by retrieved HFL
  context, so the assistant proposes builds that fit how this tenant actually operates.
- **Drift detection** — "this is the third time a workflow broke on the same expired token; want a
  credential-rotation alert?" The corpus surfaces patterns no single run reveals.

### 3.3 Every workflow is an HFL source by default

In the base fork, the `workflows/.template/` already produces manifesto-aligned tasks. AaaS extends
the template so that **completing a build emits an HFL entry** (`hfl_signal: True`) — "Shipped
workflow X on date Y; Express target Z; PR #N." The tenant's corpus then records not just what their
automations *capture from the world*, but **what they built and why**, closing the REVIEW loop of
PAER automatically. This makes HFL the substrate the manifesto §15 envisions: "anything the operator
has done, decided, observed, or built becomes recallable by prompt."

### 3.4 HFL ingest sources become a per-tenant menu

The existing `create-new-ingest-source-hfl` skill and the parked backlog in
[`HFL-INGEST-CANDIDATES.md`](HFL-INGEST-CANDIDATES.md) become a **tenant-facing catalogue**: a client
picks which signals feed their corpus (their git, their comms, their calendar, their dumps inbox),
each scaffolded by the same skill behind the `/apps`→`/workflows` flow.

---

## 4. The one decision that gates everything — the tenancy spectrum

How isolated is a tenant? This is the architectural fork in the road, and it should be decided
before any build. Three points on the spectrum, each with honest trade-offs:

### 4.1 Option A — Fork-per-tenant (today's model, extended)

Each client gets their own repo (via `/create-new-fork-repository`) deployed on their own host/nodes.

- **Pros:** Maximum isolation (separate repo, separate creds, separate fleet — already shipped).
  Tenant owns their automation outright; great for security-sensitive or air-gapped clients. Zero
  blast radius between tenants.
- **Cons:** N repos to keep in sync with upstream improvements. Maintenance scales linearly with
  tenants. No central observability. The `migrate-to-core` pattern + the `harqis-core` upstream
  package mitigate this (shared utilities flow up; forks pull them down) but don't eliminate it.
- **Best for:** the first 1–20 high-touch clients; enterprises that demand self-hosting.

### 4.2 Option B — Shared core + tenant overlay (recommended next step)

One upstream `harqis-core` + `harqis-work` codebase; each tenant is a **config + content overlay**
(their `apps_config`, their `workflows/<tenant>/`, their `machines`, their HFL corpus) layered on the
shared substrate. Forking becomes *provisioning a namespace*, not *cloning a repo*.

- **Pros:** Core improvements ship once to all tenants. Central observability and billing. The
  `CONFIG_SOURCE=http` mechanism already serves per-tenant config from a central store without code
  change. Tenant content (workflows, apps) stays isolated by namespace.
- **Cons:** Requires a real tenant boundary in code (today there is none — `workflows/` is flat).
  Shared process space means a misbehaving tenant workflow can affect neighbours unless sandboxed
  (per-tenant queues + worker pools mitigate; Celery already isolates by queue).
- **Best for:** scaling from ~20 to hundreds of tenants. **This is the recommended target** because
  it reuses the most existing machinery (`CONFIG_SOURCE`, queues, registry) while adding the one
  thing that's genuinely missing (a tenant namespace).

### 4.3 Option C — True multi-tenant single deployment

Fully managed cloud; tenants never see a repo or a machine. Pure SaaS.

- **Pros:** Lowest per-tenant ops cost; instant onboarding; the only model that reaches thousands of
  tenants.
- **Cons:** The biggest lift. Requires hardened sandboxing of tenant-authored code (their workflows
  are arbitrary Python), a code-execution security model the repo doesn't have today, and a
  managed worker fleet. Tenant-authored Python in a shared runtime is the hard security problem.
- **Best for:** a later phase, and possibly only for a "no-code" subset of workflows (declarative,
  not arbitrary Python) running in a constrained runtime.

**Recommendation:** ship **A** for the first clients (it already works), build toward **B** as the
product (the tenant namespace + config service are the only net-new infrastructure), and treat **C**
as a long-horizon option gated on a code-sandboxing investment. The decisive enabler for B is that
`CONFIG_SOURCE` + Celery queues + the registry already assume a distributed, externally-configured
fleet — the multi-tenant seams are half-cut.

---

## 5. The manifesto as the quality contract for AI-generated automation

When an AI builds automations for paying clients, "did it work?" is not enough — "is it dead weight,
is it observable, is it on the rails?" must be answerable mechanically. The manifesto model is
**already that contract**, and AaaS just enforces it per tenant.

- **The `manifesto` block becomes a required build output.** Today it's optional metadata; in AaaS
  the assistant *must* fill `code_role`, `para_bucket`, `express_target`, `review_artifact`, and
  `hfl_signal` for every generated workflow. The `/workflows` UI renders these as a form, so the
  client sees *what the automation produces and how it's verified* before merging.
- **`manifesto_audit.py` becomes a per-tenant CI gate.** Every assistant-generated PR runs the audit;
  a workflow with no Express path within one hop **cannot merge**. This is the single most important
  guardrail — it mechanically prevents the AI from shipping captures that go nowhere (the #1 failure
  mode of generous code generators).
- **PAER becomes the assistant's visible loop** (§2.4). PLAN/ANALYZE are externalized as chat
  artifacts the client approves; EXECUTE is the skill run; REVIEW is the audit + tests + dry-run.
  The client watches the loop, which builds trust in AI-authored automation.
- **The "Express path before Capture path" rule (Habit 2)** is how the assistant interrogates vague
  requests. "Pull my emails" → "and do *what* with them?" The assistant refuses to scaffold a capture
  with no express target — the same rule the audit enforces, applied at intent time.

This is the answer to the implicit risk in "AI continually builds workflows": without a contract,
that's a recipe for an accumulating swamp of half-built automations. The manifesto is the contract,
the audit is the enforcer, and HFL is the record. **Quality is a gate, not a hope.**

---

## 6. Additional features that make it feasible (the backlog)

Ranked roughly by leverage-to-effort. None are committed — this is the menu.

### 6.1 Marketplace of apps and workflows

The 41 upstream `apps/` and the workflow patterns become an **installable catalogue**. A tenant
browses, clicks install, the relevant `/create-new-service-app` scaffolding runs into their namespace.
Workflow *templates* (parameterized `tasks_config.py` blueprints) become one-click installs:
"Stripe→Slack daily summary," "GitHub→Trello issue triage." This is the network effect — every
tenant's good workflow can become a template for the next. (Win-Win, Habit 4, productized.)

### 6.2 Tenant onboarding wizard

`/create-new-fork-repository` already prunes to a curated 16-app keep list and creates a private repo.
Wrap it in a wizard: business name → industry preset (selects starter apps + workflow templates) →
provision namespace/repo → seed `.env` templates → first-run checklist. The skill's existing 9-step
flow is the backend; the wizard is the front.

### 6.3 Usage metering & billing

The orchestrator already tracks per-agent token usage and runtime (telemetry in `BoardOrchestrator`).
Promote this to a **per-tenant metering ledger**: assistant tokens (build cost), workflow run-minutes
(execution cost), API calls per app (integration cost). Billing tiers fall out naturally. The
provider-detection split (API key vs. Max subscription) already distinguishes billable vs.
subscription-covered work.

### 6.4 Observability per tenant

ES logging (`@log_result()`, the `es_logging` core lib) already writes structured run logs. A
per-tenant dashboard over the tenant's ES index gives: workflow success/failure rates, last-run
timestamps, error trends, credential-expiry alerts. The `dumps` workflow's alerting pattern
(android-pull failure alerts, per recent commits) is the precedent for proactive notifications.

### 6.5 The "approval inbox" — human-in-the-loop for AI builds

The orchestrator's `AgentPausedForQuestion` mechanism (an agent pauses mid-run, posts a question,
resumes on reply) generalizes to an **approval inbox**: the assistant proposes a build/deploy, the
client approves/edits/rejects from the UI, the build resumes. This is the safety valve that makes
"AI builds my automations" acceptable to a cautious client.

### 6.6 Versioning, rollback, and audit trail

Because every build is a **PR**, the tenant's repo/namespace *is* the version history. Surface it:
"roll back workflow X to last week's version," "show me who (which assistant run, which client
approval) changed this schedule." The git history + the HFL build entries + the audit log are three
views of the same truth.

### 6.7 Cross-tenant core migration (already prototyped)

The `migrate-to-core` skill sweeps `harqis-work` for generic utilities that belong upstream in
`harqis-core`, opening review-gated PRs. In AaaS this becomes the **mechanism by which one tenant's
generic improvement benefits all** — a util one client's assistant writes flows up to core, then down
to every fork/namespace. This is how Option-A forks stay in sync and how the platform compounds.

### 6.8 Guardrail profiles per tenant

The agent-profile model (`agent_code.yaml` etc., with `tools.allowed`, `permissions.filesystem/
network/git`, `secrets.required`) becomes **per-tenant assistant guardrails**: which apps the
assistant may touch, whether it can push vs. require PR, network allow-lists. A conservative tenant
runs a locked-down assistant; a power user unlocks more. The model exists; it just needs a UI.

---

## 7. A phased path (illustrative, not a roadmap)

Roadmaps live in Kanban (manifesto non-goal). This is dependency ordering, not dates.

1. **Phase 0 — Surface the loop for one operator.** Wire the existing assistant (Hermes) to drive
   `/create-new-workflow` from the existing FastAPI frontend's chat box, PR + audit + dry-run in the
   loop. Proves the intent→build→review→deploy loop end-to-end on the current single-tenant repo.
2. **Phase 1 — Productize the fork.** Wrap `/create-new-fork-repository` in the onboarding wizard;
   ship Option A for the first real clients. Each is a self-hosted fork; you operate the assistant
   loop for them as a service.
3. **Phase 2 — The tenant namespace (Option B).** Add the tenant boundary: `CONFIG_SOURCE=http`
   config service, per-tenant `workflows/<tenant>/` namespace, per-tenant queues + ES indices + HFL
   corpus. Core ships once; tenants overlay.
4. **Phase 3 — Self-service.** The five frontend modules become fully client-operable; metering +
   billing + approval inbox close the SaaS loop. The assistant onboards tenants without you.
5. **Phase 4 — Managed cloud (Option C), if warranted.** Sandboxed runtime for declarative workflows;
   hosted worker pools. Gated on the code-execution security investment.

Each phase is independently valuable and reuses the phase before it.

---

## 8. Risks & open questions (ANALYZE, surfaced not hidden)

- **Arbitrary tenant code is the security ceiling.** Workflows are Python. Options A/B isolate by
  repo/process/queue; Option C needs a sandbox the repo doesn't have. Don't promise C before solving
  this. *Open: is a declarative (no-code) workflow subset worth building for the managed tier?*
- **Assistant build quality at scale.** The manifesto gate stops dead weight, but not subtle logic
  bugs. Dry-run/backtest (§2.2) + tests + the approval inbox are the mitigations. *Open: what's the
  minimum test bar an AI-generated workflow must clear to auto-merge vs. require human approval?*
- **Credential blast radius.** `SecretStore` scoping is good; a central vault (§2.3) is the missing
  piece. *Open: self-hosted secrets (tenant owns the vault) vs. managed (you hold KMS) — likely both,
  per tenancy option.*
- **Upstream/fork drift (Option A).** `migrate-to-core` helps but forks still diverge. *Open: how
  much divergence is acceptable before B becomes mandatory?*
- **Cost attribution.** Assistant token spend is the new variable cost. Metering (§6.3) must exist
  before self-service, or a runaway assistant loop bills the house. *Open: hard per-tenant token
  ceilings enforced where — assistant, orchestrator, or both?*
- **The "swamp" failure mode.** Generous AI generation + no curation = an accumulating pile of
  half-used workflows. HFL drift-detection (§3.2) + manifesto audit + a periodic "what's dead weight?"
  sweep (a `migrate-to-core`-style scheduled critic) are the defense.

---

## Non-goals (for this document)

- A roadmap with dates — phases above are dependency ordering only.
- A product spec or pricing model — those live next to the feature when it's scoped via `/clarify-feature`.
- A rewrite of the substrate — the entire thesis is *reuse the existing engine, add the tenant seam
  and the assistant driver*. Anything that proposes rewriting `apps/`, `workflows/`, or the agent
  loop is out of scope.

---

## Related reading

- [`docs/MANIFESTO.md`](../MANIFESTO.md) — the operating principles this thesis is governed by.
- [`docs/thesis/MANIFESTO-REPO-UPDATES.md`](MANIFESTO-REPO-UPDATES.md) — how the manifesto metadata + audit gate were rolled out.
- [`docs/thesis/HFL-INGEST-CANDIDATES.md`](HFL-INGEST-CANDIDATES.md) — the per-tenant HFL ingest menu (§3.4).
- [`docs/thesis/RAG-WORKFLOW.md`](RAG-WORKFLOW.md) — retrieval patterns the assistant's ANALYZE step builds on.
- [`docs/info/SKILLS-INVENTORY.md`](../info/SKILLS-INVENTORY.md) — the build skills that become the frontend modules' engines.
- [`docs/info/MANIFESTO-MODEL-GUIDE.md`](../info/MANIFESTO-MODEL-GUIDE.md) — model-tier selection for the assistant config panel (§2.4).
- [`docs/info/AGENTS-TASKS-KANBAN.md`](../info/AGENTS-TASKS-KANBAN.md) — the orchestrator/Hermes loop the assistant repurposes.
