"""Manifesto content loader."""

from __future__ import annotations

from services.markdown import render_markdown
from web import REPO_ROOT


MANIFESTO_PATH = REPO_ROOT / "docs" / "MANIFESTO.md"


def load_manifesto():
    try:
        source = MANIFESTO_PATH.read_text(encoding="utf-8")
    except OSError:
        source = "# HARQIS Work\n\nThe manifesto is currently unavailable."
    return render_markdown(source)
