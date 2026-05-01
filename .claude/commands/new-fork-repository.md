Fork the `harqis-work` repository into a fresh, business-/client-scoped baseline that another team can adopt as the starting point for their own automation host. The fork keeps the platform skeleton (`apps/`, `agents/`, `core` integration, deploy scripts) but strips local-only AI tooling and pre-built workflow categories so the consuming agents have a clean slate.

## Arguments

`$ARGUMENTS` format (parse left to right):

```
<business_or_client_name> [--target-dir <path>] [--remote <git_url>] [--owner <gh_org_or_user>] [--visibility public|private|internal] [--description "<short blurb>"] [--keep <folder,folder,...>] [--strip <folder,folder,...>] [--no-create-repo] [--no-push] [--no-git-init] [--dry-run]
```

| Token | Required | Description |
|---|---|---|
| `business_or_client_name` | Yes | Free-form name. Will be slugified to kebab-case for the repo / folder name (`Acme Logistics` → `acme-logistics`). The final repo name is always `harqis-work-fork-<slug>`. |
| `--target-dir <path>` | No | Where to create the fork on disk. Default: sibling of the source repo, i.e. `<parent_of_source>/harqis-work-fork-<slug>`. |
| `--remote <git_url>` | No | Set as `origin` after `git init`. If omitted, the skill calls `gh repo create` instead (default behaviour) — pass this when the GitHub repo already exists or you want to push to a non-GitHub remote. |
| `--owner <gh_org_or_user>` | No | Owner under which to create the GitHub repo. Defaults to the authenticated `gh` user. Pass this for org-owned forks (`--owner acme-corp`). |
| `--visibility public\|private\|internal` | No | Visibility for the auto-created GitHub repo. **Default: `private`** — forks may carry client business context and should not be public unless explicitly opted in. `internal` is org-only. |
| `--description "<text>"` | No | One-paragraph project description for the new README. Also passed to `gh repo create --description`. If omitted, ask the user (Step 0). |
| `--keep <list>` | No | Comma-separated list of workflow categories to preserve from the source (default: only `.template` is kept). Example: `--keep .template,n8n`. |
| `--strip <list>` | No | Comma-separated list of additional top-level folders to remove from the fork (in addition to the always-stripped `.claude` and `.openclaw`). |
| `--no-create-repo` | No | Skip `gh repo create`. The skill still runs `git init` + initial commit; the user wires the remote manually. |
| `--no-push` | No | Initialize git and (optionally) create the GitHub repo, but do not run `git push`. |
| `--no-git-init` | No | Skip `git init` entirely. Implies `--no-create-repo` and `--no-push`. Useful when the user wants to wire git themselves. |
| `--dry-run` | No | Print the plan (folders kept, folders stripped, files rewritten, gh actions) without touching disk or invoking gh. |

The agent invoking this skill may also pass these decisions inline in a natural-language prompt; parse the prompt for them before falling back to `$ARGUMENTS`.

---

## Step 0 — Clarify inputs before touching disk

Confirm or ask for the following if not unambiguously provided:

1. **Business / client name** — required for slug + README context.
2. **Description** — what does this fork automate? Which industry or use case? (Used in the new README intro.)
3. **Target directory** — confirm the absolute path. Refuse to write into the source repo itself.
4. **Categories to keep** — by default ONLY `workflows/.template/` is kept. Any others (`n8n`, `social`, `desktop`, `hud`, `finance`, `mobile`, `purchases`) must be explicitly opted in via `--keep`.
5. **GitHub auto-publish** — by default the skill creates a private GitHub repo via `gh repo create` and pushes the initial commit. Confirm:
   - Owner (default: authenticated `gh` user; pass `--owner` for an org).
   - Visibility (default: `private`; `--visibility public` to opt out — never silently public).
   - Skip entirely with `--no-create-repo` (init + commit only) or `--no-push` (create repo but don't push).
6. **App inventory pruning** — does the user want to keep all entries under `apps/`, or trim to a shortlist? (Default: keep all — apps are reusable building blocks. Trimming is opt-in.)

If any of these are unclear, ASK before continuing — the fork is hard to undo cleanly once files are duplicated.

---

## Step 1 — Resolve the source repo and the fork target

The source is the current working directory's repo root (`harqis-work`). Verify before copying:

```bash
git -C . rev-parse --show-toplevel
git -C . status --porcelain | head
```

Refuse to proceed if:
- Not inside a git repo
- Source repo has uncommitted changes (warn the user; allow override only if they explicitly say "use the working tree as-is")

Compute the fork path:

```
slug = slugify(<business_or_client_name>)              # lowercase kebab-case
fork_name = "harqis-work-fork-" + slug
target = <target-dir override>  or  <parent_of_source>/<fork_name>
```

Refuse if `target` already exists and is non-empty. Tell the user and stop.

---

## Step 2 — Decide what to copy vs. strip

Build two explicit lists before copying. Print them to the user for confirmation (or just print under `--dry-run`).

### Always strip (never carried into the fork)

```
.claude/                  # local Claude Code agent config — fork team installs their own
.openclaw/                # local OpenClaw agent state — host-machine specific
.idea/                    # IDE-local
.run/                     # IDE run configs
.venv/                    # Python virtualenv
.pytest_cache/
__pycache__/              # at every level
*.pyc
app.log, app.log.*, app-debug.log
celerybeat-schedule.*     # local scheduler state
data/                     # local cached data dumps
logs/                     # runtime audit logs (kanban_audit.jsonl, daily/, weekly/, …)
```

### Always strip from `workflows/` (custom categories — replaced by minimal scaffold)

```
workflows/desktop/
workflows/finance/
workflows/hud/
workflows/mobile/
workflows/n8n/
workflows/purchases/
workflows/social/
```

…and any other directory directly under `workflows/` that is NOT in the keep list. The keep list defaults to `[".template"]` and is extended by `--keep`.

### Always strip from `agents/` (any client-private profiles or memory)

Walk `agents/` and strip:
- Anything under `agents/kanban/profiles/` that is NOT inside `examples/` (private profiles stay with the source).
- Any `*.local.yaml` / `*.local.json` files.
- Any `agents/openclaw/memory/` directory contents.

### Always preserve

```
apps/                     # all app integrations (unless --strip lists specific apps)
core/                     # core framework hooks if vendored locally
agents/                   # agent framework (after the prune above)
docs/                     # cross-cutting docs (will be rewritten in Step 5)
scripts/                  # deploy + ops scripts
frontend/                 # if present, minus its .venv
requirements.txt
Dockerfile
docker-compose.yml
LICENSE
.gitignore
.dockerignore
.github/                  # CI workflows — useful for the fork
apps_config.yaml.example  # if it exists; otherwise generate from apps_config.yaml (Step 4c)
```

User-supplied `--strip` entries are added to the strip list verbatim.

### Print the plan

Show the user a table:

```
The fork will be created at: <target_path>

KEEP (will be copied):
  apps/ (all 30+ integrations)
  agents/ (framework + example profiles only)
  core/, docs/, scripts/, frontend/
  workflows/.template/  ← only category retained
  Dockerfile, docker-compose.yml, requirements.txt, LICENSE, .gitignore, .dockerignore, .github/

STRIP (will not be copied):
  .claude/, .openclaw/, .idea/, .run/, .venv/, .pytest_cache/, __pycache__/
  workflows/desktop/, workflows/finance/, workflows/hud/, workflows/mobile/,
  workflows/n8n/, workflows/purchases/, workflows/social/
  agents/kanban/profiles/<private profiles>
  app.log*, celerybeat-schedule.*, data/
  <any --strip entries>

REWRITE (will be regenerated, not copied):
  README.md            (new intro for <business>)
  workflows/README.md  (minimal fork instructions)
  workflows/config.py  (minimal — only .template merge, commented)
  workflows/queues.py  (minimal — DEFAULT + ADHOC only)
  apps_config.yaml     (only if .example variant doesn't exist; redacted copy)
```

Pause for confirmation unless `--dry-run` or the user has pre-authorized.

---

## Step 3 — Copy the source tree, applying the strip list

Use `robocopy` on Windows (PowerShell) or `rsync` on POSIX, with explicit excludes. Do NOT use `cp -r` then `rm` after the fact — copy correctly the first time.

**PowerShell (Windows default for this repo):**

```powershell
$excludeDirs = @('.claude','.openclaw','.idea','.run','.venv','.pytest_cache','__pycache__','data')
$excludeWorkflowDirs = @('desktop','finance','hud','mobile','n8n','purchases','social')   # extend with --strip values; subtract --keep

robocopy <source> <target> /E `
    /XD ($excludeDirs + ($excludeWorkflowDirs | ForEach-Object { Join-Path '<source>\workflows' $_ })) `
    /XF *.pyc app.log* app-debug.log celerybeat-schedule.*
```

**Bash:**

```bash
rsync -a \
  --exclude='.claude' --exclude='.openclaw' --exclude='.idea' --exclude='.run' \
  --exclude='.venv' --exclude='.pytest_cache' --exclude='__pycache__' \
  --exclude='*.pyc' --exclude='app.log*' --exclude='app-debug.log' \
  --exclude='celerybeat-schedule.*' --exclude='data/' \
  --exclude='workflows/desktop/' --exclude='workflows/finance/' \
  --exclude='workflows/hud/' --exclude='workflows/mobile/' \
  --exclude='workflows/n8n/' --exclude='workflows/purchases/' \
  --exclude='workflows/social/' \
  <source>/ <target>/
```

After copy, verify:

```bash
ls <target>
ls <target>/workflows
test ! -d <target>/.claude && echo "ok: .claude stripped"
test ! -d <target>/.openclaw && echo "ok: .openclaw stripped"
test -d <target>/workflows/.template && echo "ok: template kept"
```

---

## Step 4 — Regenerate the minimal `workflows/` scaffold

The fork's `workflows/` folder must contain ONLY:

```
workflows/
├── __init__.py
├── README.md          # rewritten (Step 4a)
├── config.py          # rewritten (Step 4b)
├── queues.py          # rewritten (Step 4c)
└── .template/         # copied as-is from source
    ├── __init__.py
    ├── README.md
    ├── tasks/
    ├── prompts/
    ├── diagrams/
    ├── tests/
    └── tasks_config.py
```

Plus any extra category the user explicitly passed via `--keep` — those are copied verbatim from the source.

### Step 4a — Write `workflows/README.md`

Replace whatever was copied with this minimal instructions file. Substitute `<BUSINESS_NAME>` and `<DESCRIPTION>` from Step 0.

```markdown
# Workflows — <BUSINESS_NAME> fork

This directory holds the Celery Beat scheduled tasks (RPA-style automations) for the
<BUSINESS_NAME> automation host, forked from [`harqis-work`](https://github.com/brianbartilet/harqis-work).

The fork ships with **no pre-built categories** — only the `.template` reference. Add
your own categories below as you build the workflows for <BUSINESS_NAME>.

## Adding a new workflow

1. Copy the template:
   ```bash
   cp -r workflows/.template workflows/<your_category>
   ```
2. Rename the constants inside `workflows/<your_category>/tasks_config.py`
   (`WORKFLOW_TEMPLATE` → `WORKFLOW_<YOUR_CATEGORY>`).
3. Implement task functions in `workflows/<your_category>/tasks/<module>.py`,
   using the `@SPROUT.task()` decorator pattern shown in `.template/`.
4. Register the task module in `workflows/<your_category>/__init__.py` —
   `SPROUT.autodiscover_tasks` does NOT walk into `tasks/` subpackages, so each
   module must be imported explicitly.
5. Wire the new schedule into `workflows/config.py` by importing
   `WORKFLOW_<YOUR_CATEGORY>` and merging it into `CONFIG_DICTIONARY`.

If you have access to Claude Code with the harqis-work skills installed, you can
delegate the whole flow to `/new-workflow` instead of doing it manually.

## Queues

Queue names live in `workflows/queues.py`. The fork ships with two queues by default:

| Queue | Type | Use when |
|---|---|---|
| `default` | Direct | One worker dequeues each task — the home for any task without an explicit route. |
| `adhoc`   | Direct | One-off triggers and on-demand executions. |

Add more queues (e.g. domain-specific direct queues, broadcast/fanout queues for
cluster-wide actions) by extending `WorkflowQueue` and registering them in
`workflows/config.py` under `SPROUT.conf.task_queues`.

For the full design rationale (direct vs fanout, idempotency rules, broadcast
caveats), see the upstream [`harqis-work` workflows README](https://github.com/brianbartilet/harqis-work/blob/main/workflows/README.md).
```

### Step 4b — Write `workflows/config.py`

Strip the upstream imports for `desktop` / `hud` / `purchases` / `social`. Leave the
template entry commented as a hint. Keep the broadcast / fanout topology block out by
default — the fork can re-introduce it if it ever needs cluster-wide tasks.

```python
"""
Celery Beat configuration for the <BUSINESS_NAME> fork.

This is the minimal scaffold that ships with `harqis-work-fork-<slug>`. As you
build out workflow categories under `workflows/<category>/`, import their
`WORKFLOW_<CATEGORY>` dict here and merge it into `CONFIG_DICTIONARY`.

References:
- Celery Periodic Tasks: https://docs.celeryproject.org/en/stable/userguide/periodic-tasks.html
"""
from kombu import Queue

from core.apps.sprout.app.celery import SPROUT
from core.apps.sprout.settings import TIME_ZONE, USE_TZ
from workflows.queues import WorkflowQueue

# ── Add workflow imports below as you create new categories ─────────────────
# from workflows.<category>.tasks_config import WORKFLOW_<CATEGORY>


SPROUT.conf.enable_utc = USE_TZ
SPROUT.conf.timezone = TIME_ZONE
SPROUT.conf.broker_connection_retry_on_startup = True
SPROUT.autodiscover_tasks(['workflows'])

# Merge each new WORKFLOW_<CATEGORY> dict here as you add categories.
# CONFIG_DICTIONARY = WORKFLOW_<CATEGORY_A> | WORKFLOW_<CATEGORY_B>
CONFIG_DICTIONARY = {}

SPROUT.conf.beat_schedule = CONFIG_DICTIONARY

# ── Queue topology ────────────────────────────────────────────────────────────
SPROUT.conf.task_queues = (
    Queue(WorkflowQueue.DEFAULT.value),
    Queue(WorkflowQueue.ADHOC.value),
)
SPROUT.conf.task_default_queue = WorkflowQueue.DEFAULT.value

# Add task-name-pattern routes here when domain-specific queues are introduced.
SPROUT.conf.task_routes = {}
```

### Step 4c — Write `workflows/queues.py`

```python
from enum import StrEnum


class WorkflowQueue(StrEnum):
    """Logical queues consumed by Celery workers in the <BUSINESS_NAME> fork.

    Each value is the literal queue name Celery / RabbitMQ uses on the wire.
    See `workflows.config` for queue declarations (direct vs fanout).
    """

    # ── Direct (competing-consumers) queues — exactly one worker per task ──
    DEFAULT = "default"
    ADHOC = "adhoc"

    # Add domain-specific direct queues (e.g. EXAMPLE = "example") here as
    # the fork's workflows demand them. For cluster-wide actions, introduce a
    # `<DOMAIN>_BROADCAST` member and register it as `Broadcast(...)` in
    # `workflows/config.py`.
```

### Step 4d — Keep `workflows/__init__.py` empty (or with a one-line comment)

```python
# Workflow categories register themselves via their own __init__.py.
# Add `import workflows.<category>` here only if you need to force-load a
# category that isn't picked up by autodiscovery.
```

---

## Step 5 — Rewrite the top-level `README.md`

Read the source `README.md` (43k+ chars) for structure, but rewrite the top sections
for the fork. Keep the App Inventory table verbatim — it documents the platform's
reusable building blocks. Strip sections that describe Brian's personal use cases
(MTG resale, OANDA forex, personal HUD) unless the consuming agent explicitly opts
to keep them via the `--description` flag context.

Required sections (in order):

1. **Title** — `# HARQIS Work — <BUSINESS_NAME> Fork`
2. **Origin notice** — one paragraph explaining this is a fork of
   [`harqis-work`](https://github.com/brianbartilet/harqis-work) scaffolded as the
   automation baseline for `<BUSINESS_NAME>`. Link the upstream repo.
3. **Description** — the user-supplied `--description` (or Step 0 answer), framed as
   "What this fork automates for `<BUSINESS_NAME>`".
4. **Architecture** — keep the upstream three-layer description (apps / workflows /
   agents) verbatim.
5. **App Inventory** — keep the upstream table verbatim. Add a note: *"Apps are
   reusable building blocks; the fork inherits all of them. Apps not relevant to
   `<BUSINESS_NAME>` can be removed without affecting the rest."*
6. **Workflows** — replace the upstream list of pre-built categories with:
   *"This fork ships with no pre-built workflow categories. Use the `.template`
   under `workflows/` and the `/new-workflow` skill (or copy the template manually)
   to build the automations specific to `<BUSINESS_NAME>`."*
7. **Getting started** — copy the upstream "Deployment" / "Quick start" section,
   replace any path examples with the fork's path, and replace the repo URL.
8. **Upstream sync** — short section explaining how to pull updates from upstream
   `harqis-work` if the fork wants to track new app integrations:
   ```bash
   git remote add upstream https://github.com/brianbartilet/harqis-work.git
   git fetch upstream
   git merge upstream/main   # resolve conflicts manually for diverged files
   ```
9. **License** — preserve the upstream LICENSE reference.

The new README must NOT reference `.claude/`, `.openclaw/`, or any of the stripped
workflow categories. Search for and rewrite/remove those mentions before saving.

---

## Step 6 — Sweep the rest of the docs for stale references

Run a grep over the fork for anything that points at stripped folders. Remove or
rewrite each hit.

```bash
grep -rE "(\.claude/|\.openclaw/|workflows/(desktop|finance|hud|mobile|n8n|purchases|social))" <target>/docs <target>/scripts <target>/agents <target>/README.md
```

For each hit:
- If it's a doc reference (markdown): rewrite to point at the upstream repo, OR delete the section if it only made sense in the personal context.
- If it's code (a script that imports a stripped module): comment out the import with a `# TODO: re-introduce after building <category>` marker.
- If it's a deploy script flag (`--with-broadcast`, `-q hud`): leave it but add a comment noting the fork has no broadcast queue by default.

Do NOT scrub aggressively — better to leave a TODO than to silently remove
working scripts that the fork might re-enable later.

---

## Step 7 — Sanitize secrets

Walk `<target>` for files that may contain credentials and replace with templates.

```bash
ls <target>/.env/ 2>/dev/null         # remove real env files; keep .env/*.example
ls <target>/apps_config.yaml 2>/dev/null
```

Rules:
- **`.env/`** — Any file that is NOT `*.example` → delete from the fork. Then for
  every removed file, regenerate an `.example` template from the upstream copy by
  preserving keys/comments/section dividers and replacing any value that isn't
  obviously safe (port numbers, hostnames, public URLs, default placeholder strings)
  with `<REPLACE_ME>`. Hosts (`http://elasticsearch:9200`), ports (`5672`,
  `8083`, `15000`), `WORKFLOW_CONFIG="workflows.config"`, and broker URL templates
  with placeholder credentials (`amqp://guest:guest@localhost:5672/`) may be kept
  as-is. Tokens, passwords, account IDs, API keys, OAuth refresh tokens, and
  asset paths — always redact. Save the result as `.env/<name>.env.example`.

- **`apps_config.yaml`** — Three cases, in order of preference:
  1. If `apps_config.yaml.example` already exists upstream → copy only that and
     delete `apps_config.yaml` from the fork.
  2. If every credential value in upstream `apps_config.yaml` is already an
     `${ENV_VAR}` placeholder (no inline secrets), the file is effectively a
     template — copy it verbatim to `apps_config.yaml.example` and delete the
     original from the fork. Verify with:
     ```bash
     grep -nE "(token|key|secret|password|client_id|client_secret):" \
       <source>/apps_config.yaml | grep -vE '\$\{|^#'
     ```
     A clean result (or only matches like `max_tokens: 200`) confirms the
     template-only condition.
  3. Otherwise generate `apps_config.yaml.example` by reading the file and
     replacing each non-templated credential string with `<REPLACE_ME>`,
     preserving keys, structure, and comments. Then delete the original
     `apps_config.yaml` from the fork.

- **OAuth / service-account JSON** — Any `*.json` under `.env/` that looks like a
  Google `credentials.json`, `storage.json`, or service-account file → delete
  outright. Do not generate an `.example` (the structure is well-known; the host
  operator obtains a fresh download from the relevant cloud console). Print which
  files were removed in the activation checklist.

- **Pattern sweep** — Any file containing obvious credential shapes
  (`api_key:`, `secret:`, `password:`, `token:`, `Bearer <hex>`,
  `OAUTH_REFRESH_TOKEN=`, `sk-…`, `sk-ant-…`, `ghp_…`, `AIza…`, JWTs starting
  `eyJhbGciOi…`, `ATTA…`, `sk_live_…`, `ntn_…`) → flag to the user and ask before
  including.

Print a checklist of secrets the fork's host operator must supply before the platform
will boot.

---

## Step 8 — Initialize git, create the GitHub repo, and push

The default behaviour is end-to-end automation: `git init` → initial commit →
`gh repo create` (private) → `git push`. The flags below let the user opt out of
each layer.

Skip the entire step if `--no-git-init` was passed (it implies `--no-create-repo`
and `--no-push` too).

### 8a — Initialize and commit

```bash
cd <target>
git init -b main
git add -A
git status --short | head      # sanity-check what's about to be committed
git commit -m "chore: scaffold harqis-work-fork-<slug> from upstream"
```

If the commit fails because of empty staging (which would mean the copy in Step 3
or the rewrites in Steps 4–7 produced nothing to track), STOP — do not run
`--allow-empty`. Surface the error and let the user investigate.

### 8b — Auto-create the GitHub repo (default unless `--no-create-repo` or `--remote` was passed)

#### Preflight: verify `gh` is installed and authenticated

```bash
command -v gh >/dev/null 2>&1 || { echo "gh CLI not installed — install with 'winget install --id GitHub.cli' (Windows) or 'brew install gh' (macOS)"; exit 1; }
gh auth status 2>&1 | head -5
```

If `gh auth status` reports the user is not logged in, STOP and tell them to run
`gh auth login` in a terminal (since `/commit` and similar interactive logins
must happen at the user's terminal, not from inside Claude Code). Print:

> The `gh` CLI is not authenticated. Run `gh auth login` in your terminal, then
> re-invoke `/new-fork-repository` (or pass `--no-create-repo` to skip).

#### Resolve the owner

If `--owner <gh_org_or_user>` was passed, use it. Otherwise default to the
authenticated user:

```bash
GH_OWNER=$(gh api user --jq .login)
```

Confirm the resolved owner with the user before creating the repo unless they
already explicitly named one. Print: `Will create <owner>/harqis-work-fork-<slug>
(<visibility>).`

#### Create

```bash
gh repo create "<owner>/harqis-work-fork-<slug>" \
  --<visibility>                                 \    # --private (default), --public, or --internal
  --description "<description from Step 0 or --description>" \
  --source=.                                     \
  --remote=origin
```

Notes:
- `gh repo create` with `--source=.` and `--remote=origin` adds the remote to
  the local repo automatically. Do not run a separate `git remote add origin`.
- If the repo name already exists under that owner, `gh` errors out — surface
  the error and ask whether to (a) pick a different slug, (b) push to the
  existing repo (skip create with `--no-create-repo` and pass `--remote`), or
  (c) abort. Never overwrite an existing repo.

#### `--remote <url>` override

If the user passed `--remote <url>` instead, skip the `gh repo create` block and
just wire the remote:

```bash
git remote add origin <url>
```

### 8c — Push (default unless `--no-push` was passed)

```bash
git push -u origin main
```

If push fails:
- **Rejected (non-fast-forward / fetch first)** — should not happen because the
  repo was just created and is empty. If it does, surface the error and stop;
  do NOT force-push.
- **Auth error** — tell the user to re-run `gh auth refresh -s repo` (or
  reauthenticate) and retry the push manually.
- **Network / hook error** — surface verbatim and stop. The local commit and
  the (possibly empty) remote are both intact; the user can retry.

### 8d — Print the published URL

If the push succeeded:

```bash
echo "Published: $(gh repo view --json url --jq .url)"
```

If `--no-create-repo` was used (init + commit only): print the manual next-step
instructions:

```
To publish this fork manually:
  cd <target>
  gh repo create harqis-work-fork-<slug> --private --source=. --remote=origin
  git push -u origin main
```

---

## Step 9 — Print the activation checklist

Re-run the stale-doc-refs sweep from Step 6 and capture any remaining hits — those
become a `Stale doc references` block in the checklist so the consuming team
knows what they may want to edit before publishing.

```bash
grep -rE "(\.claude/|\.openclaw/|workflows/(desktop|finance|hud|mobile|n8n|purchases|social))" \
  <target>/docs <target>/scripts <target>/agents <target>/README.md 2>/dev/null
```

Print this at the end, filled in with the actual values (drop the
`Published:` line if `--no-create-repo` or `--no-push` was used):

```
Fork created: <target>
Published:    <github_url>     (or "skipped — run `gh repo create …` to publish")

What's in it:
  ✓ apps/                          (all integrations preserved)
  ✓ agents/                        (framework + examples; private profiles stripped)
  ✓ workflows/.template/           (reference scaffold)
  ✓ workflows/config.py            (minimal — empty CONFIG_DICTIONARY)
  ✓ workflows/queues.py            (minimal — DEFAULT + ADHOC only)
  ✓ workflows/README.md            (rewritten for <BUSINESS_NAME>)
  ✓ README.md                      (rewritten for <BUSINESS_NAME>)
  ✓ Dockerfile, docker-compose.yml, scripts/, .github/
  ✓ apps_config.yaml.example       (no real credentials)
  ✓ .env/apps.env.example          (every secret redacted to <REPLACE_ME>)

What was removed:
  ✗ .claude/, .openclaw/           (local AI-tooling configs)
  ✗ logs/, data/                   (host-local runtime artifacts)
  ✗ workflows/{desktop,finance,hud,mobile,n8n,purchases,social}/
  ✗ Real secrets (.env/*.real, apps_config.yaml, OAuth JSON files)

Stale doc references (review before sharing):
  <list each grep hit on its own line, or "(none — clean)" if empty>

Next steps for the host operator:
  [ ] Clone: git clone <github_url> && cd harqis-work-fork-<slug>
  [ ] Copy apps_config.yaml.example → apps_config.yaml and fill in values
  [ ] Copy .env/apps.env.example → .env/apps.env and fill in <REPLACE_ME> entries
  [ ] Obtain fresh Google OAuth/service-account JSON files and place under .env/
  [ ] Run `pip install -r requirements.txt` inside a fresh .venv
  [ ] Run `/deploy-harqis host` (after installing Claude Code + skills in the fork) or
      `./scripts/sh/deploy.sh --role host` to bring the stack up
  [ ] Build the first workflow:
        cp -r workflows/.template workflows/<your_category>
        # then edit tasks_config.py and tasks/*.py
```

---

## Decision guide — common edge cases

| Situation | Action |
|---|---|
| User wants to keep a custom category (`n8n`) | Pass `--keep .template,n8n`; that category is copied verbatim |
| User is forking for an internal team (not a separate client) | Slug still applies — use the team name. The naming convention is non-negotiable. |
| Source repo has uncommitted changes | Warn and stop unless the user confirms "use working tree as-is" |
| Target dir already exists | Refuse — never overwrite. Ask the user to pick a different path or remove the existing dir. |
| `apps/` contains an integration the fork doesn't need | Default: keep it. Trimming `apps/` is a separate, opt-in step (`--strip apps/<name>`) — apps are cheap to leave in and expensive to re-introduce. |
| User wants the fork to track upstream | Step 8 already prints the `git remote add upstream …` snippet — no extra config needed. |
| Dry run | Print the full plan from Step 2 with no disk writes; exit before Step 3. |

---

## What NOT to do

- Do NOT copy `.claude/`, `.openclaw/`, `.venv/`, IDE folders, log files, or `data/` — these are always local.
- Do NOT carry forward real credentials (`apps_config.yaml`, `.env/*` non-`.example` files).
- Do NOT preserve the upstream's pre-built workflow categories unless `--keep` lists them. The fork's value is the clean slate.
- Do NOT modify the source repo. All operations are read-only against `<source>` and write-only into `<target>`.
- Do NOT make a fork's GitHub repo public unless the user explicitly passes `--visibility public`. Default is `private` — forks may carry client business context.
- Do NOT force-push (`--force` / `--force-with-lease`) under any circumstance. The first push to a freshly created repo should never need force.
- Do NOT add Claude Code config (`.claude/`) or AI agent state (`.openclaw/`) to the fork — the consuming team installs its own.
