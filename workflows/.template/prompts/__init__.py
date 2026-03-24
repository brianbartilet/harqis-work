import os
from workflows.prompts import load_prompt as _load

_DIR = os.path.dirname(os.path.abspath(__file__))


def load_prompt(name: str) -> str:
    """Load a prompt from workflows/.template/prompts/<name>.md."""
    return _load(name, prompts_dir=_DIR)
