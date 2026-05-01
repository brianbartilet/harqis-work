Fork the `harqis-work` repository into a fresh, business-/client-scoped baseline that another team can adopt as the starting point for their own automation host. The fork keeps the platform skeleton (`apps/`, `agents/`, `core` integration, deploy scripts) but strips local-only AI tooling and pre-built workflow categories so the consuming agents have a clean slate.

## Arguments

`$ARGUMENTS` format (parse left to right):

```
<business_or_client_name> [--target-dir <path>] [--remote <git_url>] [--description "<short blurb>"] [--keep <folder,folder,...>] [--strip <folder,folder,...>] [--no-git-init] [--dry-run]
```

| Token | Required | Description |
|---|---|---|
| `business_or_client_name` | Yes | Free-form name. Will be slugified to kebab-case for the repo / folder name (`Acme Logistics` → `acme-logistics`). The final repo name is always `harqis-work-fork-<slug>`. |
| `--target-dir <path>` | No | Where to create the fork on disk. Default: sibling of the source repo, i.e. `<parent_of_source>/harqis-work-fork-<slug>`. |
| `--remote <git_url>` | No | If provided, set as `origin` after `git init`. Otherwise leave the fork without a remote. |
| `--description "<text>"` | No | One-paragraph project description for the new README. If omitted, ask the user (Step 0). |
| `--keep <list>` | No | Comma-separated list of workflow categories to preserve from the source (default: only `.template` is kept). Example: `--keep .template,n8n`. |
| `--strip <list>` | No | Comma-separated list of additional top-level folders to remove from the fork (in addition to the always-stripped `.claude` and `.openclaw`). |
| `--no-git-init` | No | Skip `git init` and remote setup. Useful when the user wants to wire git themselves. |
| `--dry-run` | No | Print the plan (folders kept, folders stripped, files rewritten) without touching disk. |

The agent invoking this skill may also pass these decisions inline in a natural-language prompt; parse the prompt for them before falling back to `$ARGUMENTS`.

---

## Step 0 — Clarify inputs before touching disk

Confirm or ask for the following if not unambiguously provided:

1. **Business / client name** — required for slug + README context.
2. **Description** — what does this fork automate? Which industry or use case? (Used in the new README intro.)
3. **Target directory** — confirm the absolute path. Refuse to write into the source repo itself.
4. **Categories to keep** — by default ONLY `workflows/.template/` is kept. Any others (`n8n`, `social`, `desktop`, `hud`, `finance`, `mobile`, `purchases`) must be explicitly opted in via `--keep`.
5. **Remote** — does the user want `origin` set now, or wire it manually later?
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
- Any file under `.env/` that is NOT `*.example` → delete from the fork. Do not copy
  real secrets across.
- `apps_config.yaml` → if a `apps_config.yaml.example` already exists upstream, keep
  only that. Otherwise generate one by reading `apps_config.yaml` and replacing every
  string value with `"<REPLACE_ME>"` (preserving keys, comments, and structure).
  Save as `apps_config.yaml.example`. Then DELETE the original `apps_config.yaml` from
  the fork.
- Any file containing obvious credential patterns (`api_key:`, `secret:`, `password:`,
  `token:`, `Bearer`, `OAUTH_REFRESH_TOKEN=`) → flag to the user and ask before
  including.

Print a checklist of secrets the fork's host operator must supply before the platform
will boot.

---

## Step 8 — Initialize git in the fork

Skip if `--no-git-init` was passed.

```bash
cd <target>
git init -b main
git add -A
git commit -m "chore: scaffold harqis-work-fork-<slug> from upstream"
```

If `--remote` was provided:

```bash
git remote add origin <remote_url>
# do NOT push — leave that to the user
```

Always print the next-step instructions for pushing:

```
To publish this fork:
  cd <target>
  gh repo create harqis-work-fork-<slug> --private --source=. --remote=origin
  git push -u origin main
```

---

## Step 9 — Print the activation checklist

Print this at the end, filled in with the actual values:

```
Fork created: <target>

What's in it:
  ✓ apps/                          (all integrations preserved)
  ✓ agents/                        (framework + examples; private profiles stripped)
  ✓ workflows/.template/           (reference scaffold)
  ✓ workflows/config.py            (minimal — empty CONFIG_DICTIONARY)
  ✓ workflows/queues.py            (minimal — DEFAULT + ADHOC only)
  ✓ workflows/README.md            (rewritten for <BUSINESS_NAME>)
  ✓ README.md                      (rewritten for <BUSINESS_NAME>)
  ✓ Dockerfile, docker-compose.yml, scripts/, .github/

What was removed:
  ✗ .claude/, .openclaw/           (local AI-tooling configs)
  ✗ workflows/{desktop,finance,hud,mobile,n8n,purchases,social}/
  ✗ Real secrets (.env/*.real, apps_config.yaml)

Next steps for the host operator:
  [ ] Copy apps_config.yaml.example → apps_config.yaml and fill in values
  [ ] Create .env/apps.env from the upstream .env/apps.env.example template
  [ ] Run `pip install -r requirements.txt` inside a fresh .venv
  [ ] Run `/deploy-harqis host` (if Claude Code is installed in the fork) or
      `./scripts/sh/deploy.sh --role host` to bring the stack up
  [ ] Build the first workflow:
        cp -r workflows/.template workflows/<your_category>
        # then edit tasks_config.py and tasks/*.py
  [ ] git push -u origin main once the remote is configured
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
- Do NOT push to any remote. Print the push command and let the user execute.
- Do NOT add Claude Code config (`.claude/`) or AI agent state (`.openclaw/`) to the fork — the consuming team installs its own.
