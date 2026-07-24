"""Tests for the Trello activity -> HFL ingest source."""

from datetime import date

import pytest

import workflows.hfl.tasks.ingest_trello as it


def _action(
    action_id: str,
    when: str,
    *,
    action_type: str = "createCard",
    creator: str = "member-1",
    board_id: str = "board-1",
    card_name: str = "Ship the ingest",
) -> dict:
    return {
        "id": action_id,
        "type": action_type,
        "date": when,
        "idMemberCreator": creator,
        "memberCreator": {"id": creator, "username": "brianbartilet"},
        "data": {
            "board": {"id": board_id, "name": "HARQIS Work"},
            "list": {"id": "list-1", "name": "In Progress"},
            "card": {
                "id": "card-1",
                "shortLink": "abc123",
                "name": card_name,
            },
        },
    }


class _FakeTrello:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def get_me(self):
        return {"id": "member-1", "username": "brianbartilet"}

    def get_member_boards(self, **_kwargs):
        return [{
            "id": "board-1",
            "name": "HARQIS Work",
            "shortLink": "board123",
            "idOrganization": "org-1",
        }, {
            "id": "personal-board",
            "name": "Personal",
            "shortLink": "personal123",
            "idOrganization": None,
        }]

    def get_member_organizations(self, **_kwargs):
        return [{"id": "org-1", "name": "harqis", "displayName": "HARQIS"}]

    def get_member_actions(self, *, before=None, **kwargs):
        self.calls.append({"before": before, **kwargs})
        return list(self.pages.get(before, []))


@pytest.mark.smoke
def test_periods_cover_previous_calendar_year_and_all():
    today = date(2026, 7, 24)
    assert it.resolve_trello_window(period="last year", today=today) == (
        date(2025, 1, 1),
        date(2025, 12, 31),
        "last-year",
    )
    assert it.resolve_trello_window(period="last 30 days", today=today) == (
        date(2026, 6, 25),
        date(2026, 7, 24),
        "last-30-days",
    )
    assert it.resolve_trello_window(period="all", today=today) == (
        None,
        date(2026, 7, 24),
        "all",
    )
    assert it.resolve_trello_window(window_days=1, today=today) == (
        date(2026, 7, 23),
        date(2026, 7, 23),
        "previous-1-day(s)",
    )


@pytest.mark.smoke
def test_collector_paginates_filters_author_and_workspace():
    first = [
        _action("a1", "2026-07-24T10:00:00Z"),
        _action("a2", "2026-07-23T10:00:00Z", creator="butler"),
    ]
    second = [
        _action("a3", "2026-07-22T10:00:00Z"),
    ]
    service = _FakeTrello({None: first, "a2": second})

    result = it.collect_trello_activity(
        since=date(2026, 7, 22),
        until=date(2026, 7, 24),
        service=service,
        workspaces="harqis",
        page_size=2,
    )

    assert [action["id"] for action in result["actions"]] == ["a3", "a1"]
    assert result["pages"] == 2
    assert result["scanned"] == 3
    assert result["workspace_filter"] == ["harqis"]
    assert result["actions"][0]["references"][0].endswith("#action-a3")


@pytest.mark.smoke
def test_personal_workspace_requires_personal_selector():
    personal = _action(
        "personal-1",
        "2026-07-24T10:00:00Z",
        board_id="personal-board",
    )
    service = _FakeTrello({None: [personal]})
    excluded = it.collect_trello_activity(
        since=date(2026, 7, 24),
        until=date(2026, 7, 24),
        service=service,
        workspaces="harqis",
    )
    included = it.collect_trello_activity(
        since=date(2026, 7, 24),
        until=date(2026, 7, 24),
        service=_FakeTrello({None: [personal]}),
        workspaces="personal",
    )
    assert excluded["action_count"] == 0
    assert included["action_count"] == 1


@pytest.mark.smoke
def test_distiller_raw_fallback_is_readable_without_api():
    service = _FakeTrello({None: [_action("a1", "2026-07-24T10:00:00Z")]})
    action = it.collect_trello_activity(
        since=date(2026, 7, 24),
        until=date(2026, 7, 24),
        service=service,
    )["actions"][0]
    result = it.distill_trello_activity(action, synthesize=False)
    assert result["moment"] == "Created “Ship the ingest”"
    assert "HARQIS Work" in result["what_happened"]
    assert result["tags"][:2] == ["trello", "card"]
    assert result["synthesized"] is False


@pytest.mark.smoke
def test_comment_fallback_redacts_emails_and_credentials():
    raw = _action(
        "comment-1",
        "2026-07-24T10:00:00Z",
        action_type="commentCard",
    )
    raw["data"]["text"] = (
        "Ask owner@example.com; api_key=super-secret-value "
        "and Authorization: Bearer abcdefghijklmnopqrstuvwxyz."
    )
    action = it.collect_trello_activity(
        since=date(2026, 7, 24),
        until=date(2026, 7, 24),
        service=_FakeTrello({None: [raw]}),
    )["actions"][0]
    result = it.distill_trello_activity(action, synthesize=False)
    assert "owner@example.com" not in result["what_happened"]
    assert "super-secret-value" not in result["what_happened"]
    assert "abcdefghijklmnopqrstuvwxyz" not in result["what_happened"]
    assert "<redacted-email>" in result["what_happened"]


@pytest.mark.smoke
def test_missing_credentials_is_clean_noop(monkeypatch):
    monkeypatch.setattr(it, "_credentials_present", lambda: False)
    monkeypatch.setattr(
        it,
        "ApiServiceTrelloMembers",
        lambda _config: pytest.fail("Trello client must not initialize"),
    )
    result = it.ingest_trello_activity()
    assert result["entries_written"] == 0
    assert result["skipped"] == "no credentials"


@pytest.mark.smoke
def test_task_submits_one_entry_per_action_with_stable_ids(monkeypatch):
    service = _FakeTrello({
        None: [_action("action-123", "2026-07-24T10:00:00Z")],
    })
    monkeypatch.setattr(it, "_credentials_present", lambda: True)
    monkeypatch.setattr(it, "ApiServiceTrelloMembers", lambda _config: service)
    submitted = []

    def fake_submit(entry, **kwargs):
        submitted.append((entry, kwargs))
        return {
            "delivery": "persisted",
            "path": "corpus/2026-07-24.md",
            "duplicate": False,
            "indexed": True,
        }

    monkeypatch.setattr(it, "submit_hfl_entry", fake_submit)
    result = it.ingest_trello_activity(
        since="2026-07-24",
        until="2026-07-24",
        synthesize=False,
    )

    assert result["entries_written"] == 1
    entry, kwargs = submitted[0]
    assert entry.when.isoformat().endswith("+08:00")
    assert entry.source == "trello"
    assert entry.references[0].endswith("#action-action-123")
    assert kwargs["source"] == "trello"
    assert kwargs["dedup_key"] == "trello:action-123"
    assert kwargs["es_doc_id"] == "trello-action-action-123"


@pytest.mark.skip(
    reason="Manual only — live Trello, optional Anthropic, corpus, and Elasticsearch"
)
def test_full_pipeline_live():
    it.ingest_trello_activity(period="last 30 days")
