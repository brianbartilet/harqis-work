"""Owner operational settings; secrets remain in the host environment."""
import json
import sqlite3
from pathlib import Path

from config import get_settings

DEFAULTS = {'actions_polling_minutes': 30, 'pin_backfill_days': 7}


def connection():
    path = Path(get_settings().profile_store_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=15)
    db.execute('CREATE TABLE IF NOT EXISTS app_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
    return db


def read_settings():
    with connection() as db:
        return {**DEFAULTS, **{key: json.loads(value) for key, value in db.execute('SELECT key,value FROM app_settings') if key in DEFAULTS}}


def save_settings(values):
    clean = {}
    for key, maximum in [('actions_polling_minutes', 1440), ('pin_backfill_days', 31)]:
        raw = values.get(key, DEFAULTS[key])
        if isinstance(raw, bool) or str(raw) != str(int(raw)) or not 1 <= int(raw) <= maximum:
            raise ValueError(f'{key.replace("_", " ").capitalize()} must be between 1 and {maximum}.')
        clean[key] = int(raw)
    with connection() as db:
        db.executemany('INSERT INTO app_settings VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', [(key, json.dumps(value)) for key, value in clean.items()])
    return clean
