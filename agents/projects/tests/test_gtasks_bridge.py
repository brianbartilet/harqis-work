"""
Unit tests for `agents/projects/integrations/gtasks_bridge.py`.

The bridge talks to two real services (Google Tasks via the discovery client,
Trello via plain HTTP). These tests mock both — the goal is to validate the
state-machine, the title-prefix algebra, and the binding lifecycle.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agents.projects.integrations.gtasks_bridge import (
    Binding,
    GTasksAccount,
    GTasksBridge,
    _apply_prefix,
    _load_state,
    _save_state,
    _strip_prefix,
)
from agents.projects.orchestrator.lists import Lists


# ── Pure helpers ─────────────────────────────────────────────────────────────

class TestPrefixHelpers:
    def test_strip_prefix_removes_leading_marker(self):
        assert _strip_prefix("|Pending| Walk the dog") == "Walk the dog"

    def test_strip_prefix_idempotent_when_no_prefix(self):
        assert _strip_prefix("Walk the dog") == "Walk the dog"

    def test_strip_prefix_handles_empty_and_none(self):
        assert _strip_prefix("") == ""
        assert _strip_prefix(None) == ""

    def test_apply_prefix_replaces_existing(self):
        assert _apply_prefix("|Pending| Walk the dog", "In Progress") == "|In Progress| Walk the dog"

    def test_apply_prefix_with_none_strips(self):
        assert _apply_prefix("|Pending| Walk the dog", None) == "Walk the dog"

    def test_apply_prefix_idempotent_for_same_status(self):
        once = _apply_prefix("Walk the dog", "Pending")
        twice = _apply_prefix(once, "Pending")
        assert once == twice == "|Pending| Walk the dog"


# ── State persistence ────────────────────────────────────────────────────────

class TestStatePersistence:
    def test_load_returns_empty_when_file_missing(self, tmp_path: Path):
        assert _load_state(tmp_path / "missing.json") == {}

    def test_round_trip(self, tmp_path: Path):
        path = tmp_path / "state.json"
        state = {
            "g1": Binding(
                gtask_id="g1", tasklist_id="t1", account="personal",
                card_id="c1", last_status=Lists.IN_PROGRESS,
            ),
        }
        _save_state(path, state)
        loaded = _load_state(path)
        assert loaded == state

    def test_load_skips_corrupt_file(self, tmp_path: Path):
        path = tmp_path / "state.json"
        path.write_text("{ not valid json", encoding="utf-8")
        assert _load_state(path) == {}

    def test_load_drops_entries_missing_required_fields(self, tmp_path: Path):
        path = tmp_path / "state.json"
        path.write_text(
            json.dumps({"bindings": [
                {"gtask_id": "", "card_id": "c1"},  # empty id → drop
                {"gtask_id": "g2", "card_id": "c2", "tasklist_id": "t2",
                 "account": "x", "last_status": ""},
            ]}),
            encoding="utf-8",
        )
        loaded = _load_state(path)
        assert "g2" in loaded
        assert "" not in loaded


# ── Bridge fixture ───────────────────────────────────────────────────────────

@pytest.fixture
def make_bridge(tmp_path):
    """Factory: builds a GTasksBridge with mocked Google + Trello clients."""

    def _build(*, accounts=None, enricher=None):
        gtasks = MagicMock()
        gtasks.list_task_lists.return_value = [
            {"id": "TL1", "title": "Agents Tasks"},
            {"id": "TL2", "title": "Some other list"},
        ]
        gtasks.list_tasks.return_value = []
        account = GTasksAccount(name="personal", config_key="GOOGLE_TASKS")
        accounts = accounts or [(account, gtasks)]

        trello = MagicMock()
        trello._auth = {"key": "k", "token": "t"}
        trello._timeout = 5
        trello._resolve_col_id.return_value = "COLREADY"

        bridge = GTasksBridge(
            accounts=accounts,
            list_name="Agents Tasks",
            board_id="BOARD",
            intake_column=Lists.READY,
            trello=trello,
            state_path=tmp_path / "state.json",
            enricher=enricher,
        )
        return bridge, gtasks, trello

    return _build


# ── Inbound flow ─────────────────────────────────────────────────────────────

class TestInbound:
    def test_creates_card_for_new_gtask(self, make_bridge):
        bridge, gtasks, trello = make_bridge()
        gtasks.list_tasks.return_value = [
            {"id": "G1", "title": "Walk the dog", "notes": "", "status": "needsAction"},
        ]
        with patch("agents.projects.integrations.gtasks_bridge.requests") as mock_requests:
            response = MagicMock()
            response.json.return_value = {"id": "C1", "shortUrl": "https://trello.com/c/abc"}
            response.raise_for_status.return_value = None
            mock_requests.post.return_value = response

            count = bridge.sync_inbound()

        assert count == 1
        assert "G1" in bridge.state
        assert bridge.state["G1"].card_id == "C1"
        assert bridge.state["G1"].last_status == Lists.READY
        # Card creation hit POST /1/cards with the right column.
        call_kwargs = mock_requests.post.call_args.kwargs
        assert "/1/cards" in mock_requests.post.call_args.args[0]
        assert call_kwargs["params"]["idList"] == "COLREADY"
        # gtask was updated with the |Pending| prefix and a Trello: line.
        gtasks.update_task.assert_called_once()
        update_kwargs = gtasks.update_task.call_args.args[1]
        assert update_kwargs["title"] == "|Pending| Walk the dog"
        assert "Trello: https://trello.com/c/abc" in update_kwargs["notes"]

    def test_skips_already_bound_gtask(self, make_bridge):
        bridge, gtasks, trello = make_bridge()
        # Pretend G1 is already bound to C1.
        bridge.state["G1"] = Binding(
            gtask_id="G1", tasklist_id="TL1", account="personal",
            card_id="C1", last_status=Lists.READY,
        )
        gtasks.list_tasks.return_value = [
            {"id": "G1", "title": "Walk the dog", "status": "needsAction"},
        ]
        with patch("agents.projects.integrations.gtasks_bridge.requests"):
            count = bridge.sync_inbound()
        assert count == 0
        gtasks.update_task.assert_not_called()

    def test_skips_completed_gtasks(self, make_bridge):
        bridge, gtasks, trello = make_bridge()
        gtasks.list_tasks.return_value = [
            {"id": "G_done", "title": "Old task", "status": "completed"},
        ]
        with patch("agents.projects.integrations.gtasks_bridge.requests") as r:
            count = bridge.sync_inbound()
            r.post.assert_not_called()
        assert count == 0

    def test_skips_account_without_matching_list(self, make_bridge):
        bridge, gtasks, trello = make_bridge()
        gtasks.list_task_lists.return_value = [
            {"id": "TL_other", "title": "Different name"},
        ]
        with patch("agents.projects.integrations.gtasks_bridge.requests"):
            count = bridge.sync_inbound()
        assert count == 0
        gtasks.list_tasks.assert_not_called()

    def test_strips_existing_prefix_before_using_title(self, make_bridge):
        bridge, gtasks, trello = make_bridge()
        gtasks.list_tasks.return_value = [
            {"id": "G1", "title": "|Old| Walk the dog", "status": "needsAction"},
        ]
        with patch("agents.projects.integrations.gtasks_bridge.requests") as mock_requests:
            response = MagicMock()
            response.json.return_value = {"id": "C1", "shortUrl": "u"}
            response.raise_for_status.return_value = None
            mock_requests.post.return_value = response
            bridge.sync_inbound()
        # Trello card name should be the clean title.
        post_kwargs = mock_requests.post.call_args.kwargs
        assert post_kwargs["params"]["name"] == "Walk the dog"


# ── Outbound flow ────────────────────────────────────────────────────────────

class TestOutbound:
    def _bind(self, bridge, *, last_status=Lists.READY):
        bridge.state["G1"] = Binding(
            gtask_id="G1", tasklist_id="TL1", account="personal",
            card_id="C1", last_status=last_status,
        )

    def _mock_card_list(self, list_name):
        """Builds a `requests.get` response mock returning {'name': list_name}."""
        resp = MagicMock()
        resp.status_code = 200
        resp.raise_for_status.return_value = None
        resp.json.return_value = {"name": list_name}
        return resp

    def test_pending_to_in_progress_updates_title(self, make_bridge):
        bridge, gtasks, _ = make_bridge()
        self._bind(bridge, last_status=Lists.PENDING)
        gtasks.get_task.return_value = {"title": "|Pending| Walk the dog"}

        with patch("agents.projects.integrations.gtasks_bridge.requests") as mock_requests:
            mock_requests.get.return_value = self._mock_card_list(Lists.IN_PROGRESS)
            count = bridge.sync_outbound()

        assert count == 1
        update_args = gtasks.update_task.call_args.args
        assert update_args[1] == {"title": "|In Progress| Walk the dog"}
        assert bridge.state["G1"].last_status == Lists.IN_PROGRESS

    def test_done_marks_completed_and_drops_binding(self, make_bridge):
        bridge, gtasks, _ = make_bridge()
        self._bind(bridge, last_status=Lists.IN_PROGRESS)
        gtasks.get_task.return_value = {"title": "|In Progress| Walk the dog"}

        with patch("agents.projects.integrations.gtasks_bridge.requests") as mock_requests:
            mock_requests.get.return_value = self._mock_card_list(Lists.DONE)
            count = bridge.sync_outbound()

        assert count == 1
        update_kwargs = gtasks.update_task.call_args.args[1]
        assert update_kwargs == {"title": "Walk the dog", "status": "completed"}
        assert "G1" not in bridge.state  # binding dropped after terminal transition

    def test_in_review_is_skipped(self, make_bridge):
        bridge, gtasks, _ = make_bridge()
        self._bind(bridge, last_status=Lists.IN_PROGRESS)
        gtasks.get_task.return_value = {"title": "|In Progress| Walk the dog"}

        with patch("agents.projects.integrations.gtasks_bridge.requests") as mock_requests:
            mock_requests.get.return_value = self._mock_card_list(Lists.IN_REVIEW)
            count = bridge.sync_outbound()

        # No title update for In Review.
        assert count == 0
        gtasks.update_task.assert_not_called()
        # But last_status updates so we don't re-evaluate.
        assert bridge.state["G1"].last_status == Lists.IN_REVIEW

    def test_blocked_writes_blocked_prefix(self, make_bridge):
        bridge, gtasks, _ = make_bridge()
        self._bind(bridge, last_status=Lists.IN_PROGRESS)
        gtasks.get_task.return_value = {"title": "|In Progress| Walk the dog"}

        with patch("agents.projects.integrations.gtasks_bridge.requests") as mock_requests:
            mock_requests.get.return_value = self._mock_card_list(Lists.BLOCKED)
            count = bridge.sync_outbound()

        assert count == 1
        assert gtasks.update_task.call_args.args[1] == {"title": "|Blocked| Walk the dog"}

    def test_failed_writes_failed_prefix_and_keeps_binding(self, make_bridge):
        bridge, gtasks, _ = make_bridge()
        self._bind(bridge, last_status=Lists.IN_PROGRESS)
        gtasks.get_task.return_value = {"title": "|In Progress| Walk the dog"}

        with patch("agents.projects.integrations.gtasks_bridge.requests") as mock_requests:
            mock_requests.get.return_value = self._mock_card_list(Lists.FAILED)
            bridge.sync_outbound()

        assert "G1" in bridge.state  # NOT terminal — could be retried
        assert gtasks.update_task.call_args.args[1] == {"title": "|Failed| Walk the dog"}

    def test_card_404_drops_binding(self, make_bridge):
        bridge, gtasks, _ = make_bridge()
        self._bind(bridge)
        not_found = MagicMock()
        not_found.status_code = 404

        with patch("agents.projects.integrations.gtasks_bridge.requests") as mock_requests:
            mock_requests.get.return_value = not_found
            bridge.sync_outbound()

        assert "G1" not in bridge.state
        gtasks.update_task.assert_not_called()

    def test_no_change_when_status_matches_last_status(self, make_bridge):
        bridge, gtasks, _ = make_bridge()
        self._bind(bridge, last_status=Lists.IN_PROGRESS)
        with patch("agents.projects.integrations.gtasks_bridge.requests") as mock_requests:
            mock_requests.get.return_value = self._mock_card_list(Lists.IN_PROGRESS)
            count = bridge.sync_outbound()
        assert count == 0
        gtasks.get_task.assert_not_called()
        gtasks.update_task.assert_not_called()


# ── Notes merging ────────────────────────────────────────────────────────────

class TestNotesMerge:
    def test_appends_trello_link(self):
        merged = GTasksBridge._merge_notes("user notes here", "https://trello.com/c/abc")
        assert merged == "user notes here\nTrello: https://trello.com/c/abc"

    def test_replaces_existing_trello_line(self):
        original = "user notes\nTrello: https://trello.com/c/old"
        merged = GTasksBridge._merge_notes(original, "https://trello.com/c/new")
        assert merged == "user notes\nTrello: https://trello.com/c/new"

    def test_empty_notes(self):
        merged = GTasksBridge._merge_notes("", "https://trello.com/c/x")
        assert merged == "Trello: https://trello.com/c/x"
