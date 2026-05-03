"""
Tests for WorkspaceOrchestrator (multi-board) and TrelloWorkspace (auto-discovery).

All HTTP / Trello calls are mocked — no real API traffic.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from hamcrest import assert_that, equal_to, has_length

from agents.projects.orchestrator.workspace import WorkspaceOrchestrator
from agents.projects.profiles.registry import ProfileRegistry
from agents.projects.security.secret_store import SecretStore
from agents.projects.trello.workspace import TrelloBoard, TrelloWorkspace


# ── TrelloWorkspace ──────────────────────────────────────────────────────────

@pytest.mark.smoke
def test_trello_workspace_filters_archived_boards_by_default():
    fake_response = MagicMock()
    fake_response.json.return_value = [
        {"id": "b1", "name": "Active board", "shortLink": "abc",
         "closed": False, "url": "https://trello.com/b/b1"},
    ]
    fake_response.raise_for_status = MagicMock()

    with patch("agents.projects.trello.workspace.requests.get", return_value=fake_response) as mock_get:
        ws = TrelloWorkspace(api_key="K", token="T", workspace_id="org123")
        boards = ws.list_boards()

    assert_that(boards, has_length(1))
    assert_that(boards[0].id, equal_to("b1"))
    # Default filter=open passed to Trello.
    assert_that(mock_get.call_args.kwargs["params"]["filter"], equal_to("open"))


@pytest.mark.smoke
def test_trello_workspace_name_filter_keeps_only_matches():
    fake_response = MagicMock()
    fake_response.json.return_value = [
        {"id": "b1", "name": "agent-engineering", "shortLink": "a", "closed": False, "url": ""},
        {"id": "b2", "name": "personal sandbox",  "shortLink": "b", "closed": False, "url": ""},
        {"id": "b3", "name": "agent-research",    "shortLink": "c", "closed": False, "url": ""},
    ]
    fake_response.raise_for_status = MagicMock()

    with patch("agents.projects.trello.workspace.requests.get", return_value=fake_response):
        ws = TrelloWorkspace(api_key="K", token="T", workspace_id="org")
        boards = ws.list_boards(name_filter="agent-")

    assert_that([b.id for b in boards], equal_to(["b1", "b3"]))


@pytest.mark.smoke
def test_trello_workspace_name_exclude_drops_matches():
    fake_response = MagicMock()
    fake_response.json.return_value = [
        {"id": "b1", "name": "engineering", "shortLink": "a", "closed": False, "url": ""},
        {"id": "b2", "name": "sandbox",     "shortLink": "b", "closed": False, "url": ""},
    ]
    fake_response.raise_for_status = MagicMock()

    with patch("agents.projects.trello.workspace.requests.get", return_value=fake_response):
        ws = TrelloWorkspace(api_key="K", token="T", workspace_id="org")
        boards = ws.list_boards(name_exclude=["sandbox"])

    assert_that([b.id for b in boards], equal_to(["b1"]))


# ── WorkspaceOrchestrator ────────────────────────────────────────────────────

def _make_workspace_orch(*, workspace=None, board_ids=None, dry_run=True):
    """Bare WorkspaceOrchestrator with mocked deps for unit tests."""
    return WorkspaceOrchestrator(
        client=MagicMock(name="client"),
        registry=MagicMock(spec=ProfileRegistry),
        api_key="apk",
        secret_store=SecretStore(),
        os_labels={"os:any"},
        workspace=workspace,
        board_ids=board_ids,
        profile_filter=None,
        poll_interval=1,
        blocked_poll_interval=10,
        dry_run=dry_run,
        audit_log_path=Path("logs/test_audit.jsonl"),
    )


@pytest.mark.smoke
def test_constructor_requires_workspace_or_board_ids():
    with pytest.raises(ValueError):
        WorkspaceOrchestrator(
            client=MagicMock(),
            registry=MagicMock(),
            api_key="x",
            secret_store=SecretStore(),
            os_labels=set(),
        )


@pytest.mark.smoke
def test_static_board_ids_skip_discovery():
    """When no workspace is configured, discover_boards returns the static list verbatim."""
    orch = _make_workspace_orch(board_ids=["b1", "b2"])
    assert_that(orch.discover_boards(), equal_to(["b1", "b2"]))


@pytest.mark.smoke
def test_workspace_discovery_returns_board_ids_from_org():
    workspace = MagicMock(spec=TrelloWorkspace)
    workspace.list_boards.return_value = [
        TrelloBoard(id="b1", name="A", short_link="x", closed=False, url=""),
        TrelloBoard(id="b2", name="B", short_link="y", closed=False, url=""),
    ]
    orch = _make_workspace_orch(workspace=workspace)
    assert_that(orch.discover_boards(), equal_to(["b1", "b2"]))


@pytest.mark.smoke
def test_ensure_board_orchestrators_adds_new_boards():
    """Newly discovered boards get a BoardOrchestrator created on the fly."""
    orch = _make_workspace_orch(board_ids=["b1", "b2"])
    orch._ensure_board_orchestrators(["b1", "b2", "b3"])
    assert_that(set(orch._board_orchestrators.keys()), equal_to({"b1", "b2", "b3"}))


@pytest.mark.smoke
def test_ensure_board_orchestrators_drops_disappeared_boards():
    """Boards that fall out of the workspace are removed (closed/moved)."""
    orch = _make_workspace_orch(board_ids=["b1", "b2"])
    orch._ensure_board_orchestrators(["b1", "b2"])
    orch._ensure_board_orchestrators(["b1"])  # b2 closed
    assert_that(set(orch._board_orchestrators.keys()), equal_to({"b1"}))


@pytest.mark.smoke
def test_poll_once_iterates_every_board():
    """A single poll_once call should poll every board orchestrator that exists."""
    orch = _make_workspace_orch(board_ids=["b1", "b2", "b3"])
    orch._ensure_board_orchestrators(orch.discover_boards())

    for board_orch in orch._board_orchestrators.values():
        board_orch.poll_intake = MagicMock(return_value=2)
        board_orch.poll_resumes = MagicMock(return_value=0)

    total = orch.poll_once()
    assert_that(total, equal_to(6))  # 2 cards × 3 boards
    for board_orch in orch._board_orchestrators.values():
        board_orch.poll_intake.assert_called_once()
        board_orch.poll_resumes.assert_called_once()


@pytest.mark.smoke
def test_discovery_failure_falls_back_to_known_boards():
    """If a transient workspace API failure happens, the orchestrator should
    keep polling the boards it already knows about rather than going dark."""
    workspace = MagicMock(spec=TrelloWorkspace)
    workspace.list_boards.side_effect = RuntimeError("API down")
    orch = _make_workspace_orch(workspace=workspace)

    # Pre-seed two known boards (as if a previous successful discovery had run).
    orch._ensure_board_orchestrators(["b1", "b2"])

    discovered = orch.discover_boards()
    assert_that(set(discovered), equal_to({"b1", "b2"}))


@pytest.mark.smoke
def test_profile_clients_cache_is_shared_across_boards():
    """Mode A: the same per-profile TrelloClient cache is used by every board
    orchestrator so a profile's Trello account login isn't re-built per board."""
    orch = _make_workspace_orch(board_ids=["b1", "b2"])
    orch._ensure_board_orchestrators(orch.discover_boards())

    b1 = orch._board_orchestrators["b1"]
    b2 = orch._board_orchestrators["b2"]
    # Same dict instance in both BoardOrchestrators.
    assert_that(b1._profile_clients is b2._profile_clients, equal_to(True))
    assert_that(b1._profile_clients is orch._profile_clients, equal_to(True))
