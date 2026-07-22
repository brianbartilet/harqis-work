"""Historical Hermes session migration into HFL prompt-audit envelopes."""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from scripts.agents.hfl.migrate_hermes_sessions import (
    collect_session_pairs,
    migrate_pairs,
)


def _database(path):
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE sessions (
            id TEXT PRIMARY KEY,
            source TEXT,
            ended_at REAL,
            archived INTEGER DEFAULT 0
        );
        CREATE TABLE messages (
            id INTEGER PRIMARY KEY,
            session_id TEXT,
            role TEXT,
            content TEXT,
            timestamp REAL,
            tool_calls TEXT,
            active INTEGER DEFAULT 1,
            compacted INTEGER DEFAULT 0
        );
        """
    )
    return connection


def test_collects_only_closed_user_facing_prompt_outcome_pairs(tmp_path):
    database = tmp_path / "state.db"
    connection = _database(database)
    now = datetime(2026, 7, 22, 12, 0).timestamp()
    connection.executemany(
        "INSERT INTO sessions(id, source, ended_at) VALUES (?, ?, ?)",
        [
            ("closed-cli", "cli", now),
            ("open-cli", "cli", None),
            ("closed-telegram", "telegram", now),
            ("closed-cron", "cron", now),
        ],
    )
    connection.executemany(
        "INSERT INTO messages(id, session_id, role, content, timestamp, tool_calls) VALUES (?, ?, ?, ?, ?, ?)",
        [
            (1, "closed-cli", "user", "Fix the parser", now - 5, None),
            (2, "closed-cli", "assistant", "", now - 4, '[{"name":"terminal"}]'),
            (3, "closed-cli", "tool", "private tool output", now - 3, None),
            (4, "closed-cli", "assistant", "Fixed parser.py", now - 2, None),
            (5, "open-cli", "user", "Still working", now - 5, None),
            (6, "open-cli", "assistant", "Partial result", now - 2, None),
            (7, "closed-telegram", "user", "Summarize this", now - 5, None),
            (8, "closed-telegram", "assistant", "Summary ready", now - 2, None),
            (9, "closed-cron", "user", "Scheduled prompt", now - 5, None),
            (10, "closed-cron", "assistant", "Scheduled result", now - 2, None),
        ],
    )
    connection.commit()
    connection.close()

    pairs = collect_session_pairs(database)

    assert [(pair["session_id"], pair["prompt_id"]) for pair in pairs] == [
        ("closed-cli", "1"),
        ("closed-telegram", "7"),
    ]
    assert pairs[0]["original_prompt"] == "Fix the parser"
    assert pairs[0]["assistant_outcome"] == "Fixed parser.py"
    assert pairs[0]["result_status"] == "unknown"
    assert "private tool output" not in str(pairs)


def test_collect_deduplicates_exact_prompt_outcomes_and_keeps_earliest(tmp_path):
    database = tmp_path / "state.db"
    connection = _database(database)
    now = datetime(2026, 7, 22, 12, 0).timestamp()
    connection.executemany(
        "INSERT INTO sessions(id, source, ended_at) VALUES (?, ?, ?)",
        [("later", "cli", now), ("earlier", "telegram", now)],
    )
    connection.executemany(
        "INSERT INTO messages(id, session_id, role, content, timestamp, tool_calls) VALUES (?, ?, ?, ?, ?, ?)",
        [
            (1, "later", "user", "Hello", now - 10, None),
            (2, "later", "assistant", "Hey Brian", now - 9, None),
            (3, "earlier", "user", " hello ", now - 20, None),
            (4, "earlier", "assistant", "Hey   Brian", now - 19, None),
        ],
    )
    connection.commit()
    connection.close()

    pairs = collect_session_pairs(database)

    assert len(pairs) == 1
    assert pairs[0]["session_id"] == "earlier"


def test_internal_followups_merge_into_previous_real_turn(tmp_path):
    database = tmp_path / "state.db"
    connection = _database(database)
    now = datetime(2026, 7, 22, 12, 0).timestamp()
    connection.execute(
        "INSERT INTO sessions(id, source, ended_at) VALUES (?, ?, ?)",
        ("closed-cli", "cli", now),
    )
    connection.executemany(
        "INSERT INTO messages(id, session_id, role, content, timestamp, tool_calls) VALUES (?, ?, ?, ?, ?, ?)",
        [
            (1, "closed-cli", "user", "Publish the corpus scaling PR", now - 8, None),
            (2, "closed-cli", "assistant", "Implemented the scaling changes.", now - 7, None),
            (3, "closed-cli", "user", "[System: Run fresh verification before calling this done.]", now - 6, None),
            (4, "closed-cli", "assistant", "Fresh pytest verification passed: 61 passed.", now - 5, None),
            (5, "closed-cli", "user", "[ASYNC DELEGATION BATCH COMPLETE — deleg_123] review results", now - 4, None),
            (6, "closed-cli", "assistant", "Review found no blocking issues.", now - 3, None),
        ],
    )
    connection.commit()
    connection.close()

    pairs = collect_session_pairs(database)

    assert len(pairs) == 1
    assert pairs[0]["original_prompt"] == "Publish the corpus scaling PR"
    assert pairs[0]["assistant_outcome"] == (
        "Implemented the scaling changes.\n\n"
        "Fresh pytest verification passed: 61 passed.\n\n"
        "Review found no blocking issues."
    )


def test_discards_orphan_internal_and_low_value_control_turns(tmp_path):
    database = tmp_path / "state.db"
    connection = _database(database)
    now = datetime(2026, 7, 22, 12, 0).timestamp()
    connection.execute(
        "INSERT INTO sessions(id, source, ended_at) VALUES (?, ?, ?)",
        ("closed-cli", "cli", now),
    )
    connection.executemany(
        "INSERT INTO messages(id, session_id, role, content, timestamp, tool_calls) VALUES (?, ?, ?, ?, ?, ?)",
        [
            (1, "closed-cli", "user", "[CONTEXT COMPACTION — REFERENCE ONLY] stale summary", now - 6, None),
            (2, "closed-cli", "assistant", "Acknowledged.", now - 5, None),
            (3, "closed-cli", "user", "stop", now - 4, None),
            (4, "closed-cli", "assistant", "Stopped.", now - 3, None),
            (7, "closed-cli", "user", "Yes approve", now - 2.5, None),
            (8, "closed-cli", "assistant", "Approved action started.", now - 2.25, None),
            (5, "closed-cli", "user", "You've reached the maximum number of tool-calling iterations allowed.", now - 2, None),
            (6, "closed-cli", "assistant", "Partial work summary.", now - 1, None),
        ],
    )
    connection.commit()
    connection.close()

    assert collect_session_pairs(database) == []


def test_skips_assistant_compaction_handoff_and_keeps_next_visible_result(tmp_path):
    database = tmp_path / "state.db"
    connection = _database(database)
    now = datetime(2026, 7, 22, 12, 0).timestamp()
    connection.execute(
        "INSERT INTO sessions(id, source, ended_at) VALUES (?, ?, ?)",
        ("closed-cli", "cli", now),
    )
    connection.executemany(
        "INSERT INTO messages(id, session_id, role, content, timestamp, tool_calls) VALUES (?, ?, ?, ?, ?, ?)",
        [
            (1, "closed-cli", "user", "Show OPENCLAW environment variables", now - 4, None),
            (2, "closed-cli", "assistant", "[CONTEXT COMPACTION — REFERENCE ONLY] stale handoff", now - 3, None),
            (3, "closed-cli", "assistant", "Found two matching variable names.", now - 2, None),
        ],
    )
    connection.commit()
    connection.close()

    pairs = collect_session_pairs(database)

    assert len(pairs) == 1
    assert pairs[0]["assistant_outcome"] == "Found two matching variable names."


def test_strips_appended_active_task_list_from_real_prompt(tmp_path):
    database = tmp_path / "state.db"
    connection = _database(database)
    now = datetime(2026, 7, 22, 12, 0).timestamp()
    connection.execute(
        "INSERT INTO sessions(id, source, ended_at) VALUES (?, ?, ?)",
        ("closed-cli", "cli", now),
    )
    connection.executemany(
        "INSERT INTO messages(id, session_id, role, content, timestamp, tool_calls) VALUES (?, ?, ?, ?, ?, ?)",
        [
            (
                1,
                "closed-cli",
                "user",
                "Resume and publish the PR\n\n[Your active task list was preserved across context compression]\n- [>] review",
                now - 2,
                None,
            ),
            (2, "closed-cli", "assistant", "Published PR 51.", now - 1, None),
        ],
    )
    connection.commit()
    connection.close()

    pairs = collect_session_pairs(database)

    assert pairs[0]["original_prompt"] == "Resume and publish the PR"


def test_dry_run_never_processes_and_execution_reports_results():
    pairs = [
        {"event_id": "agent-one"},
        {"event_id": "agent-two"},
    ]
    processed = []

    preview = migrate_pairs(
        pairs,
        dry_run=True,
        processor=lambda payload, **kwargs: processed.append(payload),
    )
    assert preview == {
        "dry_run": True,
        "eligible_pairs": 2,
        "processed": 0,
        "written": 0,
        "failed": 0,
    }
    assert processed == []

    result = migrate_pairs(
        pairs,
        dry_run=False,
        synthesize=False,
        processor=lambda payload, **kwargs: processed.append(payload)
        or {"entries_written": 1, "event_id": payload["event_id"]},
    )
    assert result["processed"] == 2
    assert result["written"] == 2
    assert result["failed"] == 0
    assert [item["event_id"] for item in processed] == ["agent-one", "agent-two"]


def test_hfl_workflow_registers_agent_session_tasks():
    init_text = (Path(__file__).parents[1] / "__init__.py").read_text(encoding="utf-8")
    assert "import workflows.hfl.tasks.ingest_agent_sessions" in init_text


def test_agent_session_retry_and_rollup_are_scheduled():
    from workflows.hfl.tasks_config import WORKFLOW_HFL

    retry = WORKFLOW_HFL["run-job--ingest_agent_session_events"]
    rollup = WORKFLOW_HFL["run-job--rollup_agent_sessions"]
    assert retry["task"].endswith("ingest_agent_session_events")
    assert rollup["task"].endswith("rollup_agent_sessions")
    assert retry["options"]["queue"].value == "hfl"
    assert rollup["options"]["queue"].value == "hfl"


def test_migration_script_runs_directly_from_repo_root(tmp_path):
    database = tmp_path / "state.db"
    connection = _database(database)
    connection.commit()
    connection.close()
    repo_root = Path(__file__).parents[3]
    result = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts/agents/hfl/migrate_hermes_sessions.py"),
            "--database",
            str(database),
            "--dry-run",
            "--since",
            "2026-04-23T00:00:00+08:00",
            "--until",
            "2026-07-22T23:59:59+08:00",
        ],
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=False,
        env={**os.environ, "PYTHONPATH": ""},
    )
    assert result.returncode == 0, result.stderr
    assert '"eligible_pairs": 0' in result.stdout
    assert '"since": "2026-04-23T00:00:00+08:00"' in result.stdout
