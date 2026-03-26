import os


def load_prompt(name: str, prompts_dir: str = None) -> str:
    """
    Load a prompt from a .md file as plain text.

    This is the shared base utility. Each workflow's prompts/__init__.py
    calls this with its own directory so prompts stay co-located with
    the workflow that owns them.

    Args:
        name:        Filename without extension (e.g. 'daily_summary').
        prompts_dir: Absolute path to the prompts directory to search.
                     Defaults to this shared prompts/ directory at the repo root.

    Returns:
        Prompt string ready to send to an LLM.

    Raises:
        FileNotFoundError: If the prompt file does not exist.
    """
    base = prompts_dir or os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(base, f"{name}.md")
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()
