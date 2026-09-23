#!/usr/bin/env python3
"""Spool completed default-profile Hermes turns; never process or call a model."""
from __future__ import annotations

import argparse
import io
import json
import os
import sqlite3
import sys
from contextlib import closing, contextmanager, nullcontext, redirect_stderr, redirect_stdout
from datetime import datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
LOOKBACK_DAYS = 1  # Leaves retry headroom inside the existing two-day ingester.
DEFAULT_DB = Path.home() / '.hermes' / 'state.db'
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.agents.hfl.capture_session_event import audit_root, normalize_event, write_event
from scripts.agents.hfl.migrate_hermes_sessions import (
    _is_internal_context, _strip_appended_internal_context, _user_message_kind,
)


def _final_answer(row):
    if row['finish_reason'] != 'stop' or row['tool_calls'] not in (None, '', '[]', 'null'):
        return ''
    if row['codex_message_items']:
        try:
            items = json.loads(row['codex_message_items'])
            if not isinstance(items, list) or not items or any(
                not isinstance(item, dict) or item.get('phase') != 'final_answer'
                for item in items
            ):
                return ''
        except (ValueError, TypeError):
            return ''
    content = row['content'] or ''
    return '' if _is_internal_context(content) else _strip_appended_internal_context(content)


def iter_completed_pairs(database: Path, *, since: datetime, until: datetime):
    """Stream finalized turns from a read-only, consistent SQLite snapshot."""
    with closing(sqlite3.connect(Path(database).resolve().as_uri() + "?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        rows = db.execute("""
            SELECT m.*, s.source FROM messages m JOIN sessions s ON s.id=m.session_id
            WHERE s.source IN ('cli', 'telegram')
                AND s.parent_session_id IS NULL
                AND COALESCE(s.profile_name, 'default') IN ('', 'default')
                AND m.timestamp >= ? AND m.timestamp <= ?
            ORDER BY m.session_id, m.id
        """, (since.timestamp(), until.timestamp()))
        pending = None
        session = None
        for row in rows:
            if session != row['session_id']:
                pending = None
                session = row['session_id']
            if not row['active'] or row['compacted']:
                continue
            if row['role'] == 'user':
                content = _strip_appended_internal_context(row['content'] or '').strip()
                pending = dict(row) if content and not content.startswith('/') and _user_message_kind(content) == 'prompt' else None
                if pending is not None:
                    pending['content'] = content
            elif pending is not None and row['role'] == 'assistant' and (answer := _final_answer(row)):
                yield normalize_event({
                    'surface': 'hermes', 'session_id': session,
                    'prompt_id': str(pending['id']),
                    'timestamp': datetime.fromtimestamp(pending['timestamp']).astimezone().isoformat(),
                    'original_prompt': pending['content'], 'assistant_outcome': answer,
                    'result_status': 'unknown', 'tags': [f"hermes-{row['source']}"],
                })
                pending = None


def collect(database: Path, *, since: datetime, until: datetime, limit: int = 100, dry_run: bool = False):
    if (since.utcoffset() is None or until.utcoffset() is None
            or not timedelta(0) <= until - since <= timedelta(days=LOOKBACK_DAYS)
            or not 1 <= limit <= 500):
        raise ValueError('Require aware bounds within one day and limit 1..500')
    with nullcontext() if dry_run else _collector_lock():
        return _spool(database, since=since, until=until, limit=limit, dry_run=dry_run)


@contextmanager
def _collector_lock():
    # Advisory lock inode stays in place across runs. No stale lock deletion.
    import fcntl

    root = audit_root()
    root.mkdir(parents=True, exist_ok=True)
    with (root / '.hermes-collector.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def _spool(database, *, since, until, limit, dry_run):
    summary = {'spooled': 0, 'duplicates': 0, 'eligible': 0, 'dry_run': dry_run, 'batch_full': False}
    for event in iter_completed_pairs(database, since=since, until=until):
        day = datetime.fromisoformat(event['timestamp']).strftime('%Y-%m-%d')
        path = audit_root() / 'events' / day / f"{event['event_id']}.json"
        if path.exists():
            existing = json.loads(path.read_text(encoding='utf-8'))
            identity = ('schema_version', 'event_id', 'surface', 'session_id', 'prompt_id', 'original_prompt')
            if (not isinstance(existing, dict)
                    or any(existing.get(key) != event[key] for key in identity)
                    or not isinstance(existing.get('ingest'), dict)
                    or not isinstance(existing.get('assistant_outcome'), str)
                    or not existing['assistant_outcome'].strip()):
                raise ValueError('Malformed existing event')
            summary['duplicates'] += 1
        else:
            summary['eligible'] += 1
            if not dry_run:
                write_event(event)
                summary['spooled'] += 1
            if summary['eligible'] >= limit:
                summary['batch_full'] = True
                break
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--since', type=datetime.fromisoformat)
    parser.add_argument('--until', type=datetime.fromisoformat)
    parser.add_argument('--limit', type=int, default=100)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args(argv)
    try:
        # Same environment precedence as the scanner/launcher, including machine overrides.
        # Keep bootstrap diagnostics out of scheduled Telegram delivery.
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            from scripts.launch import setup_env
            setup_env()
        until = args.until or datetime.now().astimezone()
        if args.since is not None:
            since = args.since
        else:
            boundary = datetime.fromisoformat(os.environ['HFL_HERMES_CAPTURE_SINCE']) if os.environ.get('HFL_HERMES_CAPTURE_SINCE') else None
            if boundary is None or boundary.utcoffset() is None:
                raise ValueError('Configure an aware launch boundary first')
            since = max(boundary, until - timedelta(days=LOOKBACK_DAYS))
        result = collect(DEFAULT_DB, since=since, until=until, limit=args.limit, dry_run=args.dry_run)
    except Exception as exc:
        # Exception messages can contain private DB text or paths; report type only.
        print(json.dumps({'failed': 1, 'error_type': type(exc).__name__}))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
