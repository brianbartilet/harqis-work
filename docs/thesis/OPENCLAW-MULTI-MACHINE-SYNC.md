# OpenClaw Multi-Machine Sync & Security Guide

How to sync OpenClaw information across multiple machines with a Gateway hosted on a server and nodes connected to it via OpenClaw TUI.

---

## Architecture Overview

### Current Setup

**Gateway (VPS/Server):**
- Runs the OpenClaw Gateway process
- Stores config, state, sessions in `OPENCLAW_STATE_DIR` and `OPENCLAW_CONFIG_PATH`
- Nodes (phones, other machines) connect to it via Tailscale/VPN

**Nodes (Client Devices):**
- Android/iOS companion apps paired to the Gateway
- Send commands, receive responses
- No persistent agent runtime (Gateway handles that)

### The Problem

- Non-workspace context lives on the Gateway machine
- If you lose the VPS, you lose all memory/context
- Each Gateway instance has isolated state
- Secrets are mixed with config, making it hard to sync securely

---

## What to Sync (Non-Workspace Items)

| Item | Location | Why Sync | Sensitivity |
|------|----------|---------|-------------|
| **Config** | `.openclaw/openclaw.json` | Gateway settings | High (has tokens) |
| **State/Sessions** | `.openclaw/state/` | Agent context, session history | Medium |
| **Auth tokens** | `.openclaw/secrets/` | API keys, credentials | **CRITICAL** |
| **Workspace** | `.openclaw/workspace/` | Already synced via git | Low |
| **Cron jobs** | Internal to gateway | Recreate on restore | Medium |

---

## Sync Options (Secure)

### Option 1: Encrypted Git + Private Repo (Recommended)

Store memory + config in a **private GitHub repo** with encrypted secrets.

**Setup:**

1. **Create a private GitHub repo:**
   ```bash
   git clone https://github.com/yourusername/openclaw-config
   cd openclaw-config
   ```

2. **Install git-crypt:**
   ```bash
   # macOS
   brew install git-crypt
   
   # Ubuntu
   sudo apt-get install git-crypt
   
   # Windows (via Chocolatey)
   choco install git-crypt
   ```

3. **Initialize encryption:**
   ```bash
   git-crypt init
   git-crypt add-gpg-user [your-gpg-key-id]
   # or if you don't have GPG:
   git-crypt export-key ~/.git-crypt/key
   ```

4. **Configure .gitattributes** to encrypt sensitive files:
   ```bash
   cat > .gitattributes << 'EOF'
   .openclaw/secrets/** filter=git-crypt diff=git-crypt
   .openclaw/openclaw.json filter=git-crypt diff=git-crypt
   memory/** filter=git-crypt diff=git-crypt
   !.gitignore
   EOF
   
   git add .gitattributes
   git commit -m "init: add encryption rules"
   ```

5. **Copy OpenClaw files to sync:**
   ```bash
   cp -r ~/.openclaw/openclaw.json .
   cp -r ~/.openclaw/state/ .
   cp -r ~/.openclaw/workspace/MEMORY.md .
   ```

6. **Commit & push (automatically encrypted):**
   ```bash
   git add .
   git commit -m "sync: initial openclaw config"
   git push origin main
   ```

7. **Auto-sync on the Gateway** with cron:
   ```bash
   # Create /etc/cron.d/openclaw-sync
   0 * * * * cd /path/to/openclaw-config && \
     git pull origin main && \
     cp openclaw.json ~/.openclaw/ && \
     cp -r state/* ~/.openclaw/state/ && \
     git add . && \
     git commit -m "auto-sync: $(date)" && \
     git push origin main
   ```

**Pros:**
- Version control with history
- Encrypted at rest (git-crypt handles decryption transparently)
- Easy rollback to previous versions
- Works across all platforms

**Cons:**
- Requires managing encryption keys securely
- Manual sync setup needed

---

### Option 2: S3 + Encryption (Cloud-hosted)

Store encrypted state on AWS S3 for cloud backup.

**Setup:**

1. **Create S3 bucket:**
   ```bash
   aws s3 mb s3://my-openclaw-backup --region us-east-1
   ```

2. **Enable encryption:**
   ```bash
   aws s3api put-bucket-encryption \
     --bucket my-openclaw-backup \
     --server-side-encryption-configuration '{
       "Rules": [{
         "ApplyServerSideEncryptionByDefault": {
           "SSEAlgorithm": "AES256"
         }
       }]
     }'
   ```

3. **Sync with server-side encryption:**
   ```bash
   aws s3 sync ~/.openclaw s3://my-openclaw-backup/ \
     --sse AES256 \
     --exclude ".git/*" \
     --exclude "node_modules/*"
   ```

4. **Automate with cron:**
   ```bash
   # /etc/cron.d/openclaw-s3-sync
   0 * * * * aws s3 sync ~/.openclaw s3://my-openclaw-backup/ \
     --sse AES256 --exclude ".git/*"
   ```

5. **Restore on new VPS:**
   ```bash
   aws s3 sync s3://my-openclaw-backup/ ~/.openclaw
   openclaw gateway restart
   ```

**Pros:**
- Cloud backup, highly available
- Automatic encryption
- Easy to restore on any machine with AWS access

**Cons:**
- AWS costs
- Requires IAM credentials (must be secured)
- Less transparent than git-based sync

---

### Option 3: Self-Hosted Sync (Syncthing/Restic)

Use **Syncthing** (peer-to-peer) or **Restic** (encrypted backups).

#### Syncthing (Real-time sync)

1. **Install on Gateway + local machine:**
   ```bash
   # macOS
   brew install syncthing
   
   # Ubuntu
   sudo apt-get install syncthing
   ```

2. **Start Syncthing:**
   ```bash
   syncthing --home=~/.syncthing
   # Web UI: http://localhost:8384
   ```

3. **Configure folders to sync:**
   - Open http://localhost:8384
   - Add folder: `~/.openclaw`
   - Add remote device (your laptop, etc.)
   - Accept sync invitation

4. **Syncthing will sync in real-time** across devices

**Pros:**
- Real-time sync, no cron needed
- Peer-to-peer (no external servers)
- Fast, low bandwidth usage

**Cons:**
- Requires Syncthing running on all machines
- Encryption must be handled separately
- More complex setup

#### Restic (Encrypted backups)

1. **Install Restic:**
   ```bash
   # macOS
   brew install restic
   
   # Ubuntu
   sudo apt-get install restic
   ```

2. **Initialize encrypted backup:**
   ```bash
   restic -r /mnt/backup init
   # or with S3:
   restic -r s3:s3.amazonaws.com/bucket/path init
   ```

3. **Create backup:**
   ```bash
   restic -r /mnt/backup backup ~/.openclaw
   ```

4. **Automate with cron:**
   ```bash
   0 * * * * restic -r /mnt/backup backup ~/.openclaw
   ```

5. **Restore:**
   ```bash
   restic -r /mnt/backup restore latest --target /
   ```

**Pros:**
- Built-in encryption (AES-256)
- Efficient (only stores changes)
- Works with local/S3/B2 storage

**Cons:**
- More complex for frequent syncs
- Better for backups than real-time sync

---

## Recommended Approach (Step-by-Step)

### Step 1: Separate Secrets from Config

**Before:**
```json
// openclaw.json (synced, contains secrets)
{
  "gateway": { "port": 18789 },
  "auth": {
    "profiles": {
      "anthropic:default": {
        "apiKey": "sk_ant_..."  // ← EXPOSED IN GIT
      }
    }
  }
}
```

**After:**
```json
// openclaw.json (safe to sync)
{
  "gateway": { "port": 18789 },
  "auth": {
    "profiles": {
      "anthropic:default": {
        "mode": "api_key"
        // apiKey loaded from secrets.json at runtime
      }
    }
  }
}

// secrets.json (ENCRYPTED only)
{
  "anthropic:default": {
    "apiKey": "sk_ant_..."
  },
  "telegram": {
    "botToken": "..."
  }
}
```

### Step 2: Encrypt Secrets at Rest

Use **age** (modern, simpler than GPG):

```bash
# Install age
curl https://api.github.com/repos/FiloSottile/age/releases/assets \
  | grep "age-v.*-linux-amd64.tar.gz" | head -1 | cut -d'"' -f 4 \
  | xargs wget && tar xzf age-*.tar.gz

# Generate a key (store in ~/.age/key.txt)
age-keygen -o ~/.age/key.txt

# Encrypt secrets (creates secrets.json.age)
age -r $(cat ~/.age/key.txt | grep "public key") \
  -o secrets.json.age secrets.json

# Delete unencrypted
rm secrets.json
```

### Step 3: Sync with Encryption in Transit

```bash
# Add to .gitignore
echo "secrets.json" >> .gitignore

# Track encrypted file
echo "!secrets.json.age" >> .gitignore

# Push encrypted config to git
git add secrets.json.age openclaw.json workspace/MEMORY.md
git commit -m "sync: config + encrypted secrets"
git push origin main
```

### Step 4: Restore on New Machine

```bash
# Clone repo
git clone https://github.com/yourusername/openclaw-config
cd openclaw-config

# Decrypt secrets (using your age key)
age -d -i ~/.age/key.txt secrets.json.age > secrets.json

# Copy to OpenClaw
cp openclaw.json ~/.openclaw/
cp secrets.json ~/.openclaw/secrets/
cp MEMORY.md ~/.openclaw/workspace/

# Restart gateway
openclaw gateway restart
```

### Step 5: Automate Sync on Gateway

Create `/etc/cron.d/openclaw-sync`:

```bash
#!/bin/bash
set -e

OPENCLAW_REPO="/root/openclaw-config"
OPENCLAW_HOME="/root/.openclaw"

# Pull latest
cd $OPENCLAW_REPO
git pull origin main

# Copy config to OpenClaw
cp openclaw.json $OPENCLAW_HOME/
cp -r state/* $OPENCLAW_HOME/state/ 2>/dev/null || true
cp MEMORY.md $OPENCLAW_HOME/workspace/ 2>/dev/null || true

# Commit changes back
git add .
git diff --cached --quiet || git commit -m "auto-sync: $(date)"
git push origin main

# Reload gateway if config changed
openclaw gateway restart
```

Install as cron job:

```bash
0 * * * * /root/openclaw-sync.sh >> /var/log/openclaw-sync.log 2>&1
```

---

## Security Best Practices

### 1. **Separate Concerns**
- Config (safe to sync): `openclaw.json`, `workspace/`
- Secrets (encrypted): `secrets.json`, tokens, API keys

### 2. **Encrypt at Rest**
- Use git-crypt or age for encrypted files
- Never commit raw API keys/tokens

### 3. **Encrypt in Transit**
- Always use HTTPS for git push/pull
- Use GitHub's HTTPS or SSH with keys

### 4. **Key Management**
- Store age/GPG keys outside the repo
- Use environment variables for sensitive paths
- Rotate keys periodically

### 5. **Access Control**
- Private GitHub repo (not public)
- Limit push access to trusted machines
- Use GitHub SSH keys (not passwords)

### 6. **Audit Trail**
- Keep git history (allows rollback)
- Monitor sync logs
- Alert on failed syncs

---

## Node + Multi-Machine Sync

For Node apps + multiple gateways:

1. **Each Gateway instance** stores its own state
2. **Sync shared memory** (MEMORY.md) to central location:
   ```bash
   # On each Gateway after agent runs:
   gsutil -m cp ~/.openclaw/workspace/MEMORY.md gs://shared-bucket/
   ```
3. **Nodes always talk to primary Gateway** (no node-to-node sync needed)
4. **Cross-machine context** via shared memory file in GCS/S3

---

## Quick Comparison

| Option | Ease | Security | Real-time | Cost | Best For |
|--------|------|----------|-----------|------|----------|
| **Git + git-crypt** | Medium | High | ✗ (hourly) | Free | Long-term, version control |
| **S3 + AES256** | Medium | High | ✓ (sync) | Low | Cloud backup, easy restore |
| **Syncthing** | Medium | Medium | ✓ (real-time) | Free | P2P, multi-device |
| **Restic** | Hard | High | ✗ (backup) | Free | Incremental backups |

**Recommendation for your setup:** Git + git-crypt (encrypted GitHub repo)
- Simple to maintain
- Version control + history
- Encrypted secrets
- Free hosting
- Easy restore on new VPS

---

## Implementation Checklist

- [ ] Create private GitHub repo `openclaw-config`
- [ ] Install git-crypt on Gateway
- [ ] Separate secrets into `secrets.json`
- [ ] Create `.gitattributes` with encryption rules
- [ ] Initialize git-crypt with GPG key
- [ ] Encrypt and commit initial state
- [ ] Test decryption on another machine
- [ ] Create `/etc/cron.d/openclaw-sync` script
- [ ] Test cron job manually
- [ ] Monitor `/var/log/openclaw-sync.log`
- [ ] Document key backup/recovery procedure
- [ ] Set up GitHub branch protection (main)

---

## Troubleshooting

### Git-crypt not decrypting files

```bash
# Check if initialized
git-crypt status

# Unlock with key
git-crypt unlock /path/to/key

# Check encrypted files
git-crypt status | grep encrypted
```

### Cron sync not working

```bash
# Check logs
tail -f /var/log/openclaw-sync.log

# Test manually
/root/openclaw-sync.sh

# Check cron is running
systemctl status cron
```

### Secrets not loading on restore

```bash
# Verify secrets.json exists
cat ~/.openclaw/secrets/secrets.json

# Check OpenClaw can read it
openclaw gateway status

# Restart with debug
openclaw gateway --verbose
```

---

## References

- [git-crypt Documentation](https://github.com/AGWA/git-crypt)
- [age Project](https://github.com/FiloSottile/age)
- [AWS S3 Encryption](https://docs.aws.amazon.com/AmazonS3/latest/userguide/UsingEncryption.html)
- [Syncthing Docs](https://docs.syncthing.net/)
- [Restic Backup](https://restic.readthedocs.io/)
