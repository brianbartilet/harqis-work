# OpenClaw Sync — Multi-Machine Setup

How OpenClaw Gateway state, config, and agent memory are kept in sync across multiple machines in conjunction with HARQIS-Work.

---

## Architecture

**Gateway (server / Mac Mini):**
- Runs the OpenClaw Gateway process
- Stores config, state, and sessions in `OPENCLAW_STATE_DIR` and `OPENCLAW_CONFIG_PATH`
- Client devices (phones, laptops) connect to it via Tailscale

**Nodes (client devices):**
- Android/iOS companion apps paired to the Gateway
- Send commands, receive responses
- No persistent agent runtime — the Gateway handles that

**Without sync:**
- All memory and context lives only on the Gateway machine
- Losing the VPS / wiping the machine loses everything
- Multiple Gateway instances have isolated, non-shared state

---

## What to Sync

| Item | Location | Sensitivity |
|------|----------|-------------|
| Config | `openclaw.json` | High (may contain tokens) |
| State / Sessions | `state/` | Medium |
| Agent workspace | `workspace/MEMORY.md`, `AGENTS.md` | Low |
| Auth tokens / secrets | `secrets/` | **Critical — never commit plain** |

---

## Implemented: Git Sync (`harqis-openclaw-sync`)

The live implementation uses a dedicated **private git repo** (`harqis-openclaw-sync`) that auto-syncs every 30 minutes. Secrets are kept out of the repo; only config and workspace files are committed.

### Repository Structure

```
C:\Users\brian\GIT\
├── harqis-work/                      ← App code (this repo)
│   ├── apps/                         ← Integrations (OANDA, TCG, Gmail, etc.)
│   ├── workflows/                    ← Celery tasks
│   ├── apps_config.yaml
│   └── .env/apps.env                 ← App credentials (never synced)
│
└── harqis-openclaw-sync/             ← OpenClaw config (synced repo)
    ├── openclaw.json                 ← Gateway config
    ├── workspace/
    │   ├── MEMORY.md                 ← Long-term agent memory
    │   ├── AGENTS.md                 ← Agent guidelines
    │   └── memory/                   ← Daily notes
    ├── state/                        ← Runtime state
    ├── scripts/                      ← Sync automation
    └── README.md
```

### Quick Setup on a New Machine

**Step 1 — Clone the sync repo:**
```bash
cd C:\Users\brian\GIT
git clone https://github.com/yourusername/harqis-openclaw-sync.git
cd harqis-openclaw-sync
```

**Step 2 — Install auto-sync task (Windows):**
```powershell
powershell -ExecutionPolicy Bypass -File scripts/install-scheduled-task.ps1
```
This installs a scheduled task that pulls changes every 30 minutes.

**Step 3 — Start OpenClaw Gateway:**
```powershell
./scripts/openclaw-with-sync.ps1 gateway
```
This sets `OPENCLAW_CONFIG_PATH` and `OPENCLAW_STATE_DIR` to the repo paths and starts the gateway.

### How It Works

1. OpenClaw loads config from `harqis-openclaw-sync/openclaw.json`
2. Agent reads guidelines from `workspace/AGENTS.md` and memory from `workspace/MEMORY.md`
3. Agent executes tasks using harqis-work integrations via `PYTHONPATH`:
   ```powershell
   $env:OPENCLAW_CONFIG_PATH = "C:\Users\brian\GIT\harqis-openclaw-sync\openclaw.json"
   $env:OPENCLAW_STATE_DIR   = "C:\Users\brian\GIT\harqis-openclaw-sync\state"
   $env:PYTHONPATH           = "C:\Users\brian\GIT\harqis-work"
   ```
4. The scheduled task pulls the repo every 30 minutes; changes on any machine propagate automatically

### Typical Workflow

```bash
# Start HARQIS-Work services
cd harqis-work
python -m celery -A workflows.config worker -l info

# Start OpenClaw Gateway (separate terminal)
cd harqis-openclaw-sync
./scripts/openclaw-with-sync.ps1 gateway
```

On a Linux/Mac VPS:
```bash
git clone https://github.com/yourusername/harqis-work.git
git clone https://github.com/yourusername/harqis-openclaw-sync.git

cd harqis-openclaw-sync
openclaw gateway   # with env vars set

cd harqis-work
python -m celery -A workflows.config worker -l info &
```

### Sync Operations

**Auto-pull (every 30 min)** — handled by the scheduled task, no manual action needed.

**Manual push after agent work:**
```bash
cd harqis-openclaw-sync
./scripts/sync-push.ps1
```
Commits and pushes `workspace/MEMORY.md`, `openclaw.json`, and `state/agents/`.

**Manual pull on any machine:**
```bash
cd harqis-openclaw-sync
git fetch origin
git rebase origin/main
```

### Git Workflow

Each repo commits independently:
```bash
# App code changes
cd harqis-work
git add apps/tcg_mp/...
git commit -m "feat: add new TCG order feature"
git push origin main

# Agent config / memory changes
cd harqis-openclaw-sync
git add workspace/MEMORY.md openclaw.json
git commit -m "sync: update long-term memory"
git push origin main
```

### Credentials & Secrets

| File | Safe to commit |
|------|---------------|
| `openclaw.json` | ✅ Yes — review for embedded secrets first |
| `workspace/MEMORY.md` | ✅ Yes |
| `workspace/AGENTS.md` | ✅ Yes |
| `state/agents/` | ✅ Yes |
| `.env` files | ❌ No |
| `secrets.json` / tokens | ❌ No |

Before pushing, scan for secrets:
```bash
git diff origin/main | grep -i "token\|key\|secret\|password"
```

### Common Tasks

**Check sync status:**
```bash
cd harqis-openclaw-sync
git log --oneline -10
git status
Get-Content logs/sync-pull.log -Tail 50
```

**Update agent memory (persists across machines):**
```bash
cd harqis-openclaw-sync
vim workspace/MEMORY.md
./scripts/sync-push.ps1
```

**Fix config on one machine and push to all:**
```bash
cd harqis-openclaw-sync
vim openclaw.json
./scripts/sync-push.ps1
# Other machines pull in 30 min, or manually:
git pull --rebase origin main && openclaw gateway restart
```

---

## Other Possible Implementations

The git sync above is intentionally lightweight. The options below offer stronger encryption, real-time sync, or cloud backup depending on requirements.

---

### Option A: Encrypted Git + git-crypt

Extends the git approach by transparently encrypting sensitive files at rest using `git-crypt`. Secrets and config are stored in the same repo — git-crypt handles decryption on `git checkout`.

**When to use:** Secrets need to live in git alongside config.

**Setup:**
```bash
brew install git-crypt       # macOS
sudo apt-get install git-crypt  # Ubuntu

cd openclaw-config
git-crypt init
git-crypt add-gpg-user [your-gpg-key-id]
# or export a symmetric key:
git-crypt export-key ~/.git-crypt/key
```

Configure `.gitattributes` to mark files for encryption:
```
secrets/** filter=git-crypt diff=git-crypt
openclaw.json filter=git-crypt diff=git-crypt
memory/** filter=git-crypt diff=git-crypt
!.gitignore
```

**Restore on a new machine:**
```bash
git clone https://github.com/yourusername/openclaw-config
cd openclaw-config
git-crypt unlock /path/to/key
```

**Pros:** version history, rollback, encrypted at rest, free
**Cons:** GPG/age key management overhead, no real-time sync

---

### Option B: S3 + Server-Side Encryption

Store the full `.openclaw` directory on AWS S3 with AES-256 server-side encryption. Good as a cloud-hosted backup layer.

**When to use:** Easy restore on any machine with AWS credentials; cloud backup alongside git.

```bash
# Create bucket with encryption
aws s3 mb s3://my-openclaw-backup --region us-east-1
aws s3api put-bucket-encryption \
  --bucket my-openclaw-backup \
  --server-side-encryption-configuration \
  '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'

# Sync
aws s3 sync ~/.openclaw s3://my-openclaw-backup/ --sse AES256 --exclude ".git/*"

# Restore on new machine
aws s3 sync s3://my-openclaw-backup/ ~/.openclaw
openclaw gateway restart
```

Automate with cron:
```bash
0 * * * * aws s3 sync ~/.openclaw s3://my-openclaw-backup/ --sse AES256 --exclude ".git/*"
```

**Pros:** cloud backup, highly available, easy restore
**Cons:** AWS cost, requires IAM credentials, less transparent than git

---

### Option C: Syncthing (Peer-to-Peer Real-Time)

Syncthing keeps folders in sync across devices in real-time, peer-to-peer with no central server. No internet required if machines are on the same network or Tailscale.

**When to use:** Real-time sync across devices is more important than version history.

```bash
brew install syncthing     # macOS
sudo apt-get install syncthing  # Ubuntu

syncthing --home=~/.syncthing
# Web UI: http://localhost:8384
# Add folder ~/.openclaw, pair with remote device
```

**Pros:** real-time, free, no external servers, works over Tailscale
**Cons:** encryption must be handled separately, all devices must run Syncthing, more complex to set up

---

### Option D: Restic (Encrypted Incremental Backups)

Restic creates encrypted, deduplicated backups to local disk, S3, B2, or any SFTP target. Best for backup/restore, not continuous sync.

**When to use:** Scheduled snapshots with easy point-in-time restore; not for live sync.

```bash
brew install restic

# Initialize repo (local)
restic -r /mnt/backup init

# Backup
restic -r /mnt/backup backup ~/.openclaw

# Restore latest
restic -r /mnt/backup restore latest --target /

# Automate
0 * * * * restic -r /mnt/backup backup ~/.openclaw
```

**Pros:** built-in AES-256 encryption, efficient incremental backups, works with many storage backends
**Cons:** better for backups than live sync, more operational overhead

---

### Comparison

| Option | Ease | Security | Real-time | Cost | Best For |
|--------|------|----------|-----------|------|----------|
| **Git sync** *(implemented)* | Easy | Medium | ✗ (30 min) | Free | Current setup |
| **Git + git-crypt** | Medium | High | ✗ (scheduled) | Free | Secrets in git |
| **S3 + AES256** | Medium | High | ✓ (on sync) | Low | Cloud backup / easy restore |
| **Syncthing** | Medium | Medium | ✓ (real-time) | Free | Multi-device, no internet needed |
| **Restic** | Hard | High | ✗ (backup) | Free | Point-in-time snapshots |

---

## Security Best Practices

1. **Separate config from secrets** — `openclaw.json` is safe to commit; API keys and tokens go in `secrets.json` which is gitignored (or encrypted via git-crypt/age)
2. **Encrypt secrets at rest** — use [age](https://github.com/FiloSottile/age) or git-crypt; never commit raw tokens
3. **Use HTTPS or SSH for git** — never plain HTTP
4. **Store encryption keys outside the repo** — `~/.age/key.txt`, not inside the synced directory
5. **Private repo only** — never make the sync repo public
6. **Audit before pushing** — `git diff origin/main | grep -i "token\|key\|secret\|password"`
7. **Keep git history** — enables rollback and audit trail; do not force-push or squash history

---

## Troubleshooting

**Agent can't access harqis-work apps (`ModuleNotFoundError`):**
```bash
echo $PYTHONPATH   # must include the harqis-work path
# In openclaw-with-sync.ps1:
$env:PYTHONPATH = "C:\Users\brian\GIT\harqis-work"
./scripts/openclaw-with-sync.ps1 gateway
```

**Changes not appearing on another machine after 30 min:**
```bash
# Machine A — force push
cd harqis-openclaw-sync && ./scripts/sync-push.ps1

# Machine B — force pull
git fetch origin && git pull --rebase origin main
```

**Merge conflict during auto-pull:**
```bash
cd harqis-openclaw-sync
git status
git checkout --theirs openclaw.json   # keep remote version
git add openclaw.json
git rebase --continue
```

**git-crypt not decrypting files:**
```bash
git-crypt status
git-crypt unlock /path/to/key
git-crypt status | grep encrypted
```

**Cron sync not running:**
```bash
tail -f /var/log/openclaw-sync.log
/root/openclaw-sync.sh   # test manually
systemctl status cron
```

---

## References

- [harqis-openclaw-sync README](../harqis-openclaw-sync/README.md)
- [git-crypt](https://github.com/AGWA/git-crypt)
- [age encryption](https://github.com/FiloSottile/age)
- [AWS S3 Encryption](https://docs.aws.amazon.com/AmazonS3/latest/userguide/UsingEncryption.html)
- [Syncthing Docs](https://docs.syncthing.net/)
- [Restic Backup](https://restic.readthedocs.io/)

---

**Status:** ✅ Git sync in production
**Last Updated:** 2026-04-21
**Sync Interval:** Every 30 minutes (auto) / on-demand (manual push)
