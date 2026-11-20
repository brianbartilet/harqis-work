"""Encrypted connector credentials and user-scoped resource associations."""
import base64
import hashlib
import hmac
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException
from config import get_settings


def now():
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def connection():
    path = Path(os.environ.get('HARQIS_CONNECTORS_DB') or Path(get_settings().profile_store_path).with_name('connectors.sqlite3'))
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=30)
    db.row_factory = sqlite3.Row
    try:
        db.executescript('''
            CREATE TABLE IF NOT EXISTS connectors (
                user TEXT NOT NULL, provider TEXT NOT NULL, credentials TEXT NOT NULL DEFAULT '',
                metadata TEXT NOT NULL, PRIMARY KEY(user,provider));
            CREATE TABLE IF NOT EXISTS connector_links (
                user TEXT NOT NULL, provider TEXT NOT NULL, resource TEXT NOT NULL,
                payload TEXT NOT NULL, PRIMARY KEY(user,provider,resource));
        ''')
        with db:
            yield db
    finally:
        db.close()


def cipher(user, provider):
    # Purpose/user/provider separation; APP_SECRET_KEY already protects sessions.
    master = os.environ.get('HARQIS_CONNECTORS_KEY') or get_settings().secret_key
    key = hmac.new(master.encode(), ('harqis-connectors-v1\0'+user+'\0'+provider).encode(), hashlib.sha256).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def get(user, provider, *, private=False):
    if provider == 'hermes':
        return {'provider': provider, 'status': 'Managed', 'enabled': True, 'managed': True, 'site': 'harqis:hermes'}
    with connection() as db:
        row = db.execute('SELECT * FROM connectors WHERE user=? AND provider=?', (user, provider)).fetchone()
    data = json.loads(row['metadata']) if row else {'status': 'Not connected', 'enabled': False}
    data['provider'] = provider
    if private:
        try:
            data['credentials'] = json.loads(cipher(user, provider).decrypt(row['credentials'].encode())) if row and row['credentials'] else {}
        except InvalidToken:
            raise HTTPException(409, 'Connection key changed. Disconnect and connect again.') from None
    return data


def save(user, provider, metadata, credentials=None):
    metadata = {k: v for k, v in metadata.items() if k != 'credentials'}
    with connection() as db:
        if credentials is None:
            row = db.execute('SELECT credentials FROM connectors WHERE user=? AND provider=?', (user, provider)).fetchone()
            encrypted = row[0] if row else ''
        else:
            encrypted = cipher(user, provider).encrypt(json.dumps(credentials).encode()).decode()
        db.execute('INSERT INTO connectors VALUES (?,?,?,?) ON CONFLICT(user,provider) DO UPDATE SET credentials=excluded.credentials,metadata=excluded.metadata',
                   (user, provider, encrypted, json.dumps(metadata)))
    return metadata


def links(user, provider=None):
    with connection() as db:
        return [json.loads(row[0]) for row in db.execute('SELECT payload FROM connector_links WHERE user=? AND (? IS NULL OR provider=?)', (user, provider, provider))]


def link(user, provider, resource, payload):
    with connection() as db:
        db.execute('INSERT INTO connector_links VALUES (?,?,?,?) ON CONFLICT(user,provider,resource) DO UPDATE SET payload=excluded.payload',
                   (user, provider, resource, json.dumps({**payload, 'resource': resource, 'provider': provider})))


def clear_action_links(user, provider, identity, account):
    """Remove only this action's associations for the connected account."""
    with connection() as db:
        result = db.execute(
            "DELETE FROM connector_links WHERE user=? AND provider=? "
            "AND json_extract(payload, '$.action_id')=? "
            "AND json_extract(payload, '$.account_key')=?",
            (user, provider, identity, account),
        )
        return result.rowcount
