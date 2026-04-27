"""
AgentContext — builds the structured prompt sent to the LLM from a KanbanCard.

All card data (description, checklists, custom fields, attachment text)
is assembled here into a single human-readable markdown string that the
agent receives as its first user message.

When a working_directory is provided the context also includes a lightweight
snapshot of the local repository (CLAUDE.md, existing apps, existing workflows)
so the agent understands what is already built and can reuse it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import requests

from agents.kanban.interface import KanbanCard

logger = logging.getLogger(__name__)

TEXT_MIME_PREFIXES = ("text/", "application/json", "application/xml", "application/yaml")


@dataclass
class AgentContext:
    card_id: str
    card_url: str
    prompt: str
    checklists: list = field(default_factory=list)
    params: dict[str, str] = field(default_factory=dict)
    file_contents: list[dict] = field(default_factory=list)
    repo_context: str = ""

    def to_prompt(self) -> str:
        parts: list[str] = []

        parts.append(f"# Task\n\n{self.prompt}")

        if self.params:
            param_lines = "\n".join(f"- **{k}**: {v}" for k, v in self.params.items() if v)
            if param_lines:
                parts.append(f"# Parameters\n\n{param_lines}")

        if self.checklists:
            cl_lines: list[str] = ["# Sub-tasks"]
            for cl in self.checklists:
                cl_lines.append(f"\n## {cl.name}")
                for item in cl.items:
                    tick = "[x]" if item.checked else "[ ]"
                    cl_lines.append(f"- {tick} {item.name}")
            parts.append("\n".join(cl_lines))

        if self.file_contents:
            att_lines: list[str] = ["# Attached Files"]
            for f in self.file_contents:
                att_lines.append(f'\n## {f["name"]}\n```\n{f["content"]}\n```')
            parts.append("\n".join(att_lines))

        if self.repo_context:
            parts.append(self.repo_context)

        parts.append(f"---\nCard: {self.card_url}  |  ID: {self.card_id}")

        return "\n\n".join(parts)


def build_card_context(
    card: KanbanCard,
    fetch_text_attachments: bool = True,
    max_attachment_bytes: int = 50_000,
    working_directory: Optional[str] = None,
) -> AgentContext:
    """
    Build an AgentContext from a KanbanCard.

    Text attachments under max_attachment_bytes are fetched and inlined.
    If working_directory is provided the context also includes a repository
    snapshot (CLAUDE.md, existing apps/workflows) for dependency awareness.
    """
    file_contents: list[dict] = []

    if fetch_text_attachments:
        for att in card.attachments:
            if not _is_text_mime(att.mime_type):
                continue
            if att.bytes_size and att.bytes_size > max_attachment_bytes:
                logger.debug("Skipping large attachment %s (%d bytes)", att.name, att.bytes_size)
                continue
            try:
                resp = requests.get(att.url, timeout=10)
                resp.raise_for_status()
                file_contents.append({"name": att.name, "content": resp.text})
            except Exception as e:
                logger.warning("Could not fetch attachment %s: %s", att.name, e)

    repo_context = ""
    if working_directory:
        repo_context = _build_repo_context(Path(working_directory))

    return AgentContext(
        card_id=card.id,
        card_url=card.url,
        prompt=card.description or card.title,
        checklists=card.checklists,
        params=card.custom_fields,
        file_contents=file_contents,
        repo_context=repo_context,
    )


def _build_repo_context(repo_root: Path) -> str:
    """
    Build a lightweight repository snapshot for agent context.

    Includes: CLAUDE.md (if present), existing app names, existing workflow names.
    Keeps output small — this is context priming, not a full directory listing.
    """
    if not repo_root.exists():
        return ""

    sections: list[str] = ["# Repository Context"]

    claude_md = repo_root / "CLAUDE.md"
    if claude_md.exists():
        try:
            content = claude_md.read_text(encoding="utf-8")[:3000]
            sections.append(f"## CLAUDE.md\n{content}")
        except OSError:
            pass

    apps_dir = repo_root / "apps"
    if apps_dir.is_dir():
        app_names = sorted(
            d.name for d in apps_dir.iterdir()
            if d.is_dir() and not d.name.startswith(".")
        )
        if app_names:
            sections.append("## Existing MCP Apps\n" + "\n".join(f"- {n}" for n in app_names))

    workflows_dir = repo_root / "workflows"
    if workflows_dir.is_dir():
        wf_names = sorted(
            d.name for d in workflows_dir.iterdir()
            if d.is_dir() and not d.name.startswith(".")
        )
        if wf_names:
            sections.append(
                "## Existing Workflows\n" + "\n".join(f"- {n}" for n in wf_names)
            )

    if len(sections) == 1:
        return ""
    return "\n\n".join(sections)


def _is_text_mime(mime: str) -> bool:
    if not mime:
        return False
    return any(mime.startswith(prefix) for prefix in TEXT_MIME_PREFIXES)
