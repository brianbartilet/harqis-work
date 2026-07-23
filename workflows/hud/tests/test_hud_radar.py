"""
Tests for `workflows/hud/tasks/hud_radar.show_daily_radar` and the
data-gathering helpers in `workflows/hud/tasks/daily_radar_agent`.

Layout:
  1. Workflow (integration) tests first — call the real task with the live
     configs. Hit Gmail / Calendar / Tasks / Trello / ES / Anthropic and
     require valid creds in `.env/apps.env`.
  2. Unit / function tests for the pure formatting helpers — fully offline,
     using fixture dicts that mirror the real collector outputs.
"""

import os
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from workflows.hud.tasks.daily_radar_agent import (
    ANALYSIS_WINDOW_HOURS,
    _ensure_list_of_dicts,
    _format_calendar,
    _format_emails,
    _format_failed_jobs,
    _format_github_prs,
    _format_jira,
    _format_last_location,
    _format_tasks,
    _format_trello,
    _parse_gmail_date,
    _resolve_trello_board_ids,
    format_inputs_as_prompt_text,
    looks_like_commitment,
    read_desktop_dump_tail,
    summarise_inputs,
    wrap_preserving_breaks,
)


# ── Unit / function — task decorator wiring ───────────────────────────────────


def test__init_meter_overwrites_dump_per_tick():
    """Regression: the radar is a fresh 12-hour mirror, not a rolling log.

    `prepend_if_exists=True` (DESKTOP LOGS's setting) would push every new
    snapshot on top of the prior one; the marquee would then scroll through
    messages older than the strict cutoff. The decorator MUST overwrite.
    """
    from workflows.hud.tasks.hud_radar import show_daily_radar
    # The @init_meter decorator stores its config on the wrapped function
    # via core.utilities.resources.decorators; the underlying inner uses the
    # closure's `prepend_if_exists`. We assert by introspecting the source
    # so a future edit can't silently flip it back to True.
    import inspect
    src = inspect.getsource(show_daily_radar)
    assert "prepend_if_exists=False" in src, (
        "show_daily_radar must overwrite dump.txt (prepend_if_exists=False); "
        "found a different setting — see the rolling-log regression in CR."
    )


def test__radar_uses_fixed_height():
    """Layout uses a fixed visible-line cap (not the dynamic JIRA-BOARD
    shape). The 19-line default is approximately 20% taller than the prior
    16-line footprint. If this needs to change, update the constant AND the
    beat-schedule kwargs in lockstep."""
    from workflows.hud.tasks.hud_radar import DAILY_RADAR_MAX_HUD_LINES
    from workflows.hud.tasks_config import WORKFLOWS_HUD

    assert DAILY_RADAR_MAX_HUD_LINES == 19
    assert (
        WORKFLOWS_HUD["run-job--show_daily_radar"]["kwargs"]["max_hud_lines"]
        == DAILY_RADAR_MAX_HUD_LINES
    )
    assert (
        WORKFLOWS_HUD["run-job--refresh_hermes_radar"]["kwargs"]["max_hud_lines"]
        == DAILY_RADAR_MAX_HUD_LINES
    )


def test__radar_sets_both_itemlines_and_maxlines():
    """Regression: bumping `max_hud_lines` must size BOTH the meter
    background (Variables.ItemLines) AND the marquee's visible window
    (Variables.MaxLines, read by TextCycle.lua, default 16). The earlier
    bug only set ItemLines, so growing the cap inflated the empty
    background while the scrolling text region stayed capped at 16."""
    import inspect
    from workflows.hud.tasks.hud_radar import _configure_radar_ini
    src = inspect.getsource(_configure_radar_ini)
    assert 'ini["Variables"]["ItemLines"]' in src
    assert 'ini["Variables"]["MaxLines"]' in src


def test__radar_pre_wraps_long_dump_lines_before_marquee_paging():
    """Long Hermes lines must count as visual rows before MaxLines is applied."""
    from pathlib import Path
    import inspect
    from workflows.hud.tasks.hud_radar import (
        DAILY_RADAR_WRAP_AT,
        _configure_radar_ini,
    )

    assert DAILY_RADAR_WRAP_AT == 56
    src = inspect.getsource(_configure_radar_ini)
    assert 'ini["Variables"]["WrapAt"] = str(DAILY_RADAR_WRAP_AT)' in src

    text_cycle = (
        Path(__file__).parents[3]
        / "apps"
        / "rainmeter"
        / "static"
        / "bin"
        / "TextCycle.lua"
    ).read_text(encoding="utf-8")
    assert 'wrapAt = tonumber(SKIN:GetVariable("WrapAt", "0")) or 0' in text_cycle
    assert "appendWrappedLine(lines, l)" in text_cycle


def test__radar_content_viewport_stays_inside_skin():
    """The content meter starts below the header and must not use SkinHeight."""
    import inspect
    from workflows.hud.tasks.hud_radar import _configure_radar_ini

    src = inspect.getsource(_configure_radar_ini)
    assert 'ini["MeterDisplay"]["H"] = "((#ItemLines#*22-42)*#Scale#)"' in src
    assert 'ini["MeterDisplay"]["Y"] = "(70*#Scale#)"' in src
    assert (
        'ini["MeterDisplay"]["H"] = '
        '"((42*#Scale#)+(#ItemLines#*22)*#Scale#)"'
    ) not in src


def test__radar_content_padding_preserves_right_margin():
    """Moving content right must shrink its width by the same amount."""
    import inspect
    from workflows.hud.tasks.hud_radar import _configure_radar_ini

    src = inspect.getsource(_configure_radar_ini)
    assert 'ini["MeterDisplay"]["X"] = "(22*#Scale#)"' in src
    assert (
        'ini["MeterDisplay"]["W"] = '
        '"(({0}*186-8)*#Scale#)".format(width_multiplier)'
    ) in src


def test__visible_title_changes_without_moving_compatibility_folder():
    import inspect
    from workflows.hud.tasks.hud_radar import show_daily_radar

    source = inspect.getsource(show_daily_radar)
    assert 'hud_item_name="HERMES RADAR"' in source
    assert 'hud_folder_name="DAILY RADAR"' in source
    assert 'result["feed_text"] = briefing' in source


# ── Workflow (integration) ────────────────────────────────────────────────────


def test__show_daily_radar():
    """Live call — walks the default registry (Gmail, Calendar, Tasks,
    Trello, Jira, GitHub, OwnTracks, ES) and hits Anthropic."""
    from workflows.hud.tasks.hud_radar import show_daily_radar
    show_daily_radar(
        cfg_id__anthropic="ANTHROPIC",
        model="claude-sonnet-4-6",
        window_hours=8,
    )


def test__show_daily_radar_tight_window():
    """Shorten the window to 2h — verifies the window kwarg flows through."""
    from workflows.hud.tasks.hud_radar import show_daily_radar
    show_daily_radar(
        cfg_id__anthropic="ANTHROPIC",
        model="claude-sonnet-4-6",
        window_hours=2,
    )


# ── Unit / function — read_desktop_dump_tail ──────────────────────────────────


def test__read_desktop_dump_tail_missing_file_returns_empty(tmp_path):
    missing = str(tmp_path / "nope.txt")
    assert read_desktop_dump_tail(missing) == ""


def test__read_desktop_dump_tail_returns_head_bytes(tmp_path):
    """get_desktop_logs PREPENDS new entries, so head-of-file is freshest."""
    p = tmp_path / "dump.txt"
    p.write_text("FRESH first line\n" + ("x" * 1000) + "\nOLDEST line\n", encoding="utf-8")
    out = read_desktop_dump_tail(str(p), tail_bytes=100)
    assert out.startswith("FRESH first line")
    assert len(out) <= 100


# ── Unit / function — Gmail date parsing ──────────────────────────────────────


def test__parse_gmail_date_handles_valid_header():
    dt = _parse_gmail_date("Tue, 12 May 2026 10:00:00 +0800")
    assert dt.year == 2026 and dt.month == 5 and dt.day == 12


def test__parse_gmail_date_falls_back_to_epoch_on_garbage():
    dt = _parse_gmail_date("not-a-date")
    assert dt == datetime.fromtimestamp(0, tz=timezone.utc)


def test__parse_gmail_date_handles_empty():
    assert _parse_gmail_date("") == datetime.fromtimestamp(0, tz=timezone.utc)


# ── Unit / function — Trello board id resolution ──────────────────────────────


def test__resolve_trello_board_ids_prefers_kanban_single():
    with patch.dict(os.environ, {
        "KANBAN_BOARD_ID": "single123",
        "TRELLO_BOARD_IDS": "multi1,multi2",
    }, clear=False):
        assert _resolve_trello_board_ids() == ["single123"]


def test__resolve_trello_board_ids_splits_comma_list():
    with patch.dict(os.environ, {
        "KANBAN_BOARD_ID": "",
        "TRELLO_BOARD_IDS": "a,  b ,c",
    }, clear=False):
        assert _resolve_trello_board_ids() == ["a", "b", "c"]


def test__resolve_trello_board_ids_returns_empty_when_unset():
    with patch.dict(os.environ, {
        "KANBAN_BOARD_ID": "",
        "TRELLO_BOARD_IDS": "",
    }, clear=False):
        assert _resolve_trello_board_ids() == []


# ── Unit / function — _ensure_list_of_dicts (guards Trello bad responses) ────


class _NonListResponse:
    """Stand-in for the raw `Response` object Trello's deserializer returns
    when the JSON body fails to parse. Not subscriptable / not iterable in
    the expected way — calling code must NOT treat it as a list."""

    def __getitem__(self, _key):
        raise TypeError("'Response' object is not subscriptable")


def test__ensure_list_of_dicts_passes_through_clean_list():
    assert _ensure_list_of_dicts([{"a": 1}, {"b": 2}]) == [{"a": 1}, {"b": 2}]


def test__ensure_list_of_dicts_drops_non_dict_members():
    assert _ensure_list_of_dicts([{"ok": True}, "junk", 42, None]) == [{"ok": True}]


def test__ensure_list_of_dicts_coerces_response_object_to_empty():
    """Regression: malformed Trello reply must not crash card iteration."""
    assert _ensure_list_of_dicts(_NonListResponse()) == []


def test__ensure_list_of_dicts_coerces_none_to_empty():
    assert _ensure_list_of_dicts(None) == []


# ── Unit / function — section formatters ──────────────────────────────────────


def test__format_emails_renders_each_field():
    section = {
        "emails": [
            {
                "from": "alice@example.com",
                "subject": "Quarterly sign-off",
                "date": "Tue, 12 May 2026 10:00:00 +0800",
                "snippet": "Please review the attached approval form.",
                "body": "",
                "labels": ["INBOX", "IMPORTANT"],
            },
        ],
        "error": None,
    }
    out = _format_emails(section)
    assert "FROM: alice@example.com" in out
    assert "SUBJ: Quarterly sign-off" in out
    assert "LABELS: INBOX,IMPORTANT" in out


def test__format_emails_empty_list_renders_friendly_placeholder():
    assert _format_emails({"emails": [], "error": None}) == "(no email)"


def test__format_emails_surfaces_error():
    out = _format_emails({"emails": [], "error": "401 Unauthorized"})
    assert "gmail unavailable" in out
    assert "401 Unauthorized" in out


def test__format_calendar_renders_event_line():
    section = {
        "events": [
            {
                "summary": "Career | Work",
                "start": "2026-05-12T09:00:00+08:00",
                "end": "2026-05-12T18:00:00+08:00",
                "calendar": "primary",
                "location": "",
            },
        ],
        "error": None,
    }
    out = _format_calendar(section)
    assert "Career | Work" in out
    assert "2026-05-12T09:00:00+08:00" in out


def test__format_calendar_empty_renders_placeholder():
    assert _format_calendar({"events": [], "error": None}) == "(no events)"


def test__format_tasks_renders_list_and_due():
    section = {
        "tasks": [
            {"list": "Inbox", "title": "Reply to Alice", "due": "2026-05-15", "notes": ""},
        ],
        "error": None,
    }
    out = _format_tasks(section)
    assert "[Inbox]" in out
    assert "Reply to Alice" in out
    assert "(due: 2026-05-15)" in out


def test__format_tasks_empty_renders_placeholder():
    assert _format_tasks({"tasks": [], "error": None}) == "(no open tasks)"


def test__format_trello_renders_list_and_name():
    section = {
        "cards": [
            {"list": "In Progress", "name": "Wire DAILY RADAR", "due": "", "board_id": "x", "url": ""},
        ],
        "error": None,
    }
    out = _format_trello(section)
    assert "[In Progress]" in out
    assert "Wire DAILY RADAR" in out


def test__format_trello_handles_unconfigured_board():
    out = _format_trello({"cards": [], "error": "no board configured"})
    assert "trello unavailable" in out
    assert "no board configured" in out


def test__format_jira_renders_key_status_summary():
    section = {
        "issues": [
            {
                "key": "SEHLAT-42",
                "status": "In Progress",
                "summary": "Wire DAILY RADAR Jira section",
                "assignee": "Bartilet, Dick Brian",
                "priority": "Major",
                "updated": "2026-05-12T15:30:00+08:00",
            },
        ],
        "error": None,
    }
    out = _format_jira(section)
    assert "SEHLAT-42" in out
    assert "[In Progress]" in out
    assert "Wire DAILY RADAR Jira section" in out
    assert "Bartilet, Dick Brian" in out
    assert "Major" in out


def test__format_jira_empty_renders_placeholder():
    assert _format_jira({"issues": [], "error": None}) == "(no recent jira updates)"


def test__format_jira_surfaces_error():
    out = _format_jira({"issues": [], "error": "401 Unauthorized"})
    assert "jira unavailable" in out
    assert "401 Unauthorized" in out


def test__format_github_prs_renders_number_state_title():
    section = {
        "prs": [
            {
                "number": 11,
                "state": "open",
                "title": "feat/config-env-injection",
                "author": "brianbartilet",
                "labels": ["enhancement", "config"],
                "updated": "2026-05-12T15:00:00Z",
            },
        ],
        "error": None,
    }
    out = _format_github_prs(section)
    assert "#11" in out
    assert "[open]" in out
    assert "feat/config-env-injection" in out
    assert "brianbartilet" in out
    assert "enhancement,config" in out


def test__format_github_prs_empty_renders_placeholder():
    assert _format_github_prs({"prs": [], "error": None}) == (
        "(no PRs involving me updated in window)"
    )


def test__format_github_prs_surfaces_error():
    out = _format_github_prs({"prs": [], "error": "401 Unauthorized"})
    assert "github unavailable" in out
    assert "401 Unauthorized" in out


def test__format_last_location_renders_user_device_coords():
    section = {
        "location": {
            "user": "brian",
            "device": "iphone",
            "lat": 1.29,
            "lon": 103.85,
            "tst": 1747038600,
            "topic": "owntracks/brian/iphone",
        },
        "error": None,
    }
    out = _format_last_location(section)
    assert "user=brian" in out
    assert "device=iphone" in out
    assert "lat=1.29" in out
    assert "lon=103.85" in out


def test__format_last_location_empty_renders_placeholder():
    assert _format_last_location({"location": None, "error": None}) == (
        "(no recent location fix)"
    )


def test__format_last_location_surfaces_error():
    out = _format_last_location({"location": None, "error": "connection refused"})
    assert "owntracks unavailable" in out
    assert "connection refused" in out


def test__format_failed_jobs_renders_task_and_error():
    section = {
        "jobs": [
            {
                "task": "hud_tcg.show_tcg_orders",
                "error": "ConnectionResetError",
                "last_failed": "2026-05-12T07:42:01",
                "machine": "harqis-server",
            },
        ],
        "error": None,
    }
    out = _format_failed_jobs(section)
    assert "hud_tcg.show_tcg_orders" in out
    assert "ConnectionResetError" in out
    assert "harqis-server" in out


def test__format_failed_jobs_empty_renders_placeholder():
    assert _format_failed_jobs({"jobs": [], "error": None}) == "(no failed jobs)"


# ── Unit / function — prompt assembly ─────────────────────────────────────────


def _fixture_payload() -> dict:
    return {
        "window_hours": ANALYSIS_WINDOW_HOURS,
        "desktop_activity_log": "[START] 2026-05-12 08:00\nPyCharm focus\n[END]",
        # Replays what `collect_inputs` writes — `_sources` is the
        # priority list it actually walked, used by both the prompt
        # formatter and the summary to know what to emit and in what
        # order.
        "_sources": [
            "gmail", "calendar", "gtasks", "trello",
            "jira", "github", "owntracks", "es_failed_jobs",
        ],
        "gmail_recent": {"emails": [], "error": None},
        "calendar_today": {"events": [], "error": None},
        "google_tasks_open": {"tasks": [], "error": None},
        "trello_open_cards": {"cards": [], "error": "no board configured"},
        "jira_recent_updates": {"issues": [], "error": None},
        "github_prs_involving_me": {"prs": [], "error": None},
        "last_location": {"location": None, "error": None},
        "es_failed_jobs": {"jobs": [], "error": None},
    }


def test__format_inputs_as_prompt_text_contains_all_section_markers():
    text = format_inputs_as_prompt_text(_fixture_payload())
    for marker in [
        "DESKTOP_ACTIVITY_LOG",
        "GMAIL_RECENT",
        "CALENDAR_TODAY",
        "GOOGLE_TASKS_OPEN",
        "TRELLO_OPEN_CARDS",
        "JIRA_RECENT_UPDATES",
        "GITHUB_PRS_INVOLVING_ME",
        "LAST_LOCATION",
        "ES_FAILED_JOBS",
        "ANALYSIS WINDOW: last 8 hours",
    ]:
        assert marker in text, "missing marker: {0}".format(marker)


def test__format_inputs_as_prompt_text_passes_through_desktop_log():
    text = format_inputs_as_prompt_text(_fixture_payload())
    assert "PyCharm focus" in text


# ── Unit / function — summarise_inputs ────────────────────────────────────────


def test__summarise_inputs_counts_each_source():
    """`summarise_inputs` walks `_sources` (the priority list the radar
    actually ran) and emits one `{source_name}_count` per registered
    source with a `count_field`. Names match the registry key, not the
    payload key — `gmail_count` not `email_count`."""
    payload = {
        "window_hours": 8,
        "desktop_activity_log": "abc",
        "_sources": [
            "gmail", "calendar", "gtasks", "trello",
            "jira", "github", "owntracks", "es_failed_jobs",
        ],
        "gmail_recent": {"emails": [{}, {}], "error": None},
        "calendar_today": {"events": [{}], "error": None},
        "google_tasks_open": {"tasks": [], "error": None},
        "trello_open_cards": {"cards": [{}, {}, {}], "error": None},
        "jira_recent_updates": {"issues": [{}, {}, {}, {}], "error": None},
        "github_prs_involving_me": {"prs": [{}, {}], "error": None},
        "last_location": {"location": {"lat": 1.0, "lon": 2.0}, "error": None},
        "es_failed_jobs": {"jobs": [], "error": "timeout"},
    }
    out = summarise_inputs(payload)
    assert out["gmail_count"] == 2
    assert out["calendar_count"] == 1
    assert out["gtasks_count"] == 0
    assert out["trello_count"] == 3
    assert out["jira_count"] == 4
    assert out["github_count"] == 2
    assert out["has_location"] is True
    assert out["es_failed_jobs_count"] == 0
    assert out["sources_errored"] == ["es_failed_jobs"]
    assert out["sources_active"] == payload["_sources"]
    assert out["desktop_log_chars"] == 3


# ── Unit / function — SOURCE_REGISTRY + sources priority list ────────────────


def test__source_registry_has_all_default_sources():
    """Every name in DEFAULT_SOURCES must resolve in SOURCE_REGISTRY,
    otherwise a default tick would silently skip a feed."""
    from workflows.hud.tasks.daily_radar_agent import (
        DEFAULT_SOURCES,
        SOURCE_REGISTRY,
    )
    missing = [n for n in DEFAULT_SOURCES if n not in SOURCE_REGISTRY]
    assert missing == [], "unregistered sources in DEFAULT_SOURCES: {0}".format(missing)


def test__source_registry_specs_are_well_formed():
    """Each SourceSpec must carry the fields the orchestrators read."""
    from workflows.hud.tasks.daily_radar_agent import SOURCE_REGISTRY
    for name, spec in SOURCE_REGISTRY.items():
        assert spec.name == name, "registry key {0} mismatches spec.name {1}".format(name, spec.name)
        assert callable(spec.collector), "{0}: collector not callable".format(name)
        assert callable(spec.formatter), "{0}: formatter not callable".format(name)
        assert spec.payload_key, "{0}: payload_key empty".format(name)
        assert spec.prompt_marker == spec.prompt_marker.upper(), (
            "{0}: prompt_marker must be UPPERCASE".format(name)
        )


def test__collect_inputs_unknown_source_is_skipped_not_raised(tmp_path):
    """Typos in the `sources` list must NOT crash the radar — they're
    logged and skipped so the rest of the briefing still runs."""
    from workflows.hud.tasks.daily_radar_agent import collect_inputs
    dump = tmp_path / "dump.txt"
    dump.write_text("hello", encoding="utf-8")
    payload = collect_inputs(
        sources=["definitely_not_a_real_source"],
        desktop_dump_path=str(dump),
        hours=8,
    )
    assert payload["_sources"] == ["definitely_not_a_real_source"]
    # Desktop log still read; no source payload keys added.
    assert payload["desktop_activity_log"] == "hello"


def test__source_overrides_redirects_cfg_id(monkeypatch):
    """`source_overrides={"gmail": "X"}` must replace the registry's
    default cfg id when calling the gmail collector."""
    from workflows.hud.tasks.daily_radar_agent import (
        SOURCE_REGISTRY,
        SourceSpec,
        collect_inputs,
    )

    captured = {}

    def fake_collector(cfg_id, hours, **_):
        captured["cfg_id"] = cfg_id
        captured["hours"] = hours
        return {"emails": [], "error": None}

    def fake_formatter(section):
        return "(noop)"

    monkeypatch.setitem(SOURCE_REGISTRY, "gmail", SourceSpec(
        name="gmail",
        default_cfg="GOOGLE_GMAIL",
        collector=fake_collector,
        formatter=fake_formatter,
        payload_key="gmail_recent",
        prompt_marker="GMAIL_RECENT",
        count_field="emails",
    ))

    collect_inputs(
        sources=["gmail"],
        desktop_dump_path="/nope",
        hours=4,
        source_overrides={"gmail": "GOOGLE_GMAIL_WORK"},
    )
    assert captured == {"cfg_id": "GOOGLE_GMAIL_WORK", "hours": 4}


def test__source_params_merges_with_default_params(monkeypatch):
    """`source_params={"owntracks": {"user": "brian"}}` must thread
    through to the collector as a kwarg."""
    from workflows.hud.tasks.daily_radar_agent import (
        SOURCE_REGISTRY,
        SourceSpec,
        collect_inputs,
    )

    captured_kwargs = {}

    def fake_collector(cfg_id, hours, **kwargs):
        captured_kwargs.update(kwargs)
        return {"location": None, "error": None}

    monkeypatch.setitem(SOURCE_REGISTRY, "owntracks", SourceSpec(
        name="owntracks",
        default_cfg="OWN_TRACKS",
        collector=fake_collector,
        formatter=lambda s: "(noop)",
        payload_key="last_location",
        prompt_marker="LAST_LOCATION",
        default_params={"device": "iphone"},
    ))

    collect_inputs(
        sources=["owntracks"],
        desktop_dump_path="/nope",
        hours=8,
        source_params={"owntracks": {"user": "brian"}},
    )
    assert captured_kwargs == {"device": "iphone", "user": "brian"}


def test__format_inputs_walks_sources_in_priority_order():
    """Prompt-input section order matches the order the radar pulled —
    callers can rearrange `sources` to weight what the LLM sees first."""
    from workflows.hud.tasks.daily_radar_agent import format_inputs_as_prompt_text
    payload = {
        "window_hours": 8,
        "desktop_activity_log": "",
        "_sources": ["jira", "gmail"],   # jira first, gmail second
        "gmail_recent": {"emails": [], "error": None},
        "jira_recent_updates": {"issues": [], "error": None},
    }
    text = format_inputs_as_prompt_text(payload)
    assert text.index("JIRA_RECENT_UPDATES") < text.index("GMAIL_RECENT")


# ── Unit / function — wrap_preserving_breaks ──────────────────────────────────


def test__wrap_preserving_breaks_keeps_blank_lines():
    """Section breaks (blank lines) must survive the wrap step."""
    src = "HEADER\n\n- item one\n- item two\n\nNEXT HEADER"
    out = wrap_preserving_breaks(src, width=80)
    assert "HEADER\n\n- item one\n- item two\n\nNEXT HEADER" == out


def test__wrap_preserving_breaks_wraps_long_lines_individually():
    src = "short line\n" + ("verylongtoken " * 20).rstrip()
    out = wrap_preserving_breaks(src, width=40)
    lines = out.splitlines()
    assert lines[0] == "short line"
    assert all(len(line) <= 40 or " " not in line.strip() for line in lines[1:])


def test__wrap_preserving_breaks_handles_empty():
    assert wrap_preserving_breaks("") == ""
    assert wrap_preserving_breaks(None) == ""


def test__wrap_preserving_breaks_does_not_break_long_unbroken_token():
    """URLs and long identifiers stay intact — overflow > truncation."""
    src = "see https://example.com/a/very/long/path/that/exceeds/width"
    out = wrap_preserving_breaks(src, width=20)
    # The URL token stays on a single physical line.
    assert "https://example.com/a/very/long/path/that/exceeds/width" in out


# ── Unit / function — commitment-phrase detection ─────────────────────────────


@pytest.mark.parametrize("text,expected", [
    ("I'll send the report tomorrow", True),
    ("Let me confirm the budget", True),
    ("I will follow up after the meeting", True),
    ("we need to align on scope", True),
    ("Thanks for the update", False),
    ("", False),
    (None, False),
])
def test__looks_like_commitment(text, expected):
    assert looks_like_commitment(text) is expected
