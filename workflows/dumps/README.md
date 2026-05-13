# Dumps Workflow

## Description

Daily collection of newly-created or modified files from every Tailscale-connected device into a single inbox on `harqis-server`. Each device's files land under a per-device, per-day directory with the source folder structure preserved, so a downstream agent (TBD) can analyze them.

Two complementary code paths:

| Path | Runs on | Reaches | Mechanism |
|---|---|---|---|
| `broadcast_collect_daily_dumps` | every Celery worker subscribed to `default_broadcast` | itself | walks local paths, builds tar in Python, streams to harqis-server via `ssh + tar -xf -` (or `shutil.copy2` if the worker IS harqis-server) |
| `pull_daily_dumps_from_remotes` | harqis-server only (queue=`host`) | every device under `[dumps.pull_targets.*]` (Android via Termux SSHD, etc.) | SSH + `find -newermt` to list, then `ssh + tar -cf -` piped into local extraction |
| `analyze_daily_dumps` | harqis-server only (queue=`host`) | the inbox | walks the day's machine folders, then pushes a per-machine summary line to the HUD feed via `@feed()`. The kanban / Trello hand-off marker is preserved in `tasks/analyze.py` as `# FUTURE: kanban agent hand-off` for a later enhancement. |

## Schedule

| Task | Time (local) | Queue | Expires |
|---|---|---|---|
| `broadcast_collect_daily_dumps` | 00:00 | `default_broadcast` (fanout) | 8 h |
| `pull_daily_dumps_from_remotes` | 00:05 | `host` | 8 h |
| `analyze_daily_dumps` | 01:00 | `host` | 8 h |

The 5-minute stagger lets most pushes from worker-attached devices land before the host-side pull runs (so the analyze task at 01:00 sees a complete picture). The 8-hour expiry drops anything stuck in the queue before the next day's run, so backlogs can't pile up.

## Directory layout produced

```
<harqis_server_inbox>/
├── windows-work-all-daily-dumps-2026-05-09/
│   ├── Screenshots 1/
│   │   └── 2026/05/Screenshot_001.png
│   └── daily/
│       └── 2026-05-09.log
├── harqis-server-daily-dumps-2026-05-09/
│   └── Pictures/
│       └── camera-roll/IMG_0001.jpeg
└── pixel-7-daily-dumps-2026-05-09/
    ├── Camera/
    │   └── PXL_20260509_120000.jpg
    └── Screenshots/
        └── Screenshot_2026-05-09.png
```

Naming rule: `<machine-name>-daily-dumps-<YYYY-MM-DD>/<source-folder-basename>/<file-relative-to-source-root>`. The machine name comes from the `[<name>]` block in `machines.toml` (resolved via `[hostnames]`). The `<source-folder-basename>` is the leaf name of each configured path.

## Configuration

All real values live in `machines.local.toml` (gitignored). `machines.toml` carries only the schema docs.

### Required for any push to work

```toml
# machines.local.toml
[dumps]
harqis_server_ssh   = "harqis-one@harqis-mac-mini.tailnet.ts.net"
harqis_server_inbox = "/Users/harqis-one/dumps"
```

### Per-device push config (celery-attached machines)

```toml
[windows-work-all.daily_dumps]
paths = [
    "C:/Users/brian/OneDrive/Pictures/Screenshots 1",
    "C:/Users/brian/GIT/harqis-work/logs/daily",
]

[harqis-server.daily_dumps]
paths = [
    "/Users/harqis-one/Pictures/Daily",
]
```

If a celery-attached machine has **no** `[<machine>.daily_dumps]` block (or empty `paths`), the broadcast task short-circuits with a "no paths configured" log and exits cleanly.

### Per-device pull config (non-celery devices, e.g. Android)

```toml
[dumps.pull_targets.pixel-7]
ssh   = "u0_a200@pixel-7.tailnet.ts.net"
port  = 8022                  # Termux's default SSHD port
paths = [
    "/storage/emulated/0/DCIM/Camera",
    "/storage/emulated/0/Pictures/Screenshots",
]
```

## How to add a new device

| If the device is... | Do |
|---|---|
| A Mac/Linux/Windows already running a harqis-work celery worker subscribed to `default_broadcast` | Add `[<machine>.daily_dumps] paths = [...]` to `machines.local.toml`. No code change. Restart that worker. |
| An Android phone/tablet | 1. Install Termux + `pkg install openssh`; start `sshd`. 2. Join the device to your Tailscale tailnet. 3. Add `[dumps.pull_targets.<name>]` to `machines.local.toml`. 4. Make sure harqis-server can `ssh -p 8022 user@<name>.tailnet.ts.net` without a password (key-based auth — `ssh-copy-id` from harqis-server). |
| A device that runs a celery worker but isn't on `default_broadcast` | Add `default_broadcast` to that machine's `queues = [...]` list in `machines.toml` and redeploy. |

## File filtering rule

A file qualifies for inclusion if:
- It's a regular file (not a symlink-traversal escape, not a directory).
- Its `mtime` is in `[yesterday 00:00:00, today 00:00:00)` in the **source machine's** local timezone.
- The walking process can `stat()` it (permission errors silently skip).

`mtime` covers both creation and modification on Windows (NTFS) and modification on POSIX. For most "things I generated yesterday" workflows that's the right granularity. If you need true creation-time filtering on POSIX (`birthtime`), the helper in `files.py` can be extended without touching the tasks.

## Failure modes

| Symptom | Likely cause | Fix |
|---|---|---|
| `[dumps] harqis_server_ssh / harqis_server_inbox missing` | `machines.local.toml` doesn't have a `[dumps]` block | Add the block (see above). |
| Broadcast task logs `no paths configured` | `[<machine>.daily_dumps] paths` empty or missing | Add per-machine paths. |
| `ssh tar-extract failed` | harqis-server unreachable / wrong inbox path / no key auth | `ssh harqis-one@harqis-mac-mini.tailnet.ts.net 'ls ~/dumps'` to verify connectivity. |
| Pull task logs `find failed on <device>` | Termux SSHD off / different port / Tailscale not connected on phone | `ssh -p 8022 user@phone.tailnet.ts.net 'echo ok'` from harqis-server. |
| Files arrive but in the wrong machine folder | `[hostnames]` mapping in `machines.local.toml` doesn't list this machine's `socket.gethostname()` | Add it: `"<this-hostname>" = "<machine-name>"`. |

## What's intentionally NOT here yet

- **A kanban / Trello hand-off agent** — `analyze_daily_dumps` now pushes a per-machine summary to the HUD feed (the manifesto-required Express path is in place). A richer Trello-card-per-machine flow is still optional; the marker in `tasks/analyze.py` reads `# FUTURE: kanban agent hand-off` so the enhancement is greppable.
- **Compression** — files ship uncompressed inside the tar stream. Add `mode="w|gz"` in `transport.py::ship_via_ssh_tar` if bandwidth becomes the bottleneck.
- **Per-source overrides for the destination folder name** — currently the source root's basename is used verbatim. If two paths on the same machine have the same basename, they'll collide. Easy to add a `source_aliases = { "/p1" = "logs", "/p2" = "screenshots" }` map under `[<machine>.daily_dumps]` if needed.
- **A new `dumps_broadcast` queue** — we reuse `default_broadcast` to keep onboarding zero-config (every machine that subscribes to default_broadcast gets dumps automatically). Switch to a dedicated queue if dumps traffic becomes noisy on the broadcast channel.

## Manifesto alignment

See [`docs/MANIFESTO.md`](../../docs/MANIFESTO.md) and [`docs/thesis/MANIFESTO-REPO-UPDATES.md`](../../docs/thesis/MANIFESTO-REPO-UPDATES.md). The same metadata is persisted on each beat entry's `'manifesto'` key in `tasks_config.py`.

| Task | code_role | para_bucket | express_target | review_artifact | hfl_signal |
| --- | --- | --- | --- | --- | --- |
| `broadcast_collect_daily_dumps` | capture | area | `file:dump_inbox` | `es_log` | `True` |
| `pull_daily_dumps_from_remotes` | capture | area | `file:dump_inbox` | `es_log` | `True` |
| `analyze_daily_dumps` | distill+express | area | `hud_feed` | `es_log+hud_feed` | `True` |
