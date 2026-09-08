# Remote stack restart verification

Use this workflow when the user asks to pull and restart the HARQIS host remotely.
The deterministic entry point is:

```powershell
.venv\Scripts\python.exe scripts\deploy.py --remote <machine-key>
```

`<machine-key>` resolves through `[ssh.<machine-key>]` in
`machines.local.toml`. The configured `path` must point to the runtime clone;
for the canonical Mac host this resolves to
`/Users/harqis-one/GIT/harqis-work`.

## Full-stack workflow

The remote option runs one fail-fast Bash script over SSH:

1. Resolve and enter the configured runtime clone. Require both `.git` and
   `scripts/deploy.py`.
2. Record the checked-out branch, full HEAD, `git status --short --branch`, and
   `scripts/deploy.py --role host --status` before changing anything.
3. Refuse to pull or restart when the runtime working tree is dirty.
4. Pull the checked-out branch from its configured upstream using
   `git pull --ff-only`.
   - Never switch to `main`, merge, or reset implicitly.
   - Report whether HEAD changed and list files changed by the pulled range.
   - When `origin/main` is available, report its left/right commit counts
     relative to the runtime branch. Do not describe a current runtime branch
     as outdated merely because another branch advanced.
5. Explicitly restart even when Git reports `Already up to date`:

   ```bash
   .venv/bin/python scripts/deploy.py --role host --down
   .venv/bin/python scripts/deploy.py --role host --console
   ```

   A post-merge hook is not deployment proof and does not replace these calls.
6. Verify:
   - frontend `/health` on `FRONTEND_PORT` loaded by `scripts.launch.setup_env`
     (fallback `8081`; never hardcode port 8000);
   - RabbitMQ, Redis, and Elasticsearch are running and healthy;
   - at least one Celery worker responds, with active queues summarized after
     loading the deploy environment;
   - service status and PIDs through `scripts/deploy.py --status`;
   - the checked-out branch did not change and the final working tree is clean.
7. Treat `cloudflared` and `ngrok` failures as non-core caveats unless the user
   explicitly asks to repair tunnels.

Any failed core verification makes the remote command non-zero. Do not report a
successful deployment unless the command prints `REMOTE HOST RESTART VERIFIED`.

## Targeted frontend-only restart

The `--remote` CLI option intentionally performs only the full verified host
restart. When the user explicitly requests a remote frontend-only refresh,
perform the following scoped workflow over SSH instead of broadening it:

1. Record Git state, deploy status, and tracked service PIDs.
2. Pull without running the repository hook:

   ```bash
   git -c core.hooksPath=/dev/null pull --ff-only
   ```

3. Restart only the frontend:

   ```bash
   .venv/bin/python scripts/deploy.py --restart frontend
   ```

4. Confirm the frontend PID changed and its configured `/health` endpoint
   returns HTTP 200. Confirm scheduler, worker, Kanban, Flower, and command
   runner PIDs did not change, then verify final Git cleanliness.

The hook override is invocation-local. Never delete, rename, or persistently
disable hooks.

## Operational cautions

- A Celery worker that pulls a HEAD-changing update can be terminated by the
  post-merge restart hook before it restarts itself. Every automated pull that
  changes HEAD therefore requires a real post-restart Celery ping.
- A repeated user invocation is a fresh restart request. Re-record state, pull,
  restart, and verify again even if the prior run was recent.
- If execution stops mid-restart, inspect Git state, deploy status, and Docker
  state, then recover with the complete pull, down, console, and verification
  sequence.
- HARQIS MCP is stdio/on-demand and is not expected to remain as a persistent
  deploy daemon.

## Final report

Keep the report concise:

- runtime branch, old/new commits, and changed files;
- service status and PIDs;
- frontend, Docker core, and Celery health;
- final Git cleanliness;
- separate non-core tunnel caveats, if any.
