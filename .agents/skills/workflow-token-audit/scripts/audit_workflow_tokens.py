#!/usr/bin/env python3
"""Estimate scheduled HARQIS workflow model/API usage from active beat entries.

This is a static estimator. It imports exported `workflows/*/tasks_config.py`
dicts after loading local env, counts schedule cadence, then applies transparent
heuristics based on kwargs/task names. It does not call external APIs.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import sys
from dataclasses import dataclass, asdict
from datetime import timedelta
from pathlib import Path
from typing import Any


DAY_NAME_TO_CELERY = {
    "sun": 0,
    "sunday": 0,
    "mon": 1,
    "monday": 1,
    "tue": 2,
    "tues": 2,
    "tuesday": 2,
    "wed": 3,
    "wednesday": 3,
    "thu": 4,
    "thur": 4,
    "thurs": 4,
    "thursday": 4,
    "fri": 5,
    "friday": 5,
    "sat": 6,
    "saturday": 6,
}

MODEL_DEFAULTS = {
    # Conservative defaults for scheduled summarization tasks when no cap is set.
    "claude-haiku-4-5-20251001": {"input": 3500, "output": 700},
    "claude-sonnet-4-6": {"input": 6000, "output": 1500},
    "sonnet": {"input": 6000, "output": 1500},
    "haiku": {"input": 3500, "output": 700},
    "whisper-1": {"input": 0, "output": 0},
}

EMBED_TOKENS_PER_ITEM = {
    "ingest_confluence_pages": 1200,
    "ingest_jira_issues": 900,
    "ingest_gdrive_docs": 1200,
    "ingest_notion_pages": 900,
    "ingest_github_repos": 700,
}

# USD per 1M tokens. Keep this table small and editable; pass --pricing-json
# when provider pricing changes or when using private enterprise rates.
PRICING_USD_PER_MTOK = {
    "models": {
        "claude-haiku-4-5-20251001": {"input": 1.00, "output": 5.00},
        "claude-sonnet-4-6": {"input": 3.00, "output": 15.00},
        "whisper-1": {"input": 0.00, "output": 0.00},
    },
    "families": {
        "haiku": {"input": 1.00, "output": 5.00},
        "sonnet": {"input": 3.00, "output": 15.00},
        "claude": {"input": 3.00, "output": 15.00},
        "gpt": {"input": 1.00, "output": 4.00},
        "gemini": {"input": 0.35, "output": 1.05},
    },
    "embeddings": {
        "gemini": 0.15,
        "openai": 0.10,
    },
}


@dataclass
class Estimate:
    workflow: str
    schedule_key: str
    task: str
    queue: str
    runs_per_day: float
    runs_per_week: float
    runs_per_month: float
    providers: list[str]
    models: list[str]
    api_calls_per_run: int
    input_tokens_per_run: int
    output_tokens_per_run: int
    embed_tokens_per_run: int
    model_usd_per_run: float
    embed_usd_per_run: float
    total_usd_per_run: float
    notes: list[str]

    @property
    def total_tokens_per_run(self) -> int:
        return self.input_tokens_per_run + self.output_tokens_per_run + self.embed_tokens_per_run

    def rollup(self) -> dict[str, float]:
        return {
            "daily_api_calls": self.api_calls_per_run * self.runs_per_day,
            "weekly_api_calls": self.api_calls_per_run * self.runs_per_week,
            "monthly_api_calls": self.api_calls_per_run * self.runs_per_month,
            "daily_tokens": self.total_tokens_per_run * self.runs_per_day,
            "weekly_tokens": self.total_tokens_per_run * self.runs_per_week,
            "monthly_tokens": self.total_tokens_per_run * self.runs_per_month,
            "daily_usd": self.total_usd_per_run * self.runs_per_day,
            "weekly_usd": self.total_usd_per_run * self.runs_per_week,
            "monthly_usd": self.total_usd_per_run * self.runs_per_month,
        }


def repo_root() -> Path:
    p = Path.cwd().resolve()
    while p != p.parent:
        if (p / "workflows").is_dir() and (p / "apps_config.yaml").exists():
            return p
        p = p.parent
    raise SystemExit("Run from the harqis-work repo root or a child directory")


def bootstrap_env(root: Path) -> None:
    sys.path.insert(0, str(root))
    try:
        from scripts.deploy import load_env_into_os, load_machine_config, machine_env_vars

        load_env_into_os()
        os.environ.setdefault("APP_CONFIG_FILE", "apps_config.yaml")
        os.environ.setdefault("WORKFLOW_CONFIG", "workflows.config")
        os.environ.update(machine_env_vars(load_machine_config(None)))
    except Exception as exc:  # noqa: BLE001
        print(f"warning: env bootstrap failed: {exc}", file=sys.stderr)
        os.environ.setdefault("APP_CONFIG_FILE", "apps_config.yaml")
        os.environ.setdefault("WORKFLOW_CONFIG", "workflows.config")


def import_task_config(path: Path) -> Any:
    module_name = "_audit_" + "_".join(path.with_suffix("").parts[-3:])
    spec = importlib.util.spec_from_file_location(module_name, path)
    if not spec or not spec.loader:
        raise RuntimeError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def active_schedule_dicts(module: Any) -> list[tuple[str, dict[str, Any]]]:
    found: list[tuple[str, dict[str, Any]]] = []
    for name, value in vars(module).items():
        if name.startswith("_") or not isinstance(value, dict) or not value:
            continue
        if all(isinstance(k, str) and k.startswith("run-job--") for k in value):
            found.append((name, value))
    return found


def parse_cron_atom(atom: str, min_value: int, max_value: int, names: dict[str, int] | None = None) -> set[int]:
    atom = atom.strip().lower()
    names = names or {}
    if atom in {"*", ""}:
        return set(range(min_value, max_value + 1))
    if atom.startswith("*/"):
        step = int(atom[2:])
        return set(range(min_value, max_value + 1, step))
    if "/" in atom:
        base, step_s = atom.split("/", 1)
        step = int(step_s)
        base_vals = sorted(parse_cron_atom(base, min_value, max_value, names))
        return set(base_vals[::step])
    if "-" in atom:
        left, right = atom.split("-", 1)
        start = names.get(left, int(left) if left.isdigit() else min_value)
        end = names.get(right, int(right) if right.isdigit() else max_value)
        if start <= end:
            return set(range(start, end + 1))
        return set(range(start, max_value + 1)) | set(range(min_value, end + 1))
    if atom in names:
        return {names[atom]}
    return {int(atom)}


def parse_cron_field(raw: Any, min_value: int, max_value: int, names: dict[str, int] | None = None) -> set[int]:
    if raw is None:
        return set(range(min_value, max_value + 1))
    if isinstance(raw, (set, frozenset, list, tuple)):
        result: set[int] = set()
        for item in raw:
            if isinstance(item, int):
                result.add(item)
            else:
                result |= parse_cron_field(str(item), min_value, max_value, names)
        return {v for v in result if min_value <= v <= max_value}
    text = str(raw).strip().strip("'")
    result: set[int] = set()
    for part in text.split(","):
        result |= parse_cron_atom(part, min_value, max_value, names)
    return {v for v in result if min_value <= v <= max_value}


def original_field(schedule: Any, name: str, fallback: str) -> Any:
    return getattr(schedule, f"_orig_{name}", getattr(schedule, name, fallback))


def cadence(schedule: Any) -> tuple[float, float, float, str]:
    if isinstance(schedule, timedelta):
        seconds = max(schedule.total_seconds(), 1)
        daily = 86400.0 / seconds
        return daily, daily * 7, daily * 30, f"every {seconds:g}s"

    cls_name = schedule.__class__.__name__.lower()
    if "crontab" in cls_name:
        minutes = parse_cron_field(original_field(schedule, "minute", "*"), 0, 59)
        hours = parse_cron_field(original_field(schedule, "hour", "*"), 0, 23)
        dows = parse_cron_field(original_field(schedule, "day_of_week", "*"), 0, 6, DAY_NAME_TO_CELERY)
        dom_raw = str(original_field(schedule, "day_of_month", "*")).strip()
        moy_raw = str(original_field(schedule, "month_of_year", "*")).strip()
        per_matching_day = len(minutes) * len(hours)
        weekly = per_matching_day * len(dows)
        daily = weekly / 7.0
        monthly = weekly * (30.0 / 7.0)
        if dom_raw not in {"*", "' * '"} or moy_raw not in {"*", "' * '"}:
            doms = parse_cron_field(original_field(schedule, "day_of_month", "*"), 1, 31)
            months = parse_cron_field(original_field(schedule, "month_of_year", "*"), 1, 12)
            monthly = per_matching_day * len(doms) * (len(months) / 12.0)
            daily = monthly / 30.0
            weekly = daily * 7.0
        return daily, weekly, monthly, "crontab"

    return 0.0, 0.0, 0.0, f"unknown schedule {schedule!r}"


def provider_from_cfg_key(key: str) -> str:
    k = key.lower()
    if "anthropic" in k or "antropic" in k:
        return "anthropic"
    if "openai" in k or "open_ai" in k:
        return "openai"
    if "gemini" in k:
        return "gemini"
    if "grok" in k:
        return "grok"
    if "perplexity" in k:
        return "perplexity"
    if "gmail" in k:
        return "gmail"
    if "jira" in k:
        return "jira"
    if "confluence" in k:
        return "confluence"
    if "gdrive" in k or "google" in k:
        return "google"
    return k



def provider_from_model(model: str) -> str:
    lower = model.lower()
    if "claude" in lower:
        return "anthropic"
    if "gpt" in lower or "whisper" in lower or "openai" in lower:
        return "openai"
    if "gemini" in lower:
        return "gemini"
    if "grok" in lower:
        return "grok"
    return "model"

def load_pricing(path: str | None) -> None:
    if not path:
        return
    data = json.loads(Path(path).read_text())
    for key in ("models", "families", "embeddings"):
        PRICING_USD_PER_MTOK.setdefault(key, {}).update(data.get(key, {}))


def model_pricing(model: str) -> dict[str, float]:
    lower = model.lower()
    direct = PRICING_USD_PER_MTOK.get("models", {}).get(model)
    if direct:
        return direct
    for key, value in PRICING_USD_PER_MTOK.get("families", {}).items():
        if key in lower:
            return value
    return {"input": 0.0, "output": 0.0}


def embedding_pricing(provider: str) -> float:
    return float(PRICING_USD_PER_MTOK.get("embeddings", {}).get(provider, 0.0))


def model_defaults(model: str) -> dict[str, int]:
    lower = model.lower()
    for key, value in MODEL_DEFAULTS.items():
        if key in lower:
            return value
    return {"input": 3000, "output": 800}


def task_basename(task: str) -> str:
    return task.rsplit(".", 1)[-1]


def estimate_entry(workflow: str, schedule_key: str, entry: dict[str, Any]) -> Estimate:
    task = entry.get("task", "")
    kwargs = entry.get("kwargs", {}) or {}
    options = entry.get("options", {}) or {}
    daily, weekly, monthly, schedule_note = cadence(entry.get("schedule"))
    providers: set[str] = set()
    models: set[str] = set()
    notes = [schedule_note]

    for key, value in kwargs.items():
        if key.startswith("cfg_id__"):
            providers.add(provider_from_cfg_key(str(value)))
    for key in ("model", "whisper_model"):
        if kwargs.get(key):
            models.add(str(kwargs[key]))

    name = task_basename(task)
    input_tokens = 0
    output_tokens = 0
    embed_tokens = 0
    model_usd = 0.0
    embed_usd = 0.0
    api_calls = max(1, len([p for p in providers if p not in {"anthropic", "openai", "gemini", "grok", "perplexity"}]))

    if models:
        for model in models:
            providers.add(provider_from_model(model))
            defaults = model_defaults(model)
            input_count = defaults["input"]
            output_count = int(kwargs.get("max_tokens") or defaults["output"])
            input_tokens += input_count
            output_tokens += output_count
            prices = model_pricing(model)
            model_usd += (input_count / 1_000_000.0) * float(prices.get("input", 0.0))
            model_usd += (output_count / 1_000_000.0) * float(prices.get("output", 0.0))
            api_calls += 1
        notes.append("model token estimate uses configured model/max_tokens plus heuristic input size")

    if name in EMBED_TOKENS_PER_ITEM:
        if "max_pages" in kwargs:
            items = int(kwargs.get("max_pages") or 0)
        elif "max_issues" in kwargs:
            items = int(kwargs.get("max_issues") or 0)
        elif "max_files" in kwargs:
            items = int(kwargs.get("max_files") or 0)
        elif "per_repo_limit" in kwargs and kwargs.get("repos"):
            items = int(kwargs.get("per_repo_limit") or 0) * len(kwargs.get("repos") or [])
        else:
            items = 100
        embed_tokens += items * EMBED_TOKENS_PER_ITEM[name]
        embed_provider = os.environ.get("HARQIS_KNOWLEDGE_EMBED_PROVIDER", "gemini") or "gemini"
        providers.add(embed_provider)
        embed_usd += (embed_tokens / 1_000_000.0) * embedding_pricing(embed_provider)
        api_calls += max(1, math.ceil(items / 50))
        notes.append(f"embedding estimate: {items} items x {EMBED_TOKENS_PER_ITEM[name]} tokens/item")

    return Estimate(
        workflow=workflow,
        schedule_key=schedule_key,
        task=task,
        queue=str(getattr(options.get("queue", "default"), "value", options.get("queue", "default"))),
        runs_per_day=daily,
        runs_per_week=weekly,
        runs_per_month=monthly,
        providers=sorted(providers),
        models=sorted(models),
        api_calls_per_run=api_calls,
        input_tokens_per_run=input_tokens,
        output_tokens_per_run=output_tokens,
        embed_tokens_per_run=embed_tokens,
        model_usd_per_run=model_usd,
        embed_usd_per_run=embed_usd,
        total_usd_per_run=model_usd + embed_usd,
        notes=notes,
    )


def discover(root: Path) -> list[Estimate]:
    estimates: list[Estimate] = []
    for path in sorted((root / "workflows").glob("*/tasks_config.py")):
        workflow = path.parent.name
        try:
            module = import_task_config(path)
        except Exception as exc:  # noqa: BLE001
            print(f"warning: skipped {path}: {exc}", file=sys.stderr)
            continue
        for _dict_name, schedule in active_schedule_dicts(module):
            for key, entry in schedule.items():
                estimates.append(estimate_entry(workflow, key, entry))
    return estimates


def summarize(estimates: list[Estimate]) -> dict[str, Any]:
    totals = {
        "daily_api_calls": 0.0,
        "weekly_api_calls": 0.0,
        "monthly_api_calls": 0.0,
        "daily_tokens": 0.0,
        "weekly_tokens": 0.0,
        "monthly_tokens": 0.0,
        "daily_usd": 0.0,
        "weekly_usd": 0.0,
        "monthly_usd": 0.0,
    }
    by_provider: dict[str, dict[str, float]] = {}
    by_model: dict[str, dict[str, float]] = {}

    for est in estimates:
        roll = est.rollup()
        for key, value in roll.items():
            totals[key] += value
        providers = est.providers or ["unknown"]
        paid_providers = [
            p for p in providers
            if p in PRICING_USD_PER_MTOK.get("embeddings", {})
            or p in {"anthropic", "openai", "gemini", "grok", "model"}
        ] or providers
        for provider in providers:
            bucket = by_provider.setdefault(
                provider,
                {"daily_tokens": 0.0, "weekly_tokens": 0.0, "monthly_tokens": 0.0,
                 "daily_api_calls": 0.0, "daily_usd": 0.0, "monthly_usd": 0.0},
            )
            bucket["daily_tokens"] += roll["daily_tokens"] / len(providers)
            bucket["weekly_tokens"] += roll["weekly_tokens"] / len(providers)
            bucket["monthly_tokens"] += roll["monthly_tokens"] / len(providers)
            bucket["daily_api_calls"] += roll["daily_api_calls"] / len(providers)
            if provider in paid_providers:
                bucket["daily_usd"] += roll["daily_usd"] / len(paid_providers)
                bucket["monthly_usd"] += roll["monthly_usd"] / len(paid_providers)
        for model in est.models:
            bucket = by_model.setdefault(model, {"daily_tokens": 0.0, "weekly_tokens": 0.0, "monthly_tokens": 0.0, "daily_usd": 0.0, "monthly_usd": 0.0})
            bucket["daily_tokens"] += roll["daily_tokens"]
            bucket["weekly_tokens"] += roll["weekly_tokens"]
            bucket["monthly_tokens"] += roll["monthly_tokens"]
            bucket["daily_usd"] += roll["daily_usd"]
            bucket["monthly_usd"] += roll["monthly_usd"]

    return {"totals": totals, "by_provider": by_provider, "by_model": by_model}


def fmt_num(value: float) -> str:
    if abs(value) >= 1000:
        return f"{value:,.0f}"
    if value == int(value):
        return str(int(value))
    return f"{value:.2f}"


def print_markdown(estimates: list[Estimate], summary: dict[str, Any], top: int) -> None:
    print("# HARQIS Workflow Token/API Usage Estimate")
    print()
    print("Static estimate from active exported `workflows/*/tasks_config.py` beat entries. Values are approximate; verify provider dashboards for billing truth.")
    print()
    totals = summary["totals"]
    print("## Rollup")
    print("| Window | API calls | Tokens | Est. USD |")
    print("| --- | ---: | ---: | ---: |")
    print(f"| Daily | {fmt_num(totals['daily_api_calls'])} | {fmt_num(totals['daily_tokens'])} | ${totals['daily_usd']:.2f} |")
    print(f"| Weekly | {fmt_num(totals['weekly_api_calls'])} | {fmt_num(totals['weekly_tokens'])} | ${totals['weekly_usd']:.2f} |")
    print(f"| Monthly | {fmt_num(totals['monthly_api_calls'])} | {fmt_num(totals['monthly_tokens'])} | ${totals['monthly_usd']:.2f} |")
    print()
    print("## By Provider")
    print("| Provider | Daily calls | Daily tokens | Monthly tokens | Monthly USD |")
    print("| --- | ---: | ---: | ---: | ---: |")
    for provider, values in sorted(summary["by_provider"].items(), key=lambda kv: kv[1]["monthly_tokens"], reverse=True):
        print(f"| {provider} | {fmt_num(values['daily_api_calls'])} | {fmt_num(values['daily_tokens'])} | {fmt_num(values['monthly_tokens'])} | ${values['monthly_usd']:.2f} |")
    print()
    print("## Top Scheduled Token Contributors")
    print("| Task | Workflow | Runs/week | Providers | Models | Tokens/run | USD/run | Monthly USD | Monthly tokens | Notes |")
    print("| --- | --- | ---: | --- | --- | ---: | ---: | ---: | ---: | --- |")
    ranked = sorted(estimates, key=lambda e: e.rollup()["monthly_tokens"], reverse=True)[:top]
    for est in ranked:
        print(
            f"| `{est.schedule_key}` | {est.workflow} | {fmt_num(est.runs_per_week)} | "
            f"{', '.join(est.providers) or '-'} | {', '.join(est.models) or '-'} | "
            f"{fmt_num(est.total_tokens_per_run)} | ${est.total_usd_per_run:.4f} | "
            f"${est.rollup()['monthly_usd']:.2f} | {fmt_num(est.rollup()['monthly_tokens'])} | "
            f"{'; '.join(est.notes[:2])} |"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit JSON instead of Markdown")
    parser.add_argument("--top", type=int, default=25, help="number of top contributors in Markdown output")
    parser.add_argument("--pricing-json", help="optional JSON file overriding USD per 1M token pricing")
    args = parser.parse_args()

    root = repo_root()
    bootstrap_env(root)
    load_pricing(args.pricing_json)
    estimates = discover(root)
    summary = summarize(estimates)
    if args.json:
        print(json.dumps({"summary": summary, "tasks": [asdict(e) | e.rollup() for e in estimates]}, indent=2, default=str))
    else:
        print_markdown(estimates, summary, args.top)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())



