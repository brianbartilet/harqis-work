import inspect
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from workflows.hfl.tasks import summarize
from workflows.hfl.tasks.summarize import (
    _render_rollup,
    _rollup_filename,
    _rollup_tags,
)


def _plain_task():
    return inspect.unwrap(summarize.summarize_hfl_week.run)


def test_historical_task_identity_and_prompt(monkeypatch, tmp_path):
    monkeypatch.setattr(summarize, "resolve_corpus_dir", lambda: tmp_path)
    (tmp_path / "2026-09-27.md").write_text("## 2026-09-27 09:00\nMoment: test\n")
    calls = []
    indexed = []
    client = SimpleNamespace(base_client=True, send_messages=lambda **kw: (
        calls.append(kw) or SimpleNamespace(content=[SimpleNamespace(text="summary")])
    ))
    monkeypatch.setattr(summarize, "get_anthropic_config", lambda _: None)
    monkeypatch.setattr(summarize, "BaseApiServiceAnthropic", lambda _: client)
    monkeypatch.setattr(summarize, "index_hfl_entry", lambda entry, **kw: indexed.append((entry, kw)))
    result = _plain_task()(end_date="2026-09-27", resolve_references=False)
    assert Path(result["summary_path"]).name == "2026-W39-rollup.md"
    assert indexed[0][0].when.date() == date(2026, 9, 27)
    assert indexed[0][1]["doc_id"] == "hfl-weekly-2026-W39"
    assert "2026-09-21" in calls[0]["messages"][0]["content"]
    assert result["window_end"] == "2026-09-27"


def test_oversized_base_fails_before_reference_fetch_or_model(monkeypatch, tmp_path):
    monkeypatch.setattr(summarize, "resolve_corpus_dir", lambda: tmp_path)
    (tmp_path / "2026-09-27.md").write_text("## 2026-09-27\nMoment: " + "界" * 50000)
    def forbidden(*args, **kwargs):
        pytest.fail("oversized input must fail before external work")
    monkeypatch.setattr(summarize, "_build_reference_appendix", forbidden)
    monkeypatch.setattr(summarize, "BaseApiServiceAnthropic", forbidden)
    with pytest.raises(ValueError, match="prompt.*budget"):
        _plain_task()(end_date="2026-09-27")
    assert not (tmp_path / "2026-W39-rollup.md").exists()


def test_reference_budget_is_global_including_metadata(monkeypatch):
    entries = [_entry("2026-09-27", "#test") for _ in range(10)]
    for i, entry in enumerate(entries):
        entry["body"] += f"References:\n  - https://example.com/{i}\n"
    calls = []
    def resolve(refs, **kw):
        calls.append(kw["max_total"])
        return [{"ref": refs[0], "ok": True, "reason": "text", "content": "x" * kw["max_total"]}]
    monkeypatch.setattr(summarize, "_resolve_references", resolve)
    appendix, _, _ = summarize._build_reference_appendix(entries, timeout=1, max_bytes=1000, max_total=1000)
    assert len(appendix.encode("utf8")) <= 1000
    assert len(calls) == 1


def test_collect_historical_window_includes_archive_and_excludes_outside(monkeypatch, tmp_path):
    monkeypatch.setattr(summarize, "resolve_corpus_dir", lambda: tmp_path)
    for day in ("2026-09-20", "2026-09-21", "2026-09-27", "2026-09-28"):
        folder = tmp_path / "2026" / "Sep"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{day}.md").write_text(f"## {day} 09:00\nMoment: test\n")
    hidden = tmp_path / ".backup"
    hidden.mkdir()
    (hidden / "2026-09-22.md").write_text("## 2026-09-22\nMoment: hidden\n")
    entries, files = summarize._collect_window(7, end_date=date(2026, 9, 27))
    assert [e["date"] for e in entries] == ["2026-09-21", "2026-09-27"]
    assert len(files) == 2


@pytest.mark.parametrize("days", [0, -1, 1.5, True])
def test_invalid_window_rejected(days):
    with pytest.raises(ValueError):
        summarize._collect_window(days, end_date=date(2026, 9, 27))


def _entry(date: str, tags: str) -> dict[str, str]:
    return {
        "date": date,
        "header": f"{date} 09:00",
        "body": (
            "Moment: A useful moment\n"
            "What happened: Something happened\n"
            f"Tags: {tags}\n"
        ),
    }


def test_rollup_tags_include_week_metadata_and_source_entry_tags():
    entries = [
        _entry("2026-07-20", "#jira #testing"),
        _entry("2026-07-21", "#notes #testing"),
    ]

    tags = _rollup_tags(entries, 2026, 30)

    assert tags == (
        "weekly",
        "summary",
        "2026-W30",
        "jira",
        "notes",
        "testing",
    )


def test_rollup_filename_uses_iso_year_and_zero_padded_week():
    assert _rollup_filename(2026, 3) == "2026-W03-rollup.md"


def test_render_rollup_adds_searchable_tags_section():
    entries = [_entry("2026-07-21", "#jira #notes")]

    rendered = _render_rollup(
        "## Themes\n- A recurring theme",
        entries,
        [Path("2026-07-21.md")],
        window_days=7,
        iso_year=2026,
        iso_week=30,
    )

    assert rendered.startswith("# Weekly rollup — 2026-W30\n")
    assert rendered.index("## Themes") < rendered.index("## Tags")
    assert rendered.endswith(
        "## Tags\nTags: #weekly #summary #2026-W30 #jira #notes\n\n"
    )
