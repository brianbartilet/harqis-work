# agents/prompts

Shared AI prompt templates for all agents in the `agents/` package.
This is the canonical prompts location — it supersedes the repo-root `prompts/` directory.

## Structure

```
agents/prompts/
├── kanban_agent_default.md   # Default system prompt for BaseKanbanAgent
├── code_smells.md            # Code review prompt
├── desktop_analysis.md       # Desktop log analysis prompt
├── docs_agent.md             # Documentation agent prompt
└── <generated>/              # Agent-generated prompts written via save_prompt()
```

Workflow-specific prompts remain co-located with each workflow:

```
workflows/<workflow>/prompts/<name>.md
```

## Usage

```python
# Load a shared prompt
from agents.prompts import load_prompt
text = load_prompt("kanban_agent_default")

# Load a workflow-local prompt
from workflows.hud.prompts import load_prompt
text = load_prompt("desktop_analysis")

# Save a generated prompt (agents write here)
from agents.prompts import save_prompt
save_prompt("my_generated_prompt", content)
```

## Adding prompts

- **Shared / reusable prompts** → add a `.md` file here
- **Workflow-specific prompts** → add to `workflows/<workflow>/prompts/`
- **Agent-generated prompts** → use `save_prompt()` which writes here by default
- Never hardcode multi-line prompt strings in Python source — put them in `.md` files

## Migration note

`prompts/` at the repo root is now a backwards-compatibility shim that re-exports
`load_prompt` and `save_prompt` from this package. Update old imports to:
```python
from agents.prompts import load_prompt
```
