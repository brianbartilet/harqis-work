"""Immutable input files with detachable, source-scoped manifests."""
import hashlib
import json
import re
import sqlite3
import tempfile
import uuid
from pathlib import Path

from fastapi import HTTPException

MAX_FILES = 10
MAX_FILE_BYTES = 50 * 1024 * 1024
MAX_TOTAL_BYTES = 200 * 1024 * 1024


class AttachmentStore:
    def __init__(self, database):
        self.database = Path(database)
        self.root = self.database.with_suffix('.inputs')
        self.root.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS input_attachments (id TEXT PRIMARY KEY, source TEXT NOT NULL, manifest TEXT NOT NULL, detached INTEGER NOT NULL DEFAULT 0)')

    def connect(self):
        db = sqlite3.connect(self.database, timeout=15)
        db.row_factory = sqlite3.Row
        return db

    def list(self, source):
        with self.connect() as db:
            return [json.loads(row['manifest']) for row in db.execute('SELECT manifest FROM input_attachments WHERE source=? AND detached=0 ORDER BY rowid', (source,))]

    def get(self, source, attachment_id):
        with self.connect() as db:
            row = db.execute('SELECT manifest FROM input_attachments WHERE source=? AND id=?', (source, attachment_id)).fetchone()
        if not row:
            raise HTTPException(404, 'Attachment not found.')
        return json.loads(row['manifest'])

    def path(self, manifest):
        digest = manifest['digest']
        if not re.fullmatch('[a-f0-9]{64}', digest):
            raise HTTPException(400, 'Invalid attachment digest.')
        path = self.root / digest
        if path.is_symlink() or not path.resolve().is_relative_to(self.root.resolve()) or not path.is_file():
            raise HTTPException(404, 'Attachment file unavailable.')
        return path

    def detach(self, source, attachment_id):
        self.get(source, attachment_id)
        with self.connect() as db:
            db.execute('UPDATE input_attachments SET detached=1 WHERE source=? AND id=?', (source, attachment_id))

    async def upload(self, source, files):
        if not files or len(files) > MAX_FILES:
            raise HTTPException(422, 'Choose 1–10 attachments.')
        staged = []
        total = 0
        try:
            for upload in files:
                name = (upload.filename or 'attachment').replace('\\', '/').rsplit('/', 1)[-1]
                name = re.sub(r'[\x00-\x1f\x7f]', '', name)[:180] or 'attachment'
                attachment_id = uuid.uuid4().hex
                suffix = Path(name).suffix.lower()
                suffix = suffix if re.fullmatch(r'\.[a-z0-9]{1,12}', suffix) else ''
                manifest = {'id': attachment_id, 'name': name, 'filename': attachment_id + suffix, 'size': 0}
                digest = hashlib.sha256()
                with tempfile.NamedTemporaryFile(dir=self.root, prefix='.upload-', delete=False) as target:
                    staged.append((Path(target.name), manifest))
                    while chunk := await upload.read(1024 * 1024):
                        manifest['size'] += len(chunk)
                        total += len(chunk)
                        if manifest['size'] > MAX_FILE_BYTES or total > MAX_TOTAL_BYTES:
                            raise HTTPException(413, 'Attachments allow 50 MB per file and 200 MB total.')
                        digest.update(chunk)
                        target.write(chunk)
                manifest['digest'] = digest.hexdigest()
            with self.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                existing = [json.loads(row['manifest']) for row in db.execute('SELECT manifest FROM input_attachments WHERE source=? AND detached=0', (source,))]
                # An uncertain upload can be retried without duplicating identical files.
                unique = []
                identities = {(m['name'], m['digest']) for m in existing}
                for path, manifest in staged:
                    identity = (manifest['name'], manifest['digest'])
                    if identity not in identities:
                        unique.append((path, manifest))
                        identities.add(identity)
                if len(existing) + len(unique) > MAX_FILES or sum(m['size'] for m in existing) + sum(m['size'] for _, m in unique) > MAX_TOTAL_BYTES:
                    raise HTTPException(413, 'A task allows 10 attachments and 200 MB total.')
                for path, manifest in unique:
                    destination = self.root / manifest['digest']
                    if destination.is_symlink():
                        raise HTTPException(400, 'Invalid attachment storage.')
                    if not destination.exists():
                        path.replace(destination)
                    db.execute('INSERT INTO input_attachments(id,source,manifest) VALUES (?,?,?)', (manifest['id'], source, json.dumps(manifest)))
            return self.list(source)
        finally:
            for path, _ in staged:
                path.unlink(missing_ok=True)
            for upload in files:
                await upload.close()


def source_store(kind, source_id):
    from modules.hfl_corpus import timeline
    from modules.hfl_corpus.memory_pins import get_memory_pin_store
    if kind == 'actionable':
        database = timeline.store().path
    elif kind == 'pin':
        database = get_memory_pin_store().path
    else:
        raise HTTPException(422, 'Choose actionable or pin.')
    return AttachmentStore(database), f'{kind}:{source_id}'


def require_source(kind, source_id):
    from modules.hfl_corpus import timeline
    from modules.hfl_corpus.memory_pins import get_memory_pin_store
    if kind == 'actionable':
        try:
            timeline.store().get(source_id)
            return
        except KeyError:
            pass
    elif kind == 'pin' and any(str(p['id']) == str(source_id) for p in get_memory_pin_store().snapshot()['ranges']):
        return
    raise HTTPException(404, 'Action or active pin not found.')
