Generate a Conventional-Commit-style message from the currently staged files and commit, following the harqis-work commit template.

Reference: [docs/info/COMMIT-MESSAGE-GUIDE.md](../../docs/info/COMMIT-MESSAGE-GUIDE.md). Read the rules there before drafting — this skill is the automated path of that guide.

## Arguments

`$ARGUMENTS` is optional and free-form. Use it to override or hint:

| Token | Effect |
|---|---|
| `<free text>` | Treat as a subject hint — bias the drafted subject toward this wording. |
| `--type <t>` | Force the type (`feat`, `fix`, `chore`, `test`, `docs`, `refactor`, `perf`, `build`, `ci`, `style`). |
| `--scope <s>` | Force the scope (`apps`, `apps/google`, `workflows/hud`, `repo`, …). |
| `--dry-run` | Print the drafted message and stop. Do not commit. |

If `$ARGUMENTS` is empty, infer everything.

---

## Step 1 — Read staged changes only

Run in parallel:

```bash
git diff --cached --name-status
git diff --cached --stat
git diff --cached
```

**If `git diff --cached --name-status` is empty:** stop. Print:

> Nothing is staged. `/commit` only reads staged changes — stage what you want to commit (`git add <paths>`) and run `/commit` again.

Do **not** run `git add` for the user. Do **not** offer to.

If working-tree changes exist alongside staged ones, mention it once so the user knows they'll be left out, then continue.

## Step 2 — Classify the type

Apply rules from [COMMIT-MESSAGE-GUIDE.md → Type-detection cheatsheet](../../docs/info/COMMIT-MESSAGE-GUIDE.md#type-detection-cheatsheet-used-by-commit) in this priority order:

1. If `$ARGUMENTS` includes `--type <t>` → use that, skip detection.
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

## Step 3 — Pick the scope

Apply rules from [COMMIT-MESSAGE-GUIDE.md → Scope-detection cheatsheet](../../docs/info/COMMIT-MESSAGE-GUIDE.md#scope-detection-cheatsheet-used-by-commit):

1. If `$ARGUMENTS` includes `--scope <s>` → use that.
2. Take each staged file's first path segment. Recognised layers: `apps`, `workflows`, `agents`, `mcp`, `frontend`, `docs`, `scripts`.
3. If all staged files share **one** layer → scope = that layer.
4. If they also share **one** sub-folder under that layer → scope = `<layer>/<sub>` (e.g. `apps/google`, `workflows/hud`, `agents/kanban`).
5. If files span multiple layers → scope = `repo`.
6. Root-level files only (`README.md`, `requirements.txt`, `Dockerfile`, `apps_config.yaml`, etc.) → scope = `repo`.

Treat any non-recognised first segment as `repo` (don't invent new top-level scopes).

## Step 4 — Draft the subject

- Imperative, lower-case, no trailing period, **≤72 chars** in the full line.
- If `$ARGUMENTS` has free-text, use it as the seed; otherwise summarise the diff.
- Lead with the verb: `add`, `fix`, `update`, `remove`, `rename`, `support`, `mirror`, `extract`, `inline`, `move`, `pin`.
- Be concrete — name the function, file, app, or behaviour. Avoid `improve`, `enhance`, `cleanup`, `refine`, `various`.
- Mention the *what* changed, not the *why* (why goes in the PR description).

If multiple unrelated changes are staged, the subject becomes vague — flag this:

> Heads up: staged changes touch both `<area A>` and `<area B>`. The drafted subject covers both, but consider splitting into two commits for a cleaner history. Continue anyway?

Do not block — just surface the observation once and proceed if the user confirms.

## Step 5 — Assemble and validate

Format: `<type>(<scope>): <subject>`

Length check: if the full line is >72 chars, shorten the subject (drop adjectives, swap to a tighter verb). Never abbreviate the type or scope.

Validate against the guide's anti-examples:
- Subject does not start with `(work)`, `(wip)`, capital letter, or end with `.`.
- Type is in the allowed set.
- Scope is in the allowed set or follows `<layer>/<name>`.

## Step 6 — Show, confirm, commit

Print the drafted message and a one-line summary of staged files:

```
Drafted commit message:
  <type>(<scope>): <subject>

Staged: <N> file(s) — <short list, max 5, then "…and M more">
```

Then ask: **"Commit this? (yes / edit / cancel)"**

- `yes` → run the commit.
- `edit` → ask the user for their preferred wording, validate against the format, then commit.
- `cancel` / no response → stop without committing.

If `--dry-run` was passed, skip the prompt and stop here.

## Step 7 — Commit

Run with the message via HEREDOC so quoting cannot break:

```bash
git commit -m "$(cat <<'EOF'
<final message>
EOF
)"
```

**Hard rules:**

- Never pass `--no-verify`. If a pre-commit hook fails, surface the error and stop — let the user fix the underlying issue and re-run `/commit`.
- Never amend (`--amend`). Always create a new commit.
- Never push. The user pushes when ready.
- Do not add a `Co-Authored-By` footer — repo style is subject-only.

After the commit, print the resulting `git log -1 --oneline` line and stop.

## Step 8 — Stale memory

If you saved a memory in a prior turn that contradicts the rules above (e.g. a feedback note saying to use a different format), update or remove it now. The guide and this skill are the source of truth.
