"""Shared application presentation overrides, separate from source inventory."""
import hashlib
import io
import sqlite3
import warnings
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError
from config import get_settings

MAX_IMAGE_BYTES = 2 * 1024 * 1024


@contextmanager
def connection():
    path = Path(get_settings().profile_store_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=15)
    db.row_factory = sqlite3.Row
    try:
        db.execute("CREATE TABLE IF NOT EXISTS application_display_settings (app_key TEXT PRIMARY KEY, display_name TEXT NOT NULL, icon BLOB NOT NULL DEFAULT X'')")
        with db:
            yield db
    finally:
        db.close()


def decorate(applications):
    with connection() as db:
        rows = {row['app_key']: row for row in db.execute('SELECT * FROM application_display_settings')}
    return tuple(replace(app, label=rows[app.key]['display_name'],
                         icon_version=hashlib.sha256(rows[app.key]['icon']).hexdigest()[:16] if rows[app.key]['icon'] else '')
                 if app.key in rows else app for app in applications)


def icon(app_key):
    with connection() as db:
        row = db.execute('SELECT icon FROM application_display_settings WHERE app_key=?', (app_key,)).fetchone()
    return bytes(row['icon']) if row else b''


def normalize_image(raw):
    if len(raw) > MAX_IMAGE_BYTES:
        raise ValueError('Choose an image no larger than 2 MB.')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as source:
                if source.format not in {'PNG', 'JPEG', 'WEBP'} or source.width * source.height > 25_000_000:
                    raise ValueError('unsupported image')
                source.verify()
            with Image.open(io.BytesIO(raw)) as source:
                normalized = ImageOps.exif_transpose(source).convert('RGBA')
                normalized.thumbnail((256, 256), Image.Resampling.LANCZOS)
                output = io.BytesIO()
                normalized.save(output, format='WEBP', lossless=True)
                return output.getvalue()
    except (Image.DecompressionBombError, Image.DecompressionBombWarning, UnidentifiedImageError, OSError, ValueError):
        raise ValueError('Choose a valid PNG, JPEG, or WebP image with at most 25 million pixels.') from None


def save(app_key, name, image=None):
    name = name.strip()
    if not name or len(name) > 80 or any(ord(c) < 32 or ord(c) == 127 for c in name):
        raise ValueError('Enter a display name between 1 and 80 characters, without control characters.')
    with connection() as db:
        if image is None:
            db.execute("INSERT INTO application_display_settings (app_key,display_name) VALUES (?,?) ON CONFLICT(app_key) DO UPDATE SET display_name=excluded.display_name", (app_key, name))
        else:
            db.execute('INSERT INTO application_display_settings VALUES (?,?,?) ON CONFLICT(app_key) DO UPDATE SET display_name=excluded.display_name,icon=excluded.icon', (app_key, name, image))


def reset(app_key):
    with connection() as db:
        db.execute('DELETE FROM application_display_settings WHERE app_key=?', (app_key,))
