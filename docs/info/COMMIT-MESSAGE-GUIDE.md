# Commit Message Guide

Standard commit message format for the `harqis-work` repo. Generated and enforced by the `/commit` skill (see [SKILLS-INVENTORY.md](SKILLS-INVENTORY.md#commit)).

---

## Format

```
<type>(<scope>): <subject>
```

- **One line.** No body. No footer.
- **Subject:** imperative, lower-case, no trailing period, **≤72 characters**.
- **Type and scope are required.** Never use a bare type (`feat: foo`) — always include the layer.

## Types

Pick the highest-priority type that applies. If a change touches both prod code and tests, use the prod-code type — `test` is reserved for changes that *only* touch tests.

| Type | When to use |
|---|---|
| `fix` | Bug fix in shipped behaviour |
| `feat` | New capability, app, workflow, or endpoint |
| `test` | Tests added or modified, no production code change |
| `docs` | Documentation, comments, README only |
| `refactor` | Restructure without behaviour change |
| `perf` | Performance-only change |
| `chore` | Repo plumbing — `.gitignore`, `requirements.txt`, `pytest.ini`, `apps_config.yaml`, `.env` templates |
| `build` | Dockerfile, `docker-compose.yml`, packaging |
| `ci` | CI configuration (`.github/`, workflow files) |
| `style` | Formatting / whitespace only, no semantic change |

## Scopes

Scope is the top-level layer of the change. If every changed file lives under one sub-app or sub-workflow, use the nested form (`apps/google`); otherwise use the layer (`apps`).

| Scope | Maps to |
|---|---|
| `apps` | Anything under `apps/` |
| `apps/<name>` | Single app — e.g. `apps/google`, `apps/airtable`, `apps/tcg_mp` |
| `workflows` | Anything under `workflows/` |
| `workflows/<name>` | Single workflow category — e.g. `workflows/hud`, `workflows/purchases` |
| `agents` | Anything under `agents/` |
| `agents/kanban` | Kanban orchestrator and profiles |
| `mcp` | `mcp/` server |
| `frontend` | `frontend/` |
| `docs` | `docs/`, `README.md`, in-tree `*.md` |
| `scripts` | `scripts/` |
| `repo` | Cross-cutting (root configs, multi-layer change with no clear primary) |

## Subject rules

- **Imperative mood.** `add`, `fix`, `update`, `remove`, `rename`, `support`, `extract`, `inline`. Not `added`, `adds`, `adding`.
- **Lower-case start.** No leading capital, no trailing period.
- **Concrete verbs.** Avoid `improve`, `enhance`, `refine`, `cleanup` when something more specific fits.
- **Skip filler.** No `some`, `various`, `several`. No `(work)`, `(wip)`.
- **No issue refs in the subject.** Put `Fixes #123` in the PR body, not here.

## Examples

```
feat(apps/airtable): scaffold integration with mcp tools
feat(workflows): support task execution via broadcast
feat(agents/kanban): support manual tags for humans
fix(workflows/hud): mirror tcg qr downloads into now folder
fix(workflows/purchases): handle empty scryfall bulk response
refactor(apps/openai): adopt latest sdk client surface
test(apps/echo_mtg): cover portfolio stats edge cases
test(workflows): add live integration test for monthly linkedin task
docs(repo): document deploy host vs node split
chore(repo): clean up .gitignore
build(repo): pin docker base image to python:3.12-slim
```

### Anti-examples (rewrite these)

| Don't | Do |
|---|---|
| `(work) add new app airtable` | `feat(apps/airtable): scaffold integration` |
| `(work) tcg fix effing bugs` | `fix(workflows/hud): resolve tcg orders qr ordering` |
| `(work) update docs` | `docs(repo): refresh deploy guide` |
| `update tests` | `test(apps): widen coverage on tcg_mp order parser` |
| `feat: add thing` | `feat(apps/<name>): add thing` (always include scope) |

## Type-detection cheatsheet (used by `/commit`)

| File set | Type |
|---|---|
| Only `**/test_*.py`, `**/tests/**` | `test` |
| Only `*.md`, `docs/**` | `docs` |
| Only `Dockerfile*`, `docker-compose*.yml` | `build` |
| Only `.github/**`, `.gitlab-ci.yml` | `ci` |
| Only `requirements*.txt`, `pytest.ini`, `*.gitignore`, `apps_config.yaml`, `.env*` | `chore` |
| Diff adds new functions / classes / files in prod code | `feat` |
| Diff fixes existing function (subject contains `fix`/`bug` cues) | `fix` |
| Diff moves / renames / restructures without adding capability | `refactor` |
| Whitespace / formatting only | `style` |
| Mixed (prod + tests) | use the prod-code type, not `test` |

## Scope-detection cheatsheet (used by `/commit`)

1. List staged files → take each file's first path segment.
2. If all files share one segment, that's the layer (`apps`, `workflows`, …).
3. If all files also share a second segment under that layer, append it (`apps/google`, `workflows/hud`).
4. If files span multiple layers, use `repo`.
5. Root-level configs (`README.md`, `requirements.txt`, `Dockerfile`) without other changes → `repo`.

## Automation

The `/commit` skill reads **only staged files** (`git diff --cached`), classifies type and scope using the rules above, drafts the subject, prints the message, and commits after you confirm. It never stages files for you. See [SKILLS-INVENTORY.md §`/commit`](SKILLS-INVENTORY.md#commit) for invocation details.
