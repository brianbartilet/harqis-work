"""Owner operational settings; secrets remain in the host environment."""
import json
import sqlite3
import re
from pathlib import Path

from config import get_settings

DEFAULTS = {'actions_polling_minutes': 30, 'pin_backfill_days': 7,
            'agent_mode': 'trusted', 'hermes_profile': '', 'agent_toolsets': '',
            'agent_model': '', 'agent_provider': '', 'agent_default_recipient': '',
            'agent_timeout_seconds': 1200, 'agent_max_turns': 30}


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
    clean = read_settings()
    for key, maximum in [('actions_polling_minutes', 1440), ('pin_backfill_days', 31),
                         ('agent_timeout_seconds', 7200), ('agent_max_turns', 200)]:
        raw = values.get(key, clean[key])
        if isinstance(raw, bool) or str(raw) != str(int(raw)) or not 1 <= int(raw) <= maximum:
            raise ValueError(f'{key.replace("_", " ").capitalize()} must be between 1 and {maximum}.')
        clean[key] = int(raw)
    for key in ('agent_mode', 'hermes_profile', 'agent_toolsets', 'agent_model', 'agent_provider', 'agent_default_recipient'):
        value = str(values.get(key, clean[key])).strip()
        if len(value) > 300 or any(ord(c) < 32 for c in value):
            raise ValueError(f'Invalid {key}.')
        clean[key] = value
    if clean['agent_mode'] not in {'trusted', 'restricted'}:
        raise ValueError('Choose trusted or restricted execution.')
    if clean['hermes_profile'] and not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}', clean['hermes_profile']):
        raise ValueError('Use a Hermes profile name, not a path.')
    if clean['agent_default_recipient'] and not re.fullmatch(r'[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+', clean['agent_default_recipient']):
        raise ValueError('Enter one default recipient email address.')
    with connection() as db:
        db.executemany('INSERT INTO app_settings VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', [(key, json.dumps(value)) for key, value in clean.items()])
    return clean
