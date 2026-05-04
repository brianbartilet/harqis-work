Stage and commit the current working-tree changes with a Conventional-Commit-style message inferred from the diff. Following [COMMIT-MESSAGE-GUIDE.md](../../docs/info/COMMIT-MESSAGE-GUIDE.md).

**Calling `/commit` is your sign-off** — the skill stages all working-tree changes, commits, and pushes to the tracking remote in one shot, no confirmation prompt. If the remote has new commits, it rebases first and then pushes. Use `--dry-run` to preview first, `--no-push` to commit without pushing, or pass pathspecs to commit a subset.

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
| `--dry-run` | Print the drafted message and stop. Stage nothing. Commit nothing. Push nothing. |

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

`.claude/skills/*/SKILL.md` exception: a net-new slash command file is `feat`, not `docs`, even though it's a `.md` file — these are functional skill definitions executed by the harness.

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

Stop.

## Step 9 — Stale memory

If a memory entry contradicts the rules above, update or remove it. The guide and this skill are the source of truth.
