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

from scripts.agents.hfl.capture_session_event import audit_root, normalize_event, write_event, _atomic_json
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
    """Visible final messages, not a claim that the logical task completed."""
    for kind, event in _iter_records(database, since=since, until=until):
        if kind == 'event':
            yield event


def _prompt_event(prompt):
    return normalize_event({
        'surface': 'hermes', 'session_id': prompt['session_id'],
        'prompt_id': str(prompt['id']),
        'timestamp': datetime.fromtimestamp(prompt['timestamp']).astimezone().isoformat(),
        'original_prompt': prompt['content'], 'result_status': 'unknown',
        'tags': [f"hermes-{prompt['source']}"],
    })


def _inventory(pending, since, *, interrupted=False):
    for prompt in pending:
        if max(prompt['timestamp'], prompt.get('observed_at', 0)) < since.timestamp():
            continue
        event = _prompt_event(prompt)
        event['capture_state'] = ('answered' if prompt.get('answered') else
                                  'interrupted' if interrupted else 'pending')
        event['observation_id'] = str(prompt.get('last_message_id', prompt['id']))
        yield 'inventory', event


def _original_rows(rows):
    """Suppress ordered replay copies from Hermes microsecond insertion batches.

    Hermes has no persisted source-row ID for compaction copies. Require both
    batch timing and an ordered match to earlier archived rows, never text-only
    deduplication: separate real retries retain their own original IDs.
    """
    from itertools import groupby
    for _, session_rows in groupby(rows, key=lambda row: row['session_id']):
        history = []
        batch = []
        def flush():
            matches = []
            cursor = 0
            for index, row in enumerate(batch):
                for pos in range(cursor, len(history)):
                    old = history[pos]
                    if (old['compacted'] and old['role'] == row['role']
                            and old['content'] == row['content']):
                        matches.append(index)
                        cursor = pos + 1
                        break
            replay = len(matches) >= 2 or (matches and any(
                'CONTEXT COMPACTION' in (r['content'] or '') for r in batch))
            excluded = set(matches) if replay else set()
            originals = [row for i, row in enumerate(batch) if i not in excluded]
            history.extend(originals)
            return originals
        for row in session_rows:
            if batch and not 0 <= row['timestamp'] - batch[-1]['timestamp'] < 0.0001:
                yield from flush()
                batch = []
            batch.append(row)
        if batch:
            yield from flush()


def _iter_records(database: Path, *, since: datetime, until: datetime):
    """Scan full available history of touched sessions in one read-only snapshot."""
    with closing(sqlite3.connect(Path(database).resolve().as_uri() + "?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        rows = db.execute("""
            SELECT m.*, s.source FROM messages m JOIN sessions s ON s.id=m.session_id
            WHERE s.source IN ('cli', 'telegram')
                AND s.parent_session_id IS NULL
                AND COALESCE(s.profile_name, 'default') IN ('', 'default')
                AND m.timestamp <= ?
                AND EXISTS (SELECT 1 FROM messages recent WHERE recent.session_id=s.id
                            AND recent.timestamp >= ? AND recent.timestamp <= ?)
            ORDER BY m.session_id, m.id
        """, (until.timestamp(), since.timestamp(), until.timestamp()))
        pending = []
        session = None
        for row in _original_rows(rows):
            if session != row['session_id']:
                yield from _inventory(pending, since)
                pending = []
                session = row['session_id']
            if not row['active'] and not row['compacted']:
                continue
            if row['role'] == 'user':
                content = _strip_appended_internal_context(row['content'] or '').strip()
                if content.casefold().rstrip('.!?') in {'stop', '/stop', 'cancel', '/cancel', 'nevermind', 'never mind'}:
                    for prompt in pending:
                        prompt.update(observed_at=row['timestamp'], last_message_id=row['id'])
                    yield from _inventory(pending, since, interrupted=True)
                    pending = []
                elif content and not content.startswith('/') and _user_message_kind(content) == 'prompt':
                    if pending and (pending[0].get('answered') or pending[0].get('started')):
                        if not pending[0].get('answered'):
                            for prompt in pending:
                                prompt.update(observed_at=row['timestamp'], last_message_id=row['id'])
                        yield from _inventory(pending, since, interrupted=not pending[0].get('answered'))
                        pending = []
                    pending.append({**dict(row), 'content': content})
            elif pending and row['role'] == 'assistant' and (answer := _final_answer(row)):
                for prompt in pending:
                    event = normalize_event({
                        'surface': 'hermes', 'session_id': session,
                        'prompt_id': str(prompt['id']),
                        'timestamp': datetime.fromtimestamp(prompt['timestamp']).astimezone().isoformat(),
                        'original_prompt': prompt['content'], 'assistant_outcome': answer,
                        'result_status': 'unknown', 'tags': [f"hermes-{row['source']}"],
                    })
                    if prompt.get('answered'):
                        event['related_event_id'] = event['event_id']
                        event['event_id'] += f"-answer-{row['id']}"
                    event['outcome_message_id'] = str(row['id'])
                    if row['timestamp'] >= since.timestamp() or prompt['timestamp'] >= since.timestamp():
                        yield 'event', event
                    prompt.update(answered=True, observed_at=row['timestamp'], last_message_id=row['id'])
            elif pending and row['role'] == 'assistant':
                for prompt in pending:
                    prompt.update(started=True, observed_at=row['timestamp'], last_message_id=row['id'])
        yield from _inventory(pending, since)


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
    summary = {'spooled': 0, 'duplicates': 0, 'eligible': 0, 'dry_run': dry_run, 'batch_full': False,
               'inventory_written': 0, 'inventory_eligible': 0, 'unanswered': 0,
               'pending_hfl_visibility': True}
    for kind, event in _iter_records(database, since=since, until=until):
        day = datetime.fromisoformat(event['timestamp']).strftime('%Y-%m-%d')
        if kind == 'inventory':
            summary['unanswered'] += event['capture_state'] != 'answered'
            path = audit_root() / 'prompt-inventory' / day / (
                f"{event['event_id']}-{event['capture_state']}-{event['observation_id']}.json")
            if not path.exists():
                summary['inventory_eligible'] += 1
                if not dry_run:
                    _atomic_json(path, event)
                    summary['inventory_written'] += 1
            if event['capture_state'] == 'answered':
                continue
            event['result_status'] = event['capture_state']
            event['tags'].append('prompt-observation')
        path = audit_root() / 'events' / day / f"{event['event_id']}.json"
        if path.exists():
            retained = json.loads(path.read_text(encoding='utf-8'))
            identity = ('schema_version', 'event_id', 'surface', 'session_id', 'prompt_id', 'original_prompt')
            if (not isinstance(retained, dict)
                    or any(retained.get(key) != event[key] for key in identity)
                    or not isinstance(retained.get('ingest'), dict)
                    or not isinstance(retained.get('assistant_outcome'), str)):
                raise ValueError('Malformed existing event')
            if kind == 'inventory' and retained['assistant_outcome'].strip():
                summary['duplicates'] += 1
                continue
            if (retained.get('assistant_outcome', '') != event['assistant_outcome']
                    or retained.get('result_status') in {'pending', 'interrupted'}
                    and event['result_status'] != retained.get('result_status')):
                event['related_event_id'] = event['event_id']
                suffix = (f"answer-{event['outcome_message_id']}" if event.get('outcome_message_id')
                          else f"state-{event['result_status']}-{event['observation_id']}")
                event['event_id'] += '-' + suffix
                path = path.with_name(event['event_id'] + '.json')
        if path.exists():
            existing = json.loads(path.read_text(encoding='utf-8'))
            identity = ('schema_version', 'event_id', 'surface', 'session_id', 'prompt_id', 'original_prompt')
            if (not isinstance(existing, dict)
                    or any(existing.get(key) != event[key] for key in identity)
                    or not isinstance(existing.get('ingest'), dict)
                    or not isinstance(existing.get('assistant_outcome'), str)
                    or (not existing['assistant_outcome'].strip()
                        and existing.get('result_status') not in {'pending', 'interrupted'})):
                raise ValueError('Malformed existing event')
            summary['duplicates'] += 1
        else:
            if summary['eligible'] >= limit:
                summary['batch_full'] = True
                continue
            summary['eligible'] += 1
            if not dry_run:
                write_event(event)
                summary['spooled'] += 1
            if summary['eligible'] >= limit:
                summary['batch_full'] = True
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
