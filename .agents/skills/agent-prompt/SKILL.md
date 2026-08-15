---
name: agent-prompt
description: Run a shared AI-agent prompt from agents/prompts against the current repository, including code-smell and documentation audits. Use when the user names a prompt or asks to list the repository's available shared prompts.
---

# Run an agent prompt

Treat `$ARGUMENTS` as a prompt name without `.md`.

1. Resolve the repository root with `git rev-parse --show-toplevel`.
2. If no name was supplied, list `agents/prompts/*.md` with a one-line description and stop.
3. Read `agents/prompts/<name>.md`. Never look for the removed root `prompts/` directory.
4. If the prompt only points at an optional workflow that is absent, report that the
   capability was not selected in this fork and stop cleanly.
5. Execute the prompt against the current codebase and present source-backed results.

For `code_smells`, give each issue a file/line and suggested fix. For `docs_agent`, list
specific stale or missing documentation. Do not modify files unless the prompt or user
explicitly requests implementation.
