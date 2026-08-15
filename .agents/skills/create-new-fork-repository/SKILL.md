---
name: create-new-fork-repository
description: Create a branded, reduced harqis-work derivative as a fresh local Git repository, copy approved local secrets for regression testing without tracking them, validate the target, and publish it to GitHub. Use when creating a client, business, or team fork rather than a GitHub history-preserving fork.
---

# Create a branded fork repository

Use the bundled deterministic generator. Do not reproduce its copy, secret, Git, or
publication logic manually.

## Required clarification

Before running anything, confirm in one message:

- exact repository name and user-facing brand name;
- one-paragraph description and absolute target directory;
- GitHub owner and visibility (default `private`);
- apps to retain;
- skills to retain;
- whether the optional HFL capability is required;
- any extra workflow categories beyond `.template`.

Show the resolved dependency closure and get confirmation. `antropic` is mandatory because
the retained agent framework imports its provider. HFL is optional; when selected it brings
its complete workflow/app dependency bundle and `create-new-ingest-source-hfl`. Selected
skills automatically bring declared skill dependencies such as `update-docs` and
`sync-host`.

Defaults are maintained by `scripts/create_fork.py`. The principal defaults are:

- apps: `.template`, `antropic`, `git`, `github`, `google_apps`, `google_drive`, `trello`;
- workflows: `.template` only;
- the generic operational skill set described by the generator; HFL ingest is conditional.

## Run

From the source repository root:

```powershell
python .agents/skills/create-new-fork-repository/scripts/create_fork.py `
  --repo-name "<repository-name>" `
  --brand-name "<Brand Name>" `
  --description "<description>" `
  --target-dir "<absolute-target>" `
  --owner "<github-owner>" `
  --visibility private
```

Use `--dry-run` to print the complete plan without writing. Use `--no-publish` only when
the user explicitly wants a local-only result. Test/evaluation runs may also use
`--skip-build`, `--skip-tests`, `--skip-live-tests`, and `--skip-docker-build`; do not use
those flags for a production fork presented as validated. The normal gate runs the offline
suite first and then credential-backed `integration` tests using the copied local secrets.

The generator:

1. requires a Git source and refuses a dirty source unless `--allow-dirty` was explicit;
2. copies only tracked allowlisted files and never copies source `.git` metadata;
3. creates the reduced workflows, app catalogue, profiles, frontend capabilities, MCP,
   scripts, docs, README, branding, and `fork-manifest.toml`;
4. initializes a fresh target Git repository;
5. copies `.env/**`, `frontend/.env`, and `machines.local.toml` locally when present;
6. proves those files are ignored and absent from the Git index;
7. builds Python/frontend dependencies, validates Compose/Docker, and runs target tests;
8. scans the staged tree for secret paths and credential shapes;
9. commits, creates the confirmed GitHub repository, and pushes `main` without force.

If any validation fails, stop. Leave the local target intact for diagnosis and do not create
or push the GitHub repository. Never print secret contents.

## Validation after changing this skill

```powershell
python -m pytest .agents/skills/create-new-fork-repository/tests -q
python C:\Users\brian\.codex\skills\.system\skill-creator\scripts\quick_validate.py `
  .agents/skills/create-new-fork-repository
```
