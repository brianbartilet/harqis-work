"""
agents/prompts — shared prompt library for all agents in the agents/ package.

This supersedes the repo-root prompts/ directory. Workflow prompts that
previously imported from `prompts` should now import from `agents.prompts`.

Each workflow/agent's local prompts/__init__.py re-exports load_prompt
pointing at its own subdirectory, using this module as the base loader.

Usage:
    # Load a shared prompt
    from agents.prompts import load_prompt
    text = load_prompt("code_smells")

    # Load a local prompt (from a workflow or agent's own prompts dir)
    from workflows.hud.prompts import load_prompt
    text = load_prompt("daily_summary")

    # Save a generated prompt
    from agents.prompts import save_prompt
    save_prompt("my_generated_prompt", content)
"""

import os
from pathlib import Path


def load_prompt(name: str, prompts_dir: str = None) -> str:
    """
    Load a prompt from a .md file as plain text.

    Args:
        name:        Filename without extension (e.g. 'code_smells').
        prompts_dir: Absolute path to the prompts directory to search.
                     Defaults to this agents/prompts/ directory.

    Returns:
        Prompt string ready to send to an LLM.

    Raises:
        FileNotFoundError: If the prompt file does not exist.
    """
    base = prompts_dir or os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(base, f"{name}.md")
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()


def save_prompt(name: str, content: str, prompts_dir: str = None) -> Path:
    """
    Write a generated prompt to a .md file in agents/prompts/.

    All generated prompts must go here — never write raw strings inline
    in agent code when the prompt is reusable or agent-generated.

    Args:
        name:        Filename without extension.
        content:     Prompt text to write.
        prompts_dir: Directory to write into. Defaults to agents/prompts/.

    Returns:
        Path of the written file.
    """
    base = prompts_dir or os.path.dirname(os.path.abspath(__file__))
    path = Path(base) / f"{name}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding='utf-8')
    return path
