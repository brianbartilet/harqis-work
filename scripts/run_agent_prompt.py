#!/usr/bin/env python3
"""
Run HARQIS agent prompts against the codebase using the Anthropic Claude API.
Reads a prompt from prompts/ (repo root), builds repo context, calls Claude,
and writes the result to the appropriate output file.

Usage:
    python scripts/run_agent_prompt.py --agent docs
    python scripts/run_agent_prompt.py --agent code_smells
    python scripts/run_agent_prompt.py --agent both
"""
import argparse
import os
import sys
from pathlib import Path
from datetime import datetime

import anthropic

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
MODEL = "claude-opus-4-6"
MAX_FILE_CHARS = 60_000   # per file guard — truncates beyond this
MAX_CONTEXT_CHARS = 180_000  # total context guard

SKIP_DIRS = {"__pycache__", ".git", "venv", ".venv", "node_modules",
             ".pytest_cache", ".mypy_cache", "dist", "build", ".eggs"}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def read_file(path: Path, max_chars: int = MAX_FILE_CHARS) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        if len(text) > max_chars:
            text = text[:max_chars] + f"\n\n... [file truncated at {max_chars:,} chars]"
        return text
    except Exception as exc:
        return f"[could not read file: {exc}]"


def dir_tree(root: Path, prefix: str = "", depth: int = 3) -> str:
    if depth < 0:
        return ""
    lines = []
    try:
        entries = sorted(root.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
    except PermissionError:
        return ""
    entries = [e for e in entries if e.name not in SKIP_DIRS and not e.name.endswith(".pyc")]
    for i, entry in enumerate(entries):
        connector = "└── " if i == len(entries) - 1 else "├── "
        lines.append(f"{prefix}{connector}{entry.name}")
        if entry.is_dir():
            extension = "    " if i == len(entries) - 1 else "│   "
            sub = dir_tree(entry, prefix + extension, depth - 1)
            if sub:
                lines.append(sub)
    return "\n".join(lines)


def collect_files(paths: list[str], per_file_max: int = MAX_FILE_CHARS) -> str:
    """Read a list of repo-relative file paths into a single formatted string."""
    parts = []
    for rel in paths:
        full = REPO_ROOT / rel
        if full.exists():
            content = read_file(full, per_file_max)
            lang = "python" if full.suffix == ".py" else "md" if full.suffix == ".md" else ""
            parts.append(f"### {rel}\n\n```{lang}\n{content}\n```")
        else:
            parts.append(f"### {rel}\n\n_[file not found]_")
    return "\n\n---\n\n".join(parts)

# ---------------------------------------------------------------------------
# Context builders
# ---------------------------------------------------------------------------

def build_docs_context() -> str:
    sections = []

    # 1. Current README + CLAUDE.md
    for name in ("README.md", "CLAUDE.md"):
        p = REPO_ROOT / name
        if p.exists():
            sections.append(f"## {name}\n\n```md\n{read_file(p)}\n```")

    # 2. Directory tree (depth 3)
    sections.append(f"## Repository Structure\n\n```\n{dir_tree(REPO_ROOT)}\n```")

    # 3. All app README files
    app_parts = []
    apps_dir = REPO_ROOT / "apps"
    if apps_dir.exists():
        for app in sorted(apps_dir.iterdir()):
            rp = app / "README.md"
            if rp.exists() and app.is_dir() and not app.name.startswith("."):
                app_parts.append(f"### apps/{app.name}/README.md\n\n{read_file(rp, 4_000)}")
    if app_parts:
        sections.append("## App READMEs\n\n" + "\n\n---\n\n".join(app_parts))

    # 4. All workflow README files
    wf_parts = []
    wf_dir = REPO_ROOT / "workflows"
    if wf_dir.exists():
        for wf in sorted(wf_dir.iterdir()):
            rp = wf / "README.md"
            if rp.exists() and wf.is_dir() and not wf.name.startswith("."):
                wf_parts.append(f"### workflows/{wf.name}/README.md\n\n{read_file(rp, 4_000)}")
    if wf_parts:
        sections.append("## Workflow READMEs\n\n" + "\n\n---\n\n".join(wf_parts))

    context = "\n\n---\n\n".join(sections)
    if len(context) > MAX_CONTEXT_CHARS:
        context = context[:MAX_CONTEXT_CHARS] + "\n\n... [context truncated]"
    return context


def build_code_smells_context() -> str:
    sections = []

    # 1. Existing CODE_SMELLS.md
    smells_path = REPO_ROOT / "CODE_SMELLS.md"
    if smells_path.exists():
        sections.append(f"## Existing CODE_SMELLS.md\n\n```md\n{read_file(smells_path)}\n```")

    # 2. Directory tree
    sections.append(f"## Repository Structure\n\n```\n{dir_tree(REPO_ROOT)}\n```")

    # 3. Key Python source files (most complex / most likely to have smells)
    key_files = [
        "workflows/purchases/tasks/tcg_mp_selling.py",
        "workflows/hud/tasks/hud_tcg.py",
        "workflows/hud/tasks/hud_logs.py",
        "workflows/hud/tasks/hud_gpt.py",
        "workflows/hud/tasks/hud_finance.py",
        "workflows/hud/tasks/hud_forex.py",
        "workflows/hud/tasks/hud_calendar.py",
        "workflows/hud/tasks/hud_utils.py",
        "workflows/hud/tasks/sections.py",
        "apps/rainmeter/references/helpers/config_builder.py",
        "apps/rainmeter/references/helpers/bangs.py",
        "apps/rainmeter/references/helpers/smart_profiles.py",
        "apps/tcg_mp/references/web/base_api_service.py",
        "apps/tcg_mp/references/web/api/order.py",
        "apps/echo_mtg/references/web/api/inventory.py",
        "workflows/desktop/tasks/capture.py",
        "workflows/desktop/tasks/commands.py",
        "workflows/purchases/helpers/helper.py",
        "workflows/config.py",
    ]
    sections.append("## Source Files\n\n" + collect_files(key_files, per_file_max=8_000))

    context = "\n\n---\n\n".join(sections)
    if len(context) > MAX_CONTEXT_CHARS:
        context = context[:MAX_CONTEXT_CHARS] + "\n\n... [context truncated]"
    return context

# ---------------------------------------------------------------------------
# Agent runner
# ---------------------------------------------------------------------------

AGENT_CONFIG = {
    "docs": {
        "prompt_file": "prompts/docs_agent.md",
        "output_file": "README.md",
        "context_fn": build_docs_context,
        "output_instruction": (
            "Output ONLY the complete, updated README.md content. "
            "Do not include any preamble, explanation, or markdown code fences wrapping the whole file. "
            "Write raw GitHub-flavored markdown exactly as it should appear in README.md."
        ),
    },
    "code_smells": {
        "prompt_file": "prompts/code_smells.md",
        "output_file": "CODE_SMELLS.md",
        "context_fn": build_code_smells_context,
        "output_instruction": (
            "Output ONLY the complete, updated CODE_SMELLS.md content. "
            "Do not include any preamble, explanation, or markdown code fences wrapping the whole file. "
            "Write raw GitHub-flavored markdown exactly as it should appear in CODE_SMELLS.md. "
            "Preserve the _DONE_ markers on issues that have already been fixed."
        ),
    },
}


def run_agent(agent: str) -> None:
    cfg = AGENT_CONFIG[agent]
    prompt_path = REPO_ROOT / cfg["prompt_file"]
    output_path = REPO_ROOT / cfg["output_file"]

    if not prompt_path.exists():
        print(f"ERROR: prompt file not found: {prompt_path}", file=sys.stderr)
        sys.exit(1)

    system_prompt = (
        prompt_path.read_text(encoding="utf-8")
        + "\n\n---\n\n## Output instruction\n\n"
        + cfg["output_instruction"]
    )

    print(f"\n{'='*60}")
    print(f"Agent : {agent}")
    print(f"Prompt: {cfg['prompt_file']}")
    print(f"Output: {cfg['output_file']}")

    context = cfg["context_fn"]()
    print(f"Context size: {len(context):,} chars")

    client = anthropic.Anthropic()

    response = client.messages.create(
        model=MODEL,
        max_tokens=8096,
        system=system_prompt,
        messages=[
            {
                "role": "user",
                "content": (
                    f"Here is the current repository context:\n\n{context}\n\n"
                    "Generate the complete updated output file now."
                ),
            }
        ],
    )

    output = response.content[0].text.strip()

    # Strip accidental outer code fence (```md ... ```) if Claude adds one
    if output.startswith("```"):
        first_newline = output.index("\n")
        output = output[first_newline + 1:]
        if output.endswith("```"):
            output = output[: output.rfind("```")].rstrip()

    output_path.write_text(output, encoding="utf-8")
    print(f"Written: {output_path.relative_to(REPO_ROOT)}  ({len(output):,} chars)")
    print(f"Tokens used: input={response.usage.input_tokens:,}  output={response.usage.output_tokens:,}")

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run HARQIS agent prompts via Anthropic Claude API"
    )
    parser.add_argument(
        "--agent",
        choices=["docs", "code_smells", "both"],
        required=True,
        help="Which agent to run",
    )
    args = parser.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ERROR: ANTHROPIC_API_KEY environment variable is not set.", file=sys.stderr)
        sys.exit(1)

    agents = ["docs", "code_smells"] if args.agent == "both" else [args.agent]
    for agent in agents:
        run_agent(agent)

    print(f"\nDone at {datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')}")


if __name__ == "__main__":
    main()
