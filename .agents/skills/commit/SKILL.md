---
name: commit
description: >
  Stage and commit the current working-tree changes with a Conventional Commit style
  message inferred from the diff, optionally pushing and chaining sync-host.
user-invocable: true
allowed-tools: Bash Read Glob Grep
---

Stage and commit the current working-tree changes with a Conventional-Commit-style message inferred from the diff. Following [COMMIT-MESSAGE-GUIDE.md](../../docs/info/COMMIT-MESSAGE-GUIDE.md).

**Calling `/commit` is your sign-off** — the skill stages all working-tree changes, commits, and pushes to the tracking remote in one shot, no confirmation prompt. If the remote has new commits, it rebases first and then pushes. Use `--dry-run` to preview first, `--no-push` to commit without pushing, or pass pathspecs to commit a subset.

**After a successful commit it also offers to chain `/sync-host`** when any of this host's configured `[sync] items` (in `machines.local.toml`) have local changes. Those items (`.env`, `frontend/.env`, `machines.local.toml`, …) are **gitignored** — they are never in the commit and a server `git pull` will not update them — so this is the step that pushes fresh config to the server. Unlike the commit/push, the sync **always asks for confirmation** (it pushes secrets to a remote). Suppress it with `--no-sync`, or skip the confirmation prompt with `--sync`.

## Arguments

`$ARGUMENTS` is optional and free-form. Order doesn't matter; tokens are parsed independently:

| Token | Effect |
|---|---|
| `<free text>` | Subject hint — biases the drafted subject toward this wording. |
| `<pathspec>` | Any token that resolves to an existing path (file or directory). Limits staging to that path. Multiple allowed. |
| `--type <t>` | Force the type (`feat`, `fix`, `chore`, `test`, `docs`, `refactor`, `perf`, `build`, `ci`, `style`). |
| `--scope <s>` | Force the scope (`apps`, `apps/google`, `workflows/hud`, `repo`, …). |
| `--no-untracked` | Skip untracked files when auto-staging (default: include untracked tracked by `git ls-files --others --exclude-standard`). |
| `--no-push` | Commit but skip the push step. |
| `--no-sync` | Skip the post-commit `/sync-host` offer entirely (Step 9). |
| `--sync` | Run `/sync-host` for changed `[sync] items` without the confirmation prompt. |
| `--dry-run` | Print the drafted message and stop. Stage nothing. Commit nothing. Push nothing. No sync. |

If a token starts with `-` it's a flag; if it resolves to an existing path it's a pathspec; otherwise it's part of the subject hint.

---

## Step 1 — Determine what to commit

Run in parallel:

```bash
git status --short
git diff --cached --name-status
```

Then pick the **commit set** in this priority order:

1. **Pathspecs given** → run `git add -- <paths>`. The commit set is whatever is now staged.
2. **Anything already staged** (and no pathspecs given) → use the existing staged set as-is. Don't auto-stage extras. Mention any unstaged working-tree changes once so the user knows they'll be left out.
3. **Nothing staged, no pathspecs** → auto-stage:
   - Tracked modifications + deletions: `git add -u`
   - Untracked files (unless `--no-untracked`): `git add -- <each path from git ls-files --others --exclude-standard>`
   - Skip anything matching `.env*` even if otherwise untracked — print a one-line warning that `.env*` files were skipped for safety. The user can stage them manually if intentional.

After staging, re-read:

```bash
git diff --cached --name-status
git diff --cached --stat
git diff --cached
```

**If still nothing is staged** (e.g. clean tree, or pathspecs matched nothing): stop and print:

> Nothing to commit. Working tree is clean (or pathspecs matched no changes).

Do not invent changes. Do not run `git commit --allow-empty`.

## Step 2 — Classify the type

Apply rules from [COMMIT-MESSAGE-GUIDE.md → Type-detection cheatsheet](../../docs/info/COMMIT-MESSAGE-GUIDE.md#type-detection-cheatsheet-used-by-commit) in this priority order:

1. If `--type <t>` was passed → use that, skip detection.
2. If **every** staged file matches `**/test_*.py` or `**/tests/**` → `test`.
3. If **every** staged file matches `*.md` or `docs/**` → `docs`.
4. If **every** staged file matches `Dockerfile*` or `docker-compose*.yml` → `build`.
5. If **every** staged file matches `.github/**` or `.gitlab-ci.yml` → `ci`.
6. If **every** staged file matches one of `requirements*.txt`, `pytest.ini`, `.gitignore`, `apps_config.yaml`, `.env*` → `chore`.
7. Otherwise inspect the diff:
   - Net-new files in prod code, or new top-level `def`/`class` in prod code → `feat`.
   - Subject hint or diff context contains bug language (`fix`, `bug`, `regression`, `error`, `crash`, `wrong`, `broken`) → `fix`.
   - Pure rename/move/extract/inline with no behaviour change → `refactor`.
   - Whitespace/formatting only (`git diff --cached --check` is clean and the diff is all `+`/`-` of identical content) → `style`.
   - Default fallback → `chore`.

Mixed staging (prod + tests): use the prod-code type. Never use `test` when prod files are also staged.

`.agents/skills/*/SKILL.md` exception: a net-new slash command file is `feat`, not `docs`, even though it's a `.md` file — these are functional skill definitions executed by the harness.

## Step 3 — Pick the scope

Apply rules from [COMMIT-MESSAGE-GUIDE.md → Scope-detection cheatsheet](../../docs/info/COMMIT-MESSAGE-GUIDE.md#scope-detection-cheatsheet-used-by-commit):

1. If `--scope <s>` was passed → use that.
2. Take each staged file's first path segment. Recognised layers: `apps`, `workflows`, `agents`, `mcp`, `frontend`, `docs`, `scripts`.
3. If all staged files share **one** layer → scope = that layer.
4. If they also share **one** sub-folder under that layer → scope = `<layer>/<sub>` (e.g. `apps/google`, `workflows/hud`, `agents/kanban`).
5. If files span multiple layers → scope = `repo`.
6. Root-level files only (`README.md`, `requirements.txt`, `Dockerfile`, `apps_config.yaml`, etc.) → scope = `repo`.

Treat any non-recognised first segment as `repo` (don't invent new top-level scopes).

## Step 4 — Draft the subject

- Imperative, lower-case, no trailing period, **≤72 chars** in the full line.
- If a subject hint was given in `$ARGUMENTS`, use it as the seed; otherwise summarise the diff.
- Lead with the verb: `add`, `fix`, `update`, `remove`, `rename`, `support`, `mirror`, `extract`, `inline`, `move`, `pin`.
- Be concrete — name the function, file, app, or behaviour. Avoid `improve`, `enhance`, `cleanup`, `refine`, `various`.
- Mention the *what* changed, not the *why*.

If the staged set spans clearly unrelated areas (e.g. one workflow change + one app change), surface this **once** in the result message after committing — never as a blocking prompt:

> Note: this commit mixed `<area A>` and `<area B>`. Consider `git reset HEAD~` and re-running `/commit` with pathspecs to split it.

## Step 5 — Assemble and validate

Format: `<type>(<scope>): <subject>`

Length check: if the full line is >72 chars, shorten the subject (drop adjectives, swap to a tighter verb). Never abbreviate type or scope.

Validate:
- Subject does not start with `(work)`, `(wip)`, capital letter, or end with `.`.
- Type is in the allowed set.
- Scope is in the allowed set or follows `<layer>/<name>`.

## Step 6 — Commit (no confirmation)

If `--dry-run`, print the drafted message + the staged-file list and stop. Do **not** unstage what was staged in Step 1 — the user may want to inspect and commit manually.

Otherwise commit immediately via HEREDOC:

```bash
git commit -m "$(cat <<'EOF'
<final message>
EOF
)"
```

**Hard rules:**

- Never pass `--no-verify`. If a pre-commit hook fails, surface the error and stop. Leave the staged state intact so the user can fix and re-run `/commit`.
- Never amend (`--amend`). Always a new commit.
- Never `git add -A` blindly — auto-staging is `git add -u` plus enumerated untracked files (with `.env*` skipped). Untracked files are listed in the post-commit summary so the user can spot anything unexpected.
- No `Co-Authored-By` footer.

## Step 7 — Push (rebase if remote diverged)

Skip this step entirely if `--no-push` was passed.

Determine the current branch and its upstream:

```bash
git rev-parse --abbrev-ref HEAD
git rev-parse --abbrev-ref --symbolic-full-name @{u} 2>/dev/null
```

Then:

1. **Upstream is configured** → run `git push`.
   - If it succeeds, continue to Step 8.
   - If it fails because the remote has new commits (rejected non-fast-forward / "fetch first"):
     - Run `git pull --rebase --autostash`.
     - If rebase completes cleanly → `git push` again.
     - If rebase has conflicts → **stop**. Do not run `git rebase --abort`, `git rebase --skip`, or any destructive recovery. Print the conflicting paths and tell the user to resolve, then run `git rebase --continue && git push`. The local commit stays — it's safe.
   - If it fails for any other reason (auth, network, hook, protected branch) → stop and surface the error verbatim. Leave the local commit in place.
2. **No upstream configured** → run `git push -u origin <current-branch>` to push and set tracking. Same failure handling as above.

**Hard rules for push:**

- Never `--force` or `--force-with-lease`. If the remote rejects, rebase is the only allowed recovery.
- Never `git rebase --abort` or `--skip` automatically. Conflicts are the user's call.
- Never push to a different remote or branch than the current one's upstream.

## Step 8 — Report

After the commit (and push, if attempted), print:

```
<oneline from `git log -1 --oneline`>

Staged: <N> file(s)
  <file 1>
  <file 2>
  …and M more
Untracked added: <list, or "(none)">
.env* skipped: <list, or "(none)">
Push: <pushed to <remote>/<branch> | rebased onto <remote>/<branch> and pushed | skipped (--no-push) | failed: <reason>>
```

If the diff spanned multiple unrelated scopes (Step 4 note), append the split-suggestion line.

Then continue to Step 9.

## Step 9 — Offer config sync (`/sync-host`)

The `/sync-host` skill pushes a configured set of config/secret files (`[sync] items` in
`machines.local.toml`) to the server over SSH. Those files are **gitignored** — they are
not in the commit, and a server `git pull` will not update them — so when local config
changed alongside this commit, the server is left stale until they're pushed. This step
bridges that gap.

**Skip this step entirely if** `--no-sync` was passed, or `--dry-run` (nothing was
committed), or the commit itself was aborted/nothing-to-commit. A `--no-push` commit
still runs this step — config sync is independent of the git push.

1. **Load the sync config.** Read `[sync] items` (and `[sync] default_machine`) from
   `machines.local.toml` at the repo root. If the file or the `[sync]` section is missing,
   print one line — `Config sync: not configured on this host; skipping.` — and continue to
   Step 10. (`/sync-host` is gitignored-config-only; absence just means this machine never syncs.)

2. **Read the last-sync marker.** `.git/sync-host.last` holds the epoch-seconds timestamp of
   the last successful sync from this skill. Treat a missing marker as `0` (first run — every
   present item counts as changed; the user confirms or declines once to set the baseline).

3. **Detect changed items.** For each path in `[sync] items` (relative to the repo root),
   compare modification time against the marker — **do NOT use `git status`; these paths are
   gitignored and git won't report them.** Use the dedicated tools, not `git`:
   - A **file** changed when its mtime > marker.
   - A **directory** (e.g. `.env/`) changed when ANY file under it has mtime > marker.
   Collect the changed items with their newest mtime. Missing items locally are reported but
   never block (don't push a partial set — that's `/sync-host`'s own guard).

4. **Nothing changed →** print `Config sync: no changes to [sync] items; skipping.` and
   continue to Step 10.

5. **Something changed → summarise and confirm.** Print a compact summary:
   - resolved target: `[sync] default_machine`
   - each changed item + its newest mtime (and any missing-locally items)
   Then, unless `--sync` was passed, **ask for explicit confirmation** with AskUserQuestion
   (this pushes secrets to a remote — always confirm; never auto-sync without `--sync`).
   On **no**: print `Config sync skipped — run /sync-host manually when ready.` and continue
   to Step 10 **without** touching the marker (the change stays pending).

6. **On confirmation (or `--sync`), run the sync.** Invoke the `/sync-host` skill (it resolves
   the OS script flavor, host, and auth — key-based for the default Mac mini target, so no
   password). If it exits 0, write the current epoch-seconds to `.git/sync-host.last` so the
   same edits aren't re-flagged next commit, and append to the report:
   `Config sync: pushed <N> item(s) to <default_machine>`.
   If it fails, surface the error verbatim, **leave the marker unchanged** (so the next commit
   re-offers), and append `Config sync: failed — <reason>`.

Stop.

## Step 10 — Stale memory

If a memory entry contradicts the rules above, update or remove it. The guide and this skill are the source of truth.
