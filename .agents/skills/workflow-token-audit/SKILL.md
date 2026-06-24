---
name: workflow-token-audit
description: Estimate API calls, model/token exposure, embedding usage, and configured AI models for active harqis-work workflow schedules. Use when asked to audit scheduled workflow cost, API/token usage, daily/weekly/monthly usage rollups, model inventory, provider usage, or high-cost Celery Beat tasks under workflows/*/tasks_config.py.
---

# Workflow Token Audit

Estimate scheduled API/model usage and approximate USD cost from active HARQIS workflow beat entries.

## Quick Start

Run from the repo root:

```powershell
python .agents\skills\workflow-token-audit\scripts\audit_workflow_tokens.py --top 25
```

For machine-readable output:

```powershell
python .agents\skills\workflow-token-audit\scripts\audit_workflow_tokens.py --json
```

To override built-in USD pricing, pass a JSON file:

```powershell
python .agents\skills\workflow-token-audit\scripts\audit_workflow_tokens.py --pricing-json pricing.local.json
```

Example override shape:

```json
{
  "models": {
    "claude-haiku-4-5-20251001": {"input": 1.0, "output": 5.0}
  },
  "families": {
    "sonnet": {"input": 3.0, "output": 15.0}
  },
  "embeddings": {
    "gemini": 0.15
  }
}
```

All prices are USD per 1M tokens.

The script loads `.env/apps.env` and machine env with `scripts.deploy` before importing task configs, so env-gated schedules such as `WORKFLOW_KNOWLEDGE` are estimated using the current host configuration.

## What It Reports

- Active exported beat entries from `workflows/*/tasks_config.py`; parked dicts beginning with `_` are ignored unless their entries are exported by env-gated code.
- Runs per day, week, and month from `crontab` or `timedelta` schedules.
- API providers inferred from `cfg_id__*` kwargs, task names, and model names.
- Configured models from `model` and `whisper_model` kwargs.
- Estimated API calls, tokens, and USD per run, then daily/weekly/monthly rollups.
- Top scheduled token contributors.

## Interpretation Rules

Treat numbers as planning estimates, not billing truth. The script does not execute tasks or call provider dashboards.

- Model tasks use configured `max_tokens` when present; otherwise they use conservative defaults by model family.
- Embedding ingestors estimate tokens and USD from scope kwargs such as `max_pages`, `max_issues`, `max_files`, or repo limits.
- External non-model API call counts are lower-bound estimates from configured service IDs.
- Broadcast queues are counted by schedule emission, not by number of subscribed workers. If a broadcast queue has multiple workers, mention that real cluster-wide calls may multiply.
- Monthly means 30-day normalized usage. Weekly means 7-day normalized usage.
- Built-in pricing is a local planning table, not a live pricing feed. Override it for current public prices or private enterprise rates.

## Recommended Review Flow

1. Run the Markdown audit.
2. Read the `Rollup` table for daily, weekly, and monthly exposure.
3. Review `By Provider` for Anthropic/Gemini/OpenAI/API concentration.
4. Review `Top Scheduled Token Contributors` for the highest scheduled cost drivers.
5. If needed, run `--json` and filter by `workflow`, `provider`, or `model` in a separate script or `jq`-style tool.
6. For any surprisingly expensive task, inspect its `workflows/<name>/tasks_config.py` entry and check `schedule`, `kwargs`, `model`, `max_tokens`, and source caps.

## Common Follow-Ups

- To reduce LLM spend, lower schedule frequency, lower `max_tokens`, switch model, or disable scheduled summaries.
- To reduce embedding spend, lower `max_pages` / `max_issues`, add source filters, or increase incremental windows such as CQL/JQL date filters.
- For Knowledge Radar, check `HARQIS_KNOWLEDGE_*` env vars because those alter the active exported schedule.

## Validation

After editing the script or skill, run:

```powershell
python -m py_compile .agents\skills\workflow-token-audit\scripts\audit_workflow_tokens.py
python C:\Users\brian\.codex\skills\.system\skill-creator\scripts\quick_validate.py .agents\skills\workflow-token-audit
python .agents\skills\workflow-token-audit\scripts\audit_workflow_tokens.py --top 10
```

