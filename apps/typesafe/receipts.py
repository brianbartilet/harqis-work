"""Local, profile-scoped receipts. No raw context, credentials or candidate names."""
import json
import os
from pathlib import Path
import sqlite3


class ReceiptStore:
    def __init__(self):
        home = Path(os.environ.get('HERMES_HOME') or Path.home() / '.hermes')
        self.path = Path(os.environ.get('TYPESAFE_RECEIPTS_DB') or home / 'typesafe-decisions.sqlite3').expanduser()

    def save(self, receipt):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Create private before SQLite opens it, rather than tightening after commit.
        if self.path.is_symlink():
            raise OSError('Receipt database must not be a symlink.')
        fd = os.open(self.path, os.O_CREAT | os.O_WRONLY, 0o600)
        os.close(fd)
        if os.name != 'nt':
            self.path.chmod(0o600)
        with sqlite3.connect(self.path, timeout=10) as db:
            db.execute('CREATE TABLE IF NOT EXISTS decisions (id TEXT PRIMARY KEY, payload TEXT NOT NULL)')
            db.execute('INSERT INTO decisions VALUES (?, ?)', (receipt['receipt_id'], json.dumps(receipt, allow_nan=False)))
