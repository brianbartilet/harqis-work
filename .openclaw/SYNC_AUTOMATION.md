# OpenClaw Sync Automation Guide

Automated sync configuration for **harqis-openclaw-sync** with commit/push every 15 minutes and pull every 30 minutes.

## Current Status ✅

**Cron jobs are already active:**
- **Push Job:** `bb9a4c5e-45fb-4b60-ac9f-b528120becf0` (every 15 minutes)
- **Pull Job:** `3f719430-4363-482e-b275-86c4f5ee28c8` (every 30 minutes)

These run via OpenClaw's gateway scheduler and post updates automatically.

---

## Manual Setup (Optional)

If you want additional redundancy or local scheduling, follow the platform-specific instructions below.

---

## Windows (Task Scheduler)

### Push Changes Every 15 Minutes

1. **Open Task Scheduler:**
   - Press `Win+R`, type `taskschd.msc`, press Enter

2. **Create New Task:**
   - Right-click "Task Scheduler Library" → "Create Basic Task"
   - **Name:** `OpenClaw Sync Push (15min)`
   - **Description:** Commit and push workspace changes

3. **Set Trigger:**
   - Click **Triggers** tab → **New**
   - **Begin the task:** At startup
   - Check: "Repeat task every: 15 minutes"
   - Duration: "Indefinitely"
   - Click **OK**

4. **Set Action:**
   - Click **Actions** tab → **New**
   - **Action:** Start a program
   - **Program/script:** `powershell.exe`
   - **Add arguments:**
     ```
     -NoProfile -ExecutionPolicy Bypass -File "C:\Users\brian\GIT\harqis-work\.openclaw\sync-push.ps1"
     ```
   - Click **OK**

5. **Set Conditions:**
   - Click **Conditions** tab
   - Uncheck: "Start the task only if the computer is on AC power"
   - Click **OK**

### Pull Changes Every 30 Minutes

Repeat the above but:
- **Name:** `OpenClaw Sync Pull (30min)`
- **Repeat every:** 30 minutes
- **Arguments:**
  ```
  -NoProfile -ExecutionPolicy Bypass -File "C:\Users\brian\GIT\harqis-work\.openclaw\sync-pull.ps1"
  ```

### PowerShell Script Alternative

Run this in **PowerShell as Administrator** to create tasks automatically:

```powershell
# Create Push Task (15 minutes)
$trigger = New-ScheduledTaskTrigger -AtStartup -RepetitionInterval (New-TimeSpan -Minutes 15) -RepetitionDuration (New-TimeSpan -Days 999)
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -File 'C:\Users\brian\GIT\harqis-work\.openclaw\sync-push.ps1'"
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
Register-ScheduledTask -TaskName "OpenClaw Sync Push (15min)" -Trigger $trigger -Action $action -Principal $principal -Force

# Create Pull Task (30 minutes)
$trigger = New-ScheduledTaskTrigger -AtStartup -RepetitionInterval (New-TimeSpan -Minutes 30) -RepetitionDuration (New-TimeSpan -Days 999)
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -File 'C:\Users\brian\GIT\harqis-work\.openclaw\sync-pull.ps1'"
Register-ScheduledTask -TaskName "OpenClaw Sync Pull (30min)" -Trigger $trigger -Action $action -Principal $principal -Force

Write-Host "✓ Tasks created successfully"
```

---

## macOS (launchd)

### Push Changes Every 15 Minutes

Create file: `~/Library/LaunchAgents/com.openclaw.sync-push.plist`

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.openclaw.sync-push</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>$HOME/GIT/harqis-work/.openclaw/sync-push.sh</string>
    </array>
    <key>StartInterval</key>
    <integer>900</integer>
    <key>StandardOutPath</key>
    <string>$HOME/Library/Logs/openclaw-sync-push.log</string>
    <key>StandardErrorPath</key>
    <string>$HOME/Library/Logs/openclaw-sync-push-error.log</string>
</dict>
</plist>
```

### Pull Changes Every 30 Minutes

Create file: `~/Library/LaunchAgents/com.openclaw.sync-pull.plist`

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.openclaw.sync-pull</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>$HOME/GIT/harqis-work/.openclaw/sync-pull.sh</string>
    </array>
    <key>StartInterval</key>
    <integer>1800</integer>
    <key>StandardOutPath</key>
    <string>$HOME/Library/Logs/openclaw-sync-pull.log</string>
    <key>StandardErrorPath</key>
    <string>$HOME/Library/Logs/openclaw-sync-pull-error.log</string>
</dict>
</plist>
```

### Load Services

```bash
# Load push service
launchctl load ~/Library/LaunchAgents/com.openclaw.sync-push.plist

# Load pull service
launchctl load ~/Library/LaunchAgents/com.openclaw.sync-pull.plist

# Verify they're loaded
launchctl list | grep openclaw
```

### View Logs

```bash
tail -f ~/Library/Logs/openclaw-sync-push.log
tail -f ~/Library/Logs/openclaw-sync-pull.log
```

---

## Linux (cron)

### Edit crontab

```bash
crontab -e
```

### Add Entries

```crontab
# OpenClaw Sync - Push every 15 minutes
*/15 * * * * /bin/bash "$HOME/GIT/harqis-work/.openclaw/sync-push.sh" >> "$HOME/.openclaw/logs/sync-push.log" 2>&1

# OpenClaw Sync - Pull every 30 minutes
*/30 * * * * /bin/bash "$HOME/GIT/harqis-work/.openclaw/sync-pull.sh" >> "$HOME/.openclaw/logs/sync-pull.log" 2>&1
```

### Create Log Directory

```bash
mkdir -p ~/.openclaw/logs
chmod 755 ~/.openclaw/logs
```

### View Logs

```bash
tail -f ~/.openclaw/logs/sync-push.log
tail -f ~/.openclaw/logs/sync-pull.log
```

### Verify Cron Jobs

```bash
crontab -l
```

---

## Manual Execution

### Windows (PowerShell)

```powershell
# Push changes
.\sync-push.ps1

# Pull changes
.\sync-pull.ps1
```

### macOS / Linux

```bash
# Push changes
chmod +x sync-push.sh
./sync-push.sh

# Pull changes
chmod +x sync-pull.sh
./sync-pull.sh
```

---

## Troubleshooting

### Tasks Not Running

**Windows:**
```powershell
# Check task status
Get-ScheduledTask "OpenClaw Sync Push*"

# View last run result
$t = Get-ScheduledTask "OpenClaw Sync Push (15min)"
$t | Get-ScheduledTaskInfo

# Run manually to test
.\sync-push.ps1 -Verbose
```

**macOS/Linux:**
```bash
# Check logs
tail -50 ~/Library/Logs/openclaw-sync-push.log

# Test script manually
bash ~/GIT/harqis-work/.openclaw/sync-push.sh
```

### Git Authentication

If push/pull fails with auth errors:

1. **Verify credentials:**
   ```bash
   git config --global user.name
   git config --global user.email
   ```

2. **Check SSH/HTTPS setup:**
   ```bash
   cd ~/GIT/harqis-openclaw-sync
   git remote -v
   ```

3. **Use SSH key (recommended):**
   ```bash
   git remote set-url origin git@github.com:brianbartilet/harqis-openclaw-sync.git
   ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519
   # Add public key to GitHub
   ```

4. **Or use personal access token (HTTPS):**
   ```bash
   git credential approve
   # Enter host: github.com
   # Enter username: brianbartilet
   # Enter password: <your-pat>
   ```

### Repo Path Issues

Update the repo path in scripts if using a different location:

**Windows:**
```powershell
.\sync-push.ps1 -RepoPath "C:\path\to\harqis-openclaw-sync"
```

**macOS/Linux:**
```bash
./sync-push.sh /path/to/harqis-openclaw-sync
```

---

## Monitoring

### Check Cron Job Status

```bash
# OpenClaw (recommended - better monitoring)
openclaw cron list

# View specific jobs
openclaw cron list | grep "harqis-openclaw-sync"

# View job history
openclaw cron runs --jobId bb9a4c5e-45fb-4b60-ac9f-b528120becf0
```

### Manual Test Run

```bash
# Trigger push immediately
openclaw cron run --jobId bb9a4c5e-45fb-4b60-ac9f-b528120becf0

# Trigger pull immediately
openclaw cron run --jobId 3f719430-4363-482e-b275-86c4f5ee28c8
```

---

## Best Practices

1. **Use OpenClaw cron** (already set up) as primary scheduler
2. **Add local scheduling** (Task Scheduler/cron) as backup only
3. **Monitor logs regularly** for sync errors
4. **Test manually** before relying on automation
5. **Keep commits atomic** — document what changed
6. **Handle conflicts** — set up merge strategy if multiple devices push
7. **Separate config** from working data — don't sync state/ directory

---

## Files Included

- `sync-push.ps1` — Windows PowerShell push script
- `sync-pull.ps1` — Windows PowerShell pull script
- `sync-push.sh` — macOS/Linux push script
- `sync-pull.sh` — macOS/Linux pull script
- `SYNC_AUTOMATION.md` — This guide

---

**Status:** ✅ Cron jobs active  
**Next Run (push):** ~15 minutes from now  
**Next Run (pull):** ~30 minutes from now  
**Last Updated:** 2026-04-26
