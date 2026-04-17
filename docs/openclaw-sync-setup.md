# OpenClaw Sync Setup - Integration with HARQIS-Work

How to set up OpenClaw Gateway syncing across multiple machines in conjunction with HARQIS-Work.

---

## Overview

Your setup now consists of **two separate repositories:**

### 1. **harqis-work** (This Repo)
- Application code, workflows, integrations
- OANDA, TCG MP, Gmail, Discord, Telegram, etc.
- Business logic and automation tasks
- `.env/apps.env` with app credentials
- `apps_config.yaml` with integration configs

### 2. **harqis-openclaw-sync** (New Repo)
- OpenClaw Gateway configuration
- Agent workspace (MEMORY.md, guidelines, notes)
- Agent state and sessions
- Auto-synced every 30 minutes across machines

**They work together seamlessly:**
- OpenClaw agents run on any machine with the sync repo
- Agents can access harqis-work apps/integrations
- Changes to either repo persist independently

---

## Quick Setup

### Step 1: Clone the Sync Repo

```bash
cd C:\Users\brian\GIT
git clone https://github.com/yourusername/harqis-openclaw-sync.git
cd harqis-openclaw-sync
```

### Step 2: Install Auto-Sync Task

```powershell
powershell -ExecutionPolicy Bypass -File scripts/install-scheduled-task.ps1
```

This installs a Windows scheduled task that pulls changes every 30 minutes.

### Step 3: Start OpenClaw Gateway

```powershell
./scripts/openclaw-with-sync.ps1 gateway
```

This automatically:
- Sets `OPENCLAW_CONFIG_PATH` to `./openclaw.json`
- Sets `OPENCLAW_STATE_DIR` to `./state`
- Starts the gateway with sync-enabled paths

---

## File Structure

After setup, your directory structure is:

```
C:\Users\brian\GIT\
├── harqis-work/                      ← Your app code (this repo)
│   ├── apps/                         ← Integrations (OANDA, TCG, Gmail, etc.)
│   ├── workflows/                    ← Celery tasks
│   ├── apps_config.yaml              ← Integration configs
│   └── .env/apps.env                 ← App credentials
│
└── harqis-openclaw-sync/             ← OpenClaw config (synced repo)
    ├── openclaw.json                 ← Gateway config
    ├── workspace/                    ← Agent workspace
    │   ├── MEMORY.md                 ← Long-term memory
    │   ├── AGENTS.md                 ← Agent guidelines
    │   └── memory/                   ← Daily notes
    ├── state/                        ← Runtime state
    ├── scripts/                      ← Sync automation
    └── README.md                     ← See for detailed docs
```

---

## How the Integration Works

### When OpenClaw Runs Agent Tasks

1. **OpenClaw loads config** from `harqis-openclaw-sync/openclaw.json`
2. **Agent reads guidelines** from `harqis-openclaw-sync/workspace/AGENTS.md`
3. **Agent reads memory** from `harqis-openclaw-sync/workspace/MEMORY.md`
4. **Agent can execute tasks** using harqis-work integrations:
   - Query OANDA via `apps/oanda/`
   - Get TCG orders via `apps/tcg_mp/`
   - Send emails via `apps/google_apps/`
   - Check calendars via `apps/google_apps/`
   - Control Telegram via `apps/telegram/`
   - etc.

### Environment Variables

When starting OpenClaw with the sync wrapper, these are set:

```powershell
$env:OPENCLAW_CONFIG_PATH = "C:\Users\brian\GIT\harqis-openclaw-sync\openclaw.json"
$env:OPENCLAW_STATE_DIR = "C:\Users\brian\GIT\harqis-openclaw-sync\state"

# Also available (from your shell):
$env:PYTHONPATH = "C:\Users\brian\GIT\harqis-work"  # For app access
```

The agent can then import harqis-work apps:
```python
from apps.tcg_mp.references.web.api.order import ApiServiceTcgMpOrder
```

---

## Typical Workflow

### Development Machine

```bash
# Terminal 1: Start HARQIS-Work services
cd harqis-work
python -m celery -A workflows.config worker -l info

# Terminal 2: Start OpenClaw Gateway (with sync)
cd harqis-openclaw-sync
./scripts/openclaw-with-sync.ps1 gateway

# Now:
# - OpenClaw agents can call harqis-work tasks
# - Changes to workspace/MEMORY.md auto-sync every 30 min
# - Config changes push to remote after agent work
```

### On a Production VPS

```bash
# Clone both repos
git clone https://github.com/yourusername/harqis-work.git
git clone https://github.com/yourusername/harqis-openclaw-sync.git

# Set up OpenClaw with sync-enabled paths
cd harqis-openclaw-sync
chmod +x scripts/sync-pull.ps1  # On Linux/Mac
# Set env vars, then:
openclaw gateway

# Set up HARQIS-Work separately
cd harqis-work
python -m celery -A workflows.config worker -l info &
```

Both run independently but share the same agent runtime.

---

## Syncing Configuration

### Auto-Pull (Every 30 Minutes)

The Windows scheduled task:
- Fetches latest from `harqis-openclaw-sync` repo
- Rebases local changes
- Reloads gateway config

**You don't need to do anything** — it happens automatically.

### Manual Push (After Agent Work)

After your agent completes important work:

```bash
cd harqis-openclaw-sync
./scripts/sync-push.ps1
```

This commits and pushes:
- Changes to `workspace/MEMORY.md`
- Updates to `openclaw.json`
- New session state in `state/agents/`

### Multi-Machine Sync

On **another machine** (laptop, VPS, etc.):

```bash
# Clone the sync repo
git clone https://github.com/yourusername/harqis-openclaw-sync.git

# Install sync task
powershell -File scripts/install-scheduled-task.ps1

# Start gateway
./scripts/openclaw-with-sync.ps1 gateway

# Now both machines sync every 30 minutes!
```

---

## Git Workflows

### Separate Commits

**harqis-work** changes (app code, workflows):
```bash
cd harqis-work
git add apps/tcg_mp/...
git commit -m "feat: add new TCG order feature"
git push origin main
```

**harqis-openclaw-sync** changes (config, memory):
```bash
cd harqis-openclaw-sync
git add workspace/MEMORY.md
git commit -m "sync: update long-term memory"
git push origin main
```

Both repos maintain independent histories.

### Merging Changes from Remote

The sync scripts handle this automatically, but you can also:

```bash
cd harqis-openclaw-sync

# Fetch latest
git fetch origin

# Rebase local changes on top
git rebase origin/main

# Or merge if rebase conflicts
git merge origin/main
```

---

## Updating Documentation in harqis-work

When you update OpenClaw setup or sync behavior:

1. **Update docs/thesis/openclaw-multi-machine-sync.md** — Architecture details
2. **Update docs/openclaw-sync-setup.md** — This file — Integration with harqis-work
3. **Commit to harqis-work repo:**
   ```bash
   cd harqis-work
   git add docs/
   git commit -m "docs: update OpenClaw sync documentation"
   git push origin main
   ```

The OpenClaw config and workspace are in `harqis-openclaw-sync`, so reference that repo in docs.

---

## Common Tasks

### Check OpenClaw Sync Status

```bash
cd harqis-openclaw-sync

# See last changes
git log --oneline -10

# Check if anything needs pushing
git status

# View pull history
Get-Content logs/sync-pull.log -Tail 50
```

### Update Agent Memory (Persists Across Machines)

Edit `harqis-openclaw-sync/workspace/MEMORY.md`:

```bash
cd harqis-openclaw-sync
vim workspace/MEMORY.md
./scripts/sync-push.ps1  # Push changes
```

Changes sync to all machines within 30 minutes.

### Fix Configuration on One Machine, Sync to All

```bash
# Fix something in openclaw.json
cd harqis-openclaw-sync
vim openclaw.json

# Push the fix
./scripts/sync-push.ps1

# Other machines pull automatically in 30 min
# Or manually:
git pull --rebase origin main
openclaw gateway restart
```

### View What Changed Since Last Sync

```bash
cd harqis-openclaw-sync
git diff HEAD~5  # Last 5 commits
git diff origin/main  # What's different from remote
```

---

## Credentials & Secrets

### Safe to Commit to harqis-openclaw-sync
- ✅ `openclaw.json` — Gateway config (review for embedded secrets)
- ✅ `workspace/MEMORY.md` — Agent memory (no credentials)
- ✅ `workspace/AGENTS.md` — Guidelines
- ✅ `state/agents/` — Session state

### NOT Safe - Keep Local Only
- ❌ `.env` files with secrets
- ❌ `credentials/` folder with tokens
- ❌ `secrets.json`

**Before pushing**, verify no secrets in git:
```bash
git diff origin/main | grep -i "token\|key\|secret\|password"
```

---

## Troubleshooting

### Agent Can't Access harqis-work Apps

**Problem:** Agent tries to import `apps.tcg_mp` but gets `ModuleNotFoundError`

**Solution:**
1. Verify `PYTHONPATH` includes harqis-work:
   ```bash
   echo $PYTHONPATH
   # Should include C:\Users\brian\GIT\harqis-work
   ```

2. Update the wrapper script if needed:
   ```powershell
   # In openclaw-with-sync.ps1, add:
   $env:PYTHONPATH = "C:\Users\brian\GIT\harqis-work"
   ```

3. Restart gateway:
   ```bash
   ./scripts/openclaw-with-sync.ps1 gateway
   ```

### Changes Not Syncing Between Machines

**Problem:** Edit on Machine A, but Machine B doesn't see changes after 30 minutes

**Steps:**
1. Manually push on Machine A:
   ```bash
   cd harqis-openclaw-sync
   ./scripts/sync-push.ps1
   ```

2. Check git log:
   ```bash
   git log --oneline -5
   ```

3. On Machine B, manually pull:
   ```bash
   git fetch origin
   git pull --rebase origin main
   ```

### Merge Conflict During Sync Pull

**Problem:** `git rebase failed` in logs

**Steps:**
```bash
cd harqis-openclaw-sync
git status                                # See conflicts
git checkout --theirs openclaw.json       # Keep remote version
git add openclaw.json
git rebase --continue
```

---

## References

- **[harqis-openclaw-sync README](../harqis-openclaw-sync/README.md)** — Main sync repo documentation
- **[harqis-openclaw-sync SETUP.md](../harqis-openclaw-sync/SETUP.md)** — Detailed setup guide
- **[openclaw-multi-machine-sync.md](./thesis/openclaw-multi-machine-sync.md)** — Architecture & security details

---

## Summary

Your setup is now:

1. **harqis-work** — Code + integrations (manual git commits)
2. **harqis-openclaw-sync** — Config + workspace (auto-synced every 30 min)
3. Both work together seamlessly

**To use it:**
```bash
cd harqis-openclaw-sync
./scripts/openclaw-with-sync.ps1 gateway
```

**That's it!** Everything else syncs automatically.

---

**Status:** ✅ Production Ready  
**Last Updated:** 2026-04-17  
**Sync Interval:** Every 30 minutes
