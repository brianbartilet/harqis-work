"""
Shared pytest fixtures for agents/kanban tests.

Unit tests run fully offline (no API calls).
Integration tests require env vars and are marked @pytest.mark.integration.
"""

import pytest

from agents.projects.trello.models import (
    KanbanAttachment,
    KanbanCard,
    KanbanChecklist,
    KanbanChecklistItem,
    KanbanColumn,
)
from agents.projects.profiles.schema import (
    AgentProfile,
    ContextConfig,
    FilesystemPermission,
    GitPermission,
    HardwareConfig,
    LifecycleConfig,
    ModelConfig,
    NetworkPermission,
    PermissionsConfig,
    ToolsConfig,
)


# ── Card fixtures ─────────────────────────────────────────────────────────────

@pytest.fixture()
def sample_checklist():
    return KanbanChecklist(
        id="cl1",
        name="Steps",
        items=[
            KanbanChecklistItem(id="ci1", name="Read existing code", checked=False),
            KanbanChecklistItem(id="ci2", name="Write tests", checked=False),
            KanbanChecklistItem(id="ci3", name="Run pytest", checked=False),
        ],
    )


@pytest.fixture()
def sample_attachment():
    return KanbanAttachment(
        id="att1",
        name="spec.md",
        url="https://trello.com/attachments/att1",
        mime_type="text/markdown",
        bytes_size=1024,
    )


@pytest.fixture()
def sample_card(sample_checklist, sample_attachment):
    return KanbanCard(
        id="card123",
        title="Write a hello-world script",
        description="Create a Python script that prints Hello, World! and save it as hello.py",
        labels=["agent:code"],
        assignees=[],
        column="Backlog",
        url="https://trello.com/c/card123",
        checklists=[sample_checklist],
        attachments=[sample_attachment],
        custom_fields={"repo_url": "https://github.com/example/repo"},
    )


@pytest.fixture()
def minimal_card():
    return KanbanCard(
        id="min1",
        title="Simple task",
        description="Do something simple",
        labels=["agent:write"],
        assignees=[],
        column="Backlog",
        url="https://trello.com/c/min1",
    )


# ── Profile fixtures ──────────────────────────────────────────────────────────

@pytest.fixture()
def open_profile():
    """Profile with no restrictions — suitable for testing agent logic."""
    return AgentProfile(
        id="agent:test",
        name="Test Agent",
        model=ModelConfig(
            provider="anthropic",
            model_id="claude-haiku-4-5-20251001",
            max_tokens=1024,
        ),
        tools=ToolsConfig(allowed=[], denied=[]),
        permissions=PermissionsConfig(
            filesystem=FilesystemPermission(allow=[], deny=[]),
            network=NetworkPermission(allow=[], deny=[]),
            git=GitPermission(can_push=False),
        ),
        lifecycle=LifecycleConfig(auto_approve=True, timeout_minutes=5),
    )


@pytest.fixture()
def restricted_profile(tmp_path):
    """Profile with strict restrictions — for permission tests."""
    allowed_dir = str(tmp_path / "**")   # cross-platform temp dir glob
    denied_dir = str(tmp_path / "secrets" / "**")
    return AgentProfile(
        id="agent:restricted",
        name="Restricted Agent",
        tools=ToolsConfig(
            allowed=["read_file", "post_comment"],
            denied=["bash", "write_file"],
        ),
        permissions=PermissionsConfig(
            filesystem=FilesystemPermission(
                allow=[allowed_dir],
                deny=[denied_dir],
            ),
            network=NetworkPermission(
                allow=["api.anthropic.com"],
                deny=["*"],
            ),
            git=GitPermission(
                can_push=False,
                protected_branches=["main"],
            ),
        ),
    )


@pytest.fixture()
def code_profile():
    """Code agent profile loaded from the example YAML."""
    from pathlib import Path
    from agents.projects.profiles.schema import AgentProfile
    examples = Path(__file__).parent.parent / "profiles" / "examples"
    return AgentProfile.from_yaml(examples / "agent_code.yaml")
