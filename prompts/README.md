# Prompts

## Description

- Repository for AI prompt templates used across workflows.
- All prompts have been moved to their respective workflow subdirectories.
- The files here are redirect stubs pointing to the new locations.

## Current Files (redirect stubs)

| File | Moved To |
|------|----------|
| `daily_summary.md` | `workflows/desktop/prompts/daily_summary.md` |
| `weekly_summary.md` | `workflows/desktop/prompts/weekly_summary.md` |
| `desktop_analysis.md` | `workflows/hud/prompts/desktop_analysis.md` |

## Prompt Locations

Prompts are now co-located with the workflow that uses them:

```
workflows/
├── desktop/
│   └── prompts/
│       ├── daily_summary.md    # Prompt for generate_daily_desktop_summary task
│       └── weekly_summary.md   # Prompt for generate_weekly_desktop_summary task
└── hud/
    └── prompts/
        └── desktop_analysis.md # Prompt for get_desktop_logs task
```

## Adding New Prompts

Place new prompt markdown files in the `prompts/` subdirectory of the workflow that uses them:

```
workflows/<workflow_name>/prompts/<prompt_name>.md
```

Load in a task:

```python
from pathlib import Path

PROMPT_PATH = Path(__file__).parent.parent / 'prompts' / 'my_prompt.md'
prompt = PROMPT_PATH.read_text(encoding='utf-8')
```

## Notes

- Do not add new prompt files to this directory — use the workflow-specific `prompts/` folder instead.
- This folder may be removed in a future cleanup once all references are updated.
