Run an AI agent prompt from the `prompts/` directory against the codebase.

The argument $ARGUMENTS is the prompt name without extension (e.g. `code_smells`, `docs_agent`, `desktop_analysis`).

Steps:
1. Read the prompt file at `prompts/$ARGUMENTS.md`.
2. Execute the prompt against the current codebase context.
3. Present the results clearly, noting:
   - For `code_smells`: list each issue with file:line and a suggested fix
   - For `docs_agent`: list documentation gaps or stale docs
   - For `desktop_analysis`: summarise the activity log insights

If $ARGUMENTS is empty, list all available prompts in `prompts/` with a one-line description of each.
