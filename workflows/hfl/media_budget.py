"""Durable daily desktop vision budget shared by scheduled and manual runs."""
import os
import sqlite3
from datetime import datetime


def reserve_desktop_attempt(corpus_dir):
    """Reserve before calling the provider; failures/crashes still consume a slot.

    Uses the canonical host's local date, matching its capture schedule. SQLite
    serializes concurrent reservations across processes and survives restarts.
    """
    limit = int(os.environ.get('HARQIS_DESKTOP_DAILY_MAX_FILES', '200'))
    if limit < 0:
        raise ValueError('HARQIS_DESKTOP_DAILY_MAX_FILES must be nonnegative')
    state = corpus_dir / '.media-ingest-state'
    state.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(state / 'daily-budget.sqlite3', timeout=30) as db:
        db.execute('CREATE TABLE IF NOT EXISTS daily_budget(day TEXT PRIMARY KEY, used INTEGER NOT NULL)')
        db.execute('BEGIN IMMEDIATE')
        day = datetime.now().date().isoformat()
        row = db.execute('SELECT used FROM daily_budget WHERE day=?', (day,)).fetchone()
        used = row[0] if row else 0
        if used >= limit:
            return False
        db.execute('INSERT INTO daily_budget VALUES (?,?) ON CONFLICT(day) DO UPDATE SET used=excluded.used',
                   (day, used + 1))
        return True
