# scripts/

Operational scripts for **harqis-work**, organised by purpose:

- **Deploy / runtime** scripts live at the **root of `scripts/`** — they bring
  the stack up, launch daemons, and sync config between machines.
- **Agent-support** scripts live under [`scripts/agents/`](#scriptsagents),
  grouped into **context subfolders** — `repo-quality/`, `learning/`,
  `testing/`, `diagnostics/`, `dumps/`, and `fleet/`. These are the agent-driven
  automation, the repo-quality / health / test tooling those agents drive, the
  HFL learning loop, and the worktree / window cleanup that keeps the fleet tidy.

## Root — deploy & runtime

| Path | Purpose |
|---|---|
| [`launch.py`](#launchpy) | Single-process launcher — runs one daemon in the foreground (`worker`, `scheduler`, `flower`, `frontend`, `mcp`, `kanban`, `trigger-hud-tasks`, `push-config`, `serve-config`). |
| [`deploy.py`](#deploypy) | Multi-daemon orchestrator — reads `machines.toml` from the repo root, brings the whole stack up/down, optionally registers OS auto-start units. |
| [`sync-to-host.ps1`](#sync-to-hostps1) | Push gitignored config (`.env/`, `frontend/.env`, `machines.local.toml`) to a remote checkout via `tar \| ssh`. Driven by the `[sync]` / `[ssh.*]` blocks in `machines.local.toml`. |
| [`../machines.toml`](#machinestoml) | Per-machine topology (role, queue list, disabled services). Lives at the repo root so per-machine `machines.local.toml` overrides sit next to it. Auto-detected from hostname. |
| [`tailscale/`](#tailscale) | Tailscale ACL policy. Unchanged. |

## `scripts/agents/`

Agent-support scripts are grouped into **context subfolders**. Each script
resolves the repo root via `Path(__file__).resolve().parents[3]` (three levels
up from `scripts/agents/<bucket>/`).

### `repo-quality/` - audits, scans, and agent-driven repo maintenance

| Path | Purpose |
|---|---|
| `manifesto_audit.py` | Validates the `'manifesto'` metadata block on every `workflows/*/tasks_config.py` beat entry. Non-zero exit on hard violations. |
| `manifesto_audit_agent.py` | Agent-delegated CODE+PARA compliance audit - runs locally (no API cost), writes findings + opens PR branches for significant issues. |
| `daily_improvement_scout.py` | Daily repo inspection — code-quality, config, workflow-health gaps. Shells out to `repo-quality/manifesto_audit.py`. |
| `weekly_claude_pr.py` | Weekly orchestration - runs the scout, delegates to the local agent client, opens a draft PR. |
| [`run_agent_prompt.py`](#run_agent_promptpy) | Agent-driven docs / code-smell regenerator. Invoked by the `agent-prompts.yml` CI workflow. |
| `migrate_to_core_scan.py` | Deterministic harvest-candidate scan for the `/migrate-to-core` skill — ranks `apps/` + `scripts/agents/` by genericness vs. coupling and maps what's already upstream in harqis-core. Writes `.harqis-data/migrate_to_core_scan.json`. |
| `migrate_to_core_agent.py` | Bi-monthly local agent runner for `/migrate-to-core` (first/third Saturdays). Runs `migrate_to_core_scan.py` first, then opens review-gated PR pairs. |
| [`sync_agent_skills.py`](#sync_agent_skillspy) | Mirrors canonical `.agents/skills` into generated `.claude/skills` for Claude compatibility. |

### `learning/` — agent reasoning capture + lessons loop

| Path | Purpose |
|---|---|
| `reasoning_capture.py` | Log structured task reasoning/decisions to the HFL corpus for later pattern detection. |
| `agent_learning_hook.py` | Load + apply learned agent lessons before a complex task (reads `~/.hermes/memory/agent_lessons.md`). |
| `lessons_extractor.py` | Weekly autonomous pattern detection over the last 7 days of HFL reasoning → writes insights to `agent_lessons.md`. |
| `weekly_lessons_extraction.py` | Cron wrapper that runs `lessons_extractor.py` and captures output for logging. |

### `testing/` — test execution + reporting

| Path | Purpose |
|---|---|
| `run_test_suite.py` | Exploratory / continuous test runner with coverage + perf tracking. |
| [`daily_test_farm_email.py`](#scriptsagentstestingdaily_test_farm_emailpy) | Daily BDD test farm sequence — refreshes `run_test_farm`, renders `logs/BDD-TEST-FARM.md`, emails the HTML report via `GOOGLE_GMAIL_SEND`, posts a Telegram notice. |
| `smoke-tests.sh` | Daily app smoke tests + Telegram summary. |

### `diagnostics/` — environment + credential health

| Path | Purpose |
|---|---|
| `check_env_health.py` | Environment / dependency / config diagnostics → JSON report. |
| [`check_plaud_token.py`](#check_plaud_tokenpy) | Read-only smoke check for the Plaud adapter — confirms `PLAUD_TOKEN` works before the nightly `ingest_plaud_activity` job. |
| [`ynab_unapproved_scan.py`](#ynab_unapproved_scanpy) | Weekly YNAB unapproved-transaction digest for the SGD/PHP Daily Bankroll budgets, limited to the last 30 days. Silent when there are no matches. |
| [`reauth_gmail_send.py`](#scriptsagentsdiagnosticsreauth_gmail_sendpy) | Interactive re-authorization of a HARQIS Google OAuth credential when its refresh token expires/revokes (`invalid_grant`). |

### `dumps/` — device dump ops

| Path | Purpose |
|---|---|
| [`pull_dumps.py`](#pull_dumpspy) | Manually pull Android/device dumps from `[dumps.pull_targets.*]` — date range, full sweep, `--by-file-day`, or `--missing-only` catch-up. Run on harqis-server. |
| [`run_dumps_summary_retro.py`](#run_dumps_summary_retropy) | Retro-summarize the dumps inbox for a range / month / day (the nightly `analyze_daily_dumps` only sees yesterday). Run on harqis-server. |

### `emulator/` — Android emulator ops

| Path | Purpose |
|---|---|
| [`run_emulator.py`](#run_emulatorpy) | Start/manage local Android emulators (start / stop / list / create) from a profile. Wraps `workflows.mobile.emulator.tasks`. Self-guards (exit 2) on a host without the SDK. |

### `fleet/` — agent worktree / window cleanup

| Path | Purpose |
|---|---|
| `cleanup-worktrees.sh` | Delete merged / idle git worktrees left by agent runs. |
| `close-completed-windows.sh` | Close idle Terminal windows post-deploy (macOS). Also called by `deploy.py`'s post-deploy hook. |
| `cleanup-loop.sh` | Runs `close-completed-windows.sh` every 30s (driven by the launchd job). |
| `install-cleanup-job.sh` | Install / uninstall the `cleanup-windows` launchd agent. |
| `launchd/` | macOS launchd plists for the agent cleanup job. |

Both Python entry points (`launch.py`, `deploy.py`) use `pathlib`, work on
Windows / macOS / Linux, and require Python 3.11+ (uses `tomllib` from stdlib).
Scripts under `agents/<bucket>/` resolve the repo root via
`Path(__file__).resolve().parents[3]` (three levels up from
`scripts/agents/<bucket>/`).


### `scripts/agents/repo-quality/sync_agent_skills.py`

Mirror the canonical source-controlled skills from `.agents/skills` into
`.claude/skills` for Claude compatibility. The generated `.claude/skills` tree is
ignored by git so skill bodies stay DRY in source control.

```bash
python scripts/agents/repo-quality/sync_agent_skills.py
python scripts/agents/repo-quality/sync_agent_skills.py --check
```

The `--check` mode validates every canonical `SKILL.md` has YAML frontmatter and
returns non-zero when the generated Claude copy is missing or stale.

---

### `scripts/agents/testing/daily_test_farm_email.py`

Refresh and email the rendered BDD test farm report:

```bash
python scripts/agents/testing/daily_test_farm_email.py
python scripts/agents/testing/daily_test_farm_email.py --dry-run --skip-generate
```

The script reuses `workflows.testing.tasks.test_farm.run_test_farm`, which invokes the
repo-local `/generate-gherkin-scenarios` skill through the local agent client Max
subscription. It renders `logs/BDD-TEST-FARM.md` to HTML, writes audit artifacts under
`logs/test_farm_email/`, sends via the `GOOGLE_GMAIL_SEND` app config, and sends a
Telegram completion notification via the `TELEGRAM` app config. Recipients and sender
are read from `TEST_FARM_EMAIL_TO` / `TEST_FARM_EMAIL_FROM` in `.env/apps.env` (or
`--to` / `--from-account`); they fall back to a generic placeholder when unset.
Use `--no-telegram` for email-only test runs.

### `scripts/agents/diagnostics/reauth_gmail_send.py`

Re-authorize a HARQIS Google OAuth credential when its refresh token has been
revoked or hard-expired (Google expires refresh tokens after 7 days while the
OAuth consent screen is in **Testing** publishing status). Symptom: a daily job
fails at the Gmail preflight with `invalid_grant: Token has been expired or
revoked`. **Run interactively** — it opens a browser for Google consent:

```bash
python scripts/agents/diagnostics/reauth_gmail_send.py                       # GOOGLE_GMAIL_SEND
python scripts/agents/diagnostics/reauth_gmail_send.py --config GOOGLE_GMAIL  # any google_apps cred
```

It reads the credential's `scopes` / `credentials` / `storage` from
`apps_config.yaml`, drops the stale token, runs the `InstalledAppFlow` local
server, and writes a fresh token to the credential's storage file under `.env/`.
The durable fix for recurrence is to set the OAuth consent screen to **In
production** in the Google Cloud Console so refresh tokens stop expiring weekly.

---

## `launch.py`

Loads `.env/apps.env`, sets `PYTHONPATH` + the standard `WORKFLOW_*` and
`PATH_APP_CONFIG_*` env vars, then `os.execvp`s into the actual command.
The result: the system service / Task Scheduler / launchd / systemd
manages the real Python process directly — no extra wrapper PID, no
PowerShell-vs-bash drift.

**Subcommands**

```bash
python scripts/launch.py worker [-q default,hud,tcg]
python scripts/launch.py scheduler
python scripts/launch.py flower
python scripts/launch.py frontend
python scripts/launch.py mcp
python scripts/launch.py kanban [-p agent:default] [--num-agents 1]

# Helpers
python scripts/launch.py trigger-hud-tasks [--queue hud]
python scripts/launch.py push-config  [--redis-url URL] [--key KEY]
python scripts/launch.py serve-config [--port 8765]    [--token TOKEN]
python scripts/launch.py print-env                                 # eval-able env
```

**Notes**

- `worker --queues` accepts a comma-separated list. Celery's `-Q` natively
  consumes multiple queues, so one process listens to all of them.
- `flower`, `trigger-hud-tasks` require `FLOWER_USER` and `FLOWER_PASSWORD`
  in `.env/apps.env`. The legacy hardcoded creds in `run_hud_tasks.bat`
  are gone — `launch.py trigger-hud-tasks` reads them from the env.
- `push-config` / `serve-config` run on the **host** machine. Remote workers
  set `CONFIG_SOURCE=redis|http` to consume the resolved config.

---

## `deploy.py`

Orchestrator. Reads `machines.toml`, decides which services to start
(based on `role` + `disable`), launches each as a detached background
process, tracks PIDs in `<repo>/.run/<service>.pid`, and logs to
`<repo>/logs/<service>.log`. On every deploy or `--down` it also sweeps
stray celery / launcher processes (matched by command-line needles
`run_workflows.py` and `core.apps.sprout.app`) so orphans from prior
runs — the kind that pile up extra console windows on Windows — are
killed before fresh daemons start.

**All commands**

```bash
# Lifecycle
python scripts/deploy.py                            # auto-detect from hostname → start everything
python scripts/deploy.py --down                     # stop services + sweep celery + docker compose down
python scripts/deploy.py --status                   # tabular status (PID + alive PIDs + log path)
python scripts/deploy.py --stop SERVICE             # stop one service by name (worker / scheduler / …)

# OS auto-start
python scripts/deploy.py --register                 # register at-logon auto-start, then start now
python scripts/deploy.py --unregister               # remove auto-start units

# Targeting / overrides
python scripts/deploy.py --machine NAME             # explicit profile lookup (skip hostname auto-detect)
python scripts/deploy.py --role host|node           # override role from machines.toml
python scripts/deploy.py -q QUEUES                  # comma-separated worker queues (override profile)
python scripts/deploy.py -p PROFILE                 # override Kanban profile filter (e.g. agent:code)
python scripts/deploy.py --num-agents N             # override Kanban concurrent agents

# Service filters (skip individual host daemons; can also live under `disable=` in machines.toml)
python scripts/deploy.py --no-frontend
python scripts/deploy.py --no-mcp
python scripts/deploy.py --no-kanban
python scripts/deploy.py --no-flower

# Visible scheduler/worker windows (live celery output)
python scripts/deploy.py --console                  # CREATE_NEW_CONSOLE for scheduler+worker only;
                                                    # closes-window-kills-daemon, no log file written

# Docker only (skip Python services)
python scripts/deploy.py --docker-only              # bring docker compose up/down without daemons
```

`--down`, `--status`, `--stop`, `--register`, `--unregister` are mutually
exclusive — pass at most one per invocation.

**Per-role behaviour**

| Role | Docker compose | scheduler | worker | frontend | mcp | kanban | flower |
|---|---|---|---|---|---|---|---|
| `host` | ✓ up/down | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `node` | — (broker is on host) | — | ✓ | — | — | ✓ | — |

Use `--no-frontend / --no-mcp / --no-kanban / --no-flower` to skip
individual host daemons, or list them under `disable` in `machines.toml`.

**Console mode (`--console`)**

`scheduler` and `worker` are flagged `console: True` in `SERVICES`. With
`--console`, those two daemons launch under `python.exe` (not
`pythonw.exe`) with `CREATE_NEW_CONSOLE` and **no stdout redirect** —
each gets its own visible window with live celery output. Other services
(`frontend`, `mcp`, `kanban`, `flower`) stay windowless even with the
flag set. Trade-offs:

- `logs/scheduler.log` / `logs/worker.log` are **not** written while in
  console mode (output goes only to the windows).
- Closing a console window terminates that daemon — no automatic respawn.
  Use `--down` for orderly shutdown.
- The harqis-core sprout patch (`d30527a` and later) auto-detects an
  attached console and inherits it for the forked celery child, so you
  see celery's actual log lines (not just the launcher's startup print).

**OS-native auto-start (`--register`)**

| OS | Mechanism | Unit / key location |
|---|---|---|
| macOS | launchd LaunchAgent | `~/Library/LaunchAgents/work.harqis.<svc>.plist` |
| Linux | systemd user unit | `~/.config/systemd/user/harqis-<svc>.service` |
| Windows | HKCU `…\CurrentVersion\Run` key | `HKCU:\Software\Microsoft\Windows\CurrentVersion\Run\work.harqis.<svc>` |

macOS launchd / Linux systemd units are `KeepAlive=true` /
`Restart=always` / restart on failure with backoff. Windows Run keys
fire **once at user logon** (no auto-restart on crash) — they were
chosen over Scheduled Tasks because Scheduled Tasks need admin even for
user-scope tasks on most installs. `--register` also starts the
services *now* (otherwise on Windows you'd have to log out/in to see
anything running). `--unregister` removes them cleanly.

---

## `machines.toml`

Lives at the **repo root** (alongside `requirements.txt`, `apps_config.yaml`,
etc.), not under `scripts/`. Declarative topology — each section describes
one machine; `[hostnames]` maps `socket.gethostname()` → machine name.
Example layout:

```toml
[default]                       # fallback when no [hostnames] entry matches
role = "host"
queues = ["default", "default_broadcast"]

[harqis-server]                 # always-on hub
role = "host"
queues = ["tcg", "agent", "host", "adhoc", "default_broadcast"]

[windows-work]
role = "host"
queues = ["default", "hud", "default_broadcast"]
disable = ["kanban"]

[vps-worker]
role = "node"
queues = ["agent", "worker", "default_broadcast"]
kanban_profile = "agent:code"

[hostnames]
"<bare-hostname>.local" = "harqis-server"
"<windows-hostname>"    = "windows-work"
```

> **Broadcast queues:** any name ending in `_broadcast` (e.g.
> `default_broadcast`, `hud_broadcast`) is a fanout exchange in
> `workflows/config.py`. Workers must include the broadcast queue in
> their `queues` list, otherwise the exchange is never declared on
> RabbitMQ and beat publishes fail with `404 NOT_FOUND - no exchange
> '<name>' in vhost '/'`. The broadcast subscriber on every machine
> above is what makes `git_pull_on_paths_broadcast` (and any future
> cluster-wide task) actually fan out.

Find a machine's hostname:
```bash
python -c "import socket; print(socket.gethostname())"
```

**Local override (`machines.local.toml`)** — gitignored. `deploy.py` merges
it on top of `machines.toml` at load time, so real hostname mappings or
per-machine tweaks stay off the repo. Copy `machines.local.toml.example`
to `machines.local.toml` and fill in:

```toml
[hostnames]
"<bare-hostname>.local"      = "harqis-server"
"<windows-hostname>"         = "windows-work"
"<vps-hostname>.tailnet.net" = "vps-worker"

# Override a field of an existing machine
[windows-work]
kanban_num_agents = 3
```

---

## Quick recipes

**Bring up your machine (anywhere):**
```bash
python scripts/deploy.py
# = auto-detect via machines.toml → start docker (if host) + all relevant daemons
```

**Stop everything:**
```bash
python scripts/deploy.py --down
```

**Run one worker by hand (no daemonization):**
```bash
python scripts/launch.py worker --queues hud,tcg
```

**See what's running:**
```bash
python scripts/deploy.py --status
```

**Auto-start at boot:**
```bash
python scripts/deploy.py --register     # one-time per machine
```

**Push resolved config to Redis (host) so remote workers pick it up:**
```bash
python scripts/launch.py push-config
```

---

## `sync-to-host.ps1`

Streams a configured set of gitignored files to a remote harqis-work checkout
over a single SSH connection (`tar -cf - … | ssh user@host "tar -xf - -C <path>"`),
so one password prompt covers the whole push. Targets and the file list live in
`machines.local.toml`:

```toml
[sync]
default_machine = "harqis-mac-mini"
items           = [".env", "frontend/.env", "machines.local.toml"]

[ssh.harqis-mac-mini]
user = "harqis-one"
host = "harqis-ones-mac-mini.local"
path = "~/GIT/harqis-work"
```

```powershell
powershell -NoProfile -File scripts/sync-to-host.ps1            # default_machine
powershell -NoProfile -File scripts/sync-to-host.ps1 -MachineKey <key>
powershell -NoProfile -File scripts/sync-to-host.ps1 --list      # show targets
```

The `/sync-host` skill wraps this for the current OS.

---

## `check_plaud_token.py`

Read-only smoke check for the Plaud acquisition adapter (`apps/plaud`). Prints
which backend is active (cloud API vs local export folder) and lists the
recordings it can see in a window — without transcribing, distilling, writing to
the HFL corpus/ES, or archiving. Use it to confirm `PLAUD_TOKEN` (or
`PLAUD_EXPORT_DIR`) works before the nightly `ingest_plaud_activity` job runs.

```bash
python scripts/agents/diagnostics/check_plaud_token.py                       # last 7 days
python scripts/agents/diagnostics/check_plaud_token.py --days 30
python scripts/agents/diagnostics/check_plaud_token.py --since 2026-06-01 --until 2026-06-09
```

Exit codes: `0` backend ready + listing ok · `1` acquisition errored (bad/expired
token, api.plaud.ai unreachable) · `2` no backend configured. Grab the token from
web.plaud.ai → DevTools Console `localStorage.getItem("tokenstr")` and set
`PLAUD_TOKEN` in `.env/apps.env`. The cloud path calls api.plaud.ai directly over
HTTP (no SDK package); non-US accounts set `PLAUD_API_BASE`.

---

## `ynab_unapproved_scan.py`

Weekly Hermes cron digest for unapproved YNAB transactions. It reads HARQIS YNAB
config through `apps/ynab`, scans only the last 30 days, and only these budgets:
`Daily Bankroll - SGD` and `Daily Bankroll - PHP`.

```bash
python scripts/agents/diagnostics/ynab_unapproved_scan.py
```

The script is designed for Hermes `no_agent` cron delivery: stdout is empty when
there are no matching unapproved transactions, so Telegram stays silent; stdout
contains a compact mobile digest when matches exist. No credentials are printed.

---

## `pull_dumps.py`

Manual companion to the nightly `pull_daily_dumps_from_remotes` task (the dumps
pull from `[dumps.pull_targets.*]` devices — typically Android over Termux SSHD).
Use it to **back-fill** a date range or do a **full sweep** of every file. Same
list→`ssh+tar`→extract path as the nightly job, so what lands in the inbox is
indistinguishable from a nightly pull and flows straight into `analyze_hfl_media`
and the memory MCP.

> ⚠️ Run this **on harqis-server** (the dumps host). The inbox is a *local* path
> there (`[dumps] harqis_server_inbox`); running it elsewhere extracts into a
> folder on the wrong machine.

```bash
python scripts/agents/dumps/pull_dumps.py                      # yesterday (same as nightly)
python scripts/agents/dumps/pull_dumps.py --days 7             # last 7 days, one folder per day
python scripts/agents/dumps/pull_dumps.py --since 2026-05-01 --until 2026-05-31
python scripts/agents/dumps/pull_dumps.py --full               # EVERY file → one folder/device
python scripts/agents/dumps/pull_dumps.py --full --by-file-day # sweep, but per-day folders
python scripts/agents/dumps/pull_dumps.py --since 2026-05-01 --until 2026-05-31 --by-file-day
python scripts/agents/dumps/pull_dumps.py --days 30 --single-folder   # range in one folder
python scripts/agents/dumps/pull_dumps.py --days 30 --missing-only --dry-run  # report the gaps
python scripts/agents/dumps/pull_dumps.py --days 30 --missing-only            # fill the gaps
python scripts/agents/dumps/pull_dumps.py --device pixel-7 --dry-run --days 3
```

Catch-up (`--missing-only`): for each day in the window, skip any device that
already has a non-empty `<device>-daily-dumps-<date>` folder on the server and
pull **only the gaps** — no wasted SSH cycles re-pulling days you already have.
Paired with `--dry-run` it's a pure *"what did I miss in the last N days?"*
report (absent **or** empty folders count as missing, so a failed/partial pull
gets retried). Per-day range only — not valid with `--full`, `--by-file-day`, or
`--single-folder`.

Layout:
- **range (default)** → `<device>-daily-dumps-YYYY-MM-DD` per day (back-fills the
  inbox exactly as if the nightly job had run each night; one `find`/`tar` cycle
  per day).
- **`--by-file-day`** → `<device>-daily-dumps-YYYY-MM-DD` per day too, but pulled
  in **one** SSH cycle per source root and bucketed on the server by each file's
  own mtime (`tar` preserves it). Composes with `--full` (whole device, date-split
  on the server) or a window. The efficient way to back-fill a wide range without
  N per-day round trips or remote `find -printf`. Same `-daily-dumps-` layout, so
  `analyze_daily_dumps` / HFL ingest pick it up.
- **`--single-folder`** → one `<device>-range-dumps-<from>_<to>` folder (one SSH
  cycle, no per-day split).
- **`--full`** → one `<device>-full-dumps-YYYY-MM-DD` folder (no date split — the
  remote `find` stays portable, so per-file dates aren't read for bucketing). Add
  `--by-file-day` to date-split the sweep instead.

`--dry-run` lists + counts (real remote `find`) but transfers nothing. With
`--by-file-day` the per-day split only materializes on a real run (mtimes are
read locally during extraction). Exit codes: `0` ok / dry-run · `1` a device
errored · `2` nothing configured.

---

## `run_dumps_summary_retro.py`

Retro companion to the nightly `analyze_daily_dumps` task, which only ever
summarizes *yesterday*. A missed daily run (host offline, broker outage, the
host-queue race) leaves a permanent gap; this script re-summarizes a date
**range**, a whole **month**, or a single **day** from the inbox's existing
`<machine>-daily-dumps-<date>` folders and pushes a per-day breakdown + grand
total to the HUD feed. Missed days surface as `0 machines (no dumps)`.

It prints the per-day summary as **Markdown** to stdout and APPENDS each day's
block to a single consolidated `daily-dumps.log` — to both the repo sink
(`DUMPS.summary.path` → `DUMPS_SUMMARY_PATH` → `<repo>/logs/dumps/`) and the
Drive-synced feed sink (`<feed-dir>/dumps/`). Re-running a date appends another
block (plain append). See `workflows/dumps/summary_store.py` and the
`/dumps-summary` skill. Pass `--no-md` to skip the log append and emit the
feed/ES summary only.

> ⚠️ Run this **on harqis-server** (the dumps host). The inbox is a *local* path
> there (`[dumps] harqis_server_inbox`). The task self-guards to harqis-server,
> so running it elsewhere is a no-op (exit `2`).

```bash
python scripts/agents/dumps/run_dumps_summary_retro.py                      # yesterday (same as nightly)
python scripts/agents/dumps/run_dumps_summary_retro.py --days 7             # last 7 full days
python scripts/agents/dumps/run_dumps_summary_retro.py --date 2026-06-12    # one specific day
python scripts/agents/dumps/run_dumps_summary_retro.py --start 2026-05-01 --end 2026-05-31
python scripts/agents/dumps/run_dumps_summary_retro.py --month 2026-05      # whole calendar month
```

Flags map 1:1 to the task kwargs; precedence is `date → start/end → month →
days`, and ranges are capped at yesterday (today's folder is still being filled
by the intra-day collect). A weekly Beat job
(`run-job--analyze_dumps_weekly_catchup`, Mon 01:30) runs the `--days 7`
equivalent automatically. Exit codes: `0` ok · `1` error (inbox/config) · `2`
skipped (ran off the hub).

---

## `run_emulator.py`

Start and manage local Android emulators from the shell. A thin CLI over
`workflows.mobile.emulator.tasks.manage` (which wraps `apps.android_emulator`),
so the command line, the MCP tools, and the Celery tasks share one
implementation. Runs synchronously; self-guards on a host without the SDK
(exit `2`).

```bash
python scripts/agents/emulator/run_emulator.py start                          # default profile, wait for boot
python scripts/agents/emulator/run_emulator.py start --profile pixel7-test --port 5556 --no-wait
python scripts/agents/emulator/run_emulator.py start --no-headless            # show the GUI window
python scripts/agents/emulator/run_emulator.py list
python scripts/agents/emulator/run_emulator.py stop emulator-5554
python scripts/agents/emulator/run_emulator.py create --profile pixel7-test
```

Profiles live in `apps_config.yaml` under `ANDROID_EMULATOR.profiles`; the SDK
location is resolved per-host from `ANDROID_SDK_ROOT`/`ANDROID_HOME`. Exit codes:
`0` ok · `1` error · `2` skipped (no SDK on this host).

---

## `run_agent_prompt.py`

`scripts/agents/repo-quality/run_agent_prompt.py` - agent-powered regenerator for top-level
docs.

```bash
python scripts/agents/repo-quality/run_agent_prompt.py --agent docs          # regenerate README.md
python scripts/agents/repo-quality/run_agent_prompt.py --agent code_smells   # regenerate CODE_SMELLS.md
python scripts/agents/repo-quality/run_agent_prompt.py --agent both
```

---

## `tailscale/`

Unchanged. See `tailscale/acl-policy.hujson` (gitignored). Apply via:
```bash
tailscale acls set --file scripts/tailscale/acl-policy.hujson
```

Tag model and rules — see the file's header comment, or the previous
revision of this README in git history.
