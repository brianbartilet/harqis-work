"""
Local vector store backed by sqlite-vec.

A single SQLite file holds two paired tables:

    chunks(id TEXT PRIMARY KEY, source TEXT, ref TEXT, text TEXT, meta_json TEXT)
    vec_chunks(rowid, embedding FLOAT[<dim>])  -- vec0 virtual table

`upsert()` writes one row per chunk plus its embedding; `search()` runs a KNN
query against the vec0 table and joins back to chunks for the payload.

Design choices:
  - Cosine distance via vec0's default L2 on normalised vectors. We normalise
    on write so search() can use plain L2 and still behave like cosine.
  - String chunk ids — callers compose stable keys like
    f"{page_id}:{chunk_idx}" so re-ingesting a page replaces its chunks.
  - meta is round-tripped as JSON to avoid schema churn per source.

Not designed for >~5M chunks. For larger corpora swap the backing file for
qdrant/pgvector — the upsert/search interface stays the same.
"""

from __future__ import annotations

import json
import math
import os
import sqlite3
import struct
import threading
from pathlib import Path
from typing import Any, Iterable, Optional

try:
    import sqlite_vec  # type: ignore
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "sqlite-vec is required for apps/sqlite_vec — "
        "install with: pip install sqlite-vec>=0.1.6"
    ) from exc


_DEFAULT_DB = (
    Path(os.environ.get("HARQIS_VECTOR_DB"))
    if os.environ.get("HARQIS_VECTOR_DB")
    else Path(__file__).resolve().parents[2] / "data" / "vector_store.db"
)

_CONN_LOCK = threading.Lock()
_CONN_CACHE: dict[str, sqlite3.Connection] = {}


def _open(db_path: Path, dim: int) -> sqlite3.Connection:
    """Open (or reuse) a connection with sqlite-vec loaded and tables ensured."""
    key = f"{db_path}:{dim}"
    with _CONN_LOCK:
        conn = _CONN_CACHE.get(key)
        if conn is not None:
            return conn

        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(db_path), check_same_thread=False)
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS chunks (
                id        TEXT PRIMARY KEY,
                source    TEXT NOT NULL,
                ref       TEXT,
                text      TEXT NOT NULL,
                meta_json TEXT
            )
            """
        )
        conn.execute(
            f"CREATE VIRTUAL TABLE IF NOT EXISTS vec_chunks "
            f"USING vec0(embedding FLOAT[{dim}])"
        )
        conn.commit()
        _CONN_CACHE[key] = conn
        return conn


def _l2_normalise(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def _serialise(vec: list[float]) -> bytes:
    """sqlite-vec expects little-endian packed float32 for FLOAT[N] columns."""
    return struct.pack(f"<{len(vec)}f", *vec)


def upsert(
    chunk_id: str,
    text: str,
    embedding: list[float],
    source: str,
    ref: Optional[str] = None,
    meta: Optional[dict[str, Any]] = None,
    *,
    db_path: Optional[Path] = None,
) -> None:
    """Insert or replace a single chunk + embedding pair.

    Args:
        chunk_id:  Stable string id. Reusing an id replaces the row.
        text:      The raw chunk text (returned by search).
        embedding: Vector — any dim; the table is created on first call.
        source:    Logical corpus label (e.g. 'notion', 'jira', 'harqis-code').
        ref:       Optional pointer back to the origin (URL, page id, file path).
        meta:      Free-form dict serialised to JSON.
        db_path:   Override the default store path.
    """
    db = db_path or _DEFAULT_DB
    vec = _l2_normalise(embedding)
    conn = _open(db, dim=len(vec))

    cur = conn.execute("SELECT rowid FROM chunks WHERE id = ?", (chunk_id,))
    row = cur.fetchone()

    meta_json = json.dumps(meta) if meta is not None else None

    if row is None:
        cur = conn.execute(
            "INSERT INTO chunks (id, source, ref, text, meta_json) VALUES (?, ?, ?, ?, ?)",
            (chunk_id, source, ref, text, meta_json),
        )
        rowid = cur.lastrowid
        conn.execute(
            "INSERT INTO vec_chunks(rowid, embedding) VALUES (?, ?)",
            (rowid, _serialise(vec)),
        )
    else:
        rowid = row[0]
        conn.execute(
            "UPDATE chunks SET source=?, ref=?, text=?, meta_json=? WHERE rowid=?",
            (source, ref, text, meta_json, rowid),
        )
        conn.execute("DELETE FROM vec_chunks WHERE rowid = ?", (rowid,))
        conn.execute(
            "INSERT INTO vec_chunks(rowid, embedding) VALUES (?, ?)",
            (rowid, _serialise(vec)),
        )

    conn.commit()


def upsert_many(
    rows: Iterable[dict[str, Any]],
    *,
    db_path: Optional[Path] = None,
) -> int:
    """Batch helper. Each row must have keys: id, text, embedding, source. Optional: ref, meta."""
    n = 0
    for r in rows:
        upsert(
            chunk_id=r["id"],
            text=r["text"],
            embedding=r["embedding"],
            source=r["source"],
            ref=r.get("ref"),
            meta=r.get("meta"),
            db_path=db_path,
        )
        n += 1
    return n


def search(
    embedding: list[float],
    k: int = 5,
    source: Optional[str] = None,
    *,
    db_path: Optional[Path] = None,
) -> list[dict[str, Any]]:
    """KNN search. Returns up to k chunks ordered by similarity (best first).

    Each result is:
        {id, source, ref, text, meta, distance}

    `distance` is L2 over the L2-normalised vectors — equivalent to
    sqrt(2 - 2·cosine), so smaller = more similar.
    """
    db = db_path or _DEFAULT_DB
    vec = _l2_normalise(embedding)
    conn = _open(db, dim=len(vec))

    if source:
        sql = """
            SELECT c.id, c.source, c.ref, c.text, c.meta_json, v.distance
            FROM vec_chunks v
            JOIN chunks c ON c.rowid = v.rowid
            WHERE v.embedding MATCH ? AND k = ? AND c.source = ?
            ORDER BY v.distance
        """
        params = (_serialise(vec), k, source)
    else:
        sql = """
            SELECT c.id, c.source, c.ref, c.text, c.meta_json, v.distance
            FROM vec_chunks v
            JOIN chunks c ON c.rowid = v.rowid
            WHERE v.embedding MATCH ? AND k = ?
            ORDER BY v.distance
        """
        params = (_serialise(vec), k)

    out: list[dict[str, Any]] = []
    for cid, src, ref, text, meta_json, dist in conn.execute(sql, params):
        out.append({
            "id": cid,
            "source": src,
            "ref": ref,
            "text": text,
            "meta": json.loads(meta_json) if meta_json else None,
            "distance": float(dist),
        })
    return out


def delete_by_source(source: str, *, db_path: Optional[Path] = None) -> int:
    """Drop every chunk whose `source` matches. Used by full re-ingests."""
    db = db_path or _DEFAULT_DB
    conn = _open(db, dim=1)  # dim irrelevant for delete; vec0 already exists if we got here
    cur = conn.execute("SELECT rowid FROM chunks WHERE source = ?", (source,))
    rowids = [r[0] for r in cur.fetchall()]
    if not rowids:
        return 0
    qmarks = ",".join(["?"] * len(rowids))
    conn.execute(f"DELETE FROM vec_chunks WHERE rowid IN ({qmarks})", rowids)
    conn.execute("DELETE FROM chunks WHERE source = ?", (source,))
    conn.commit()
    return len(rowids)


def stats(*, db_path: Optional[Path] = None) -> dict[str, Any]:
    """Counts per source — handy for ingestion smoke checks."""
    db = db_path or _DEFAULT_DB
    if not db.exists():
        return {"total": 0, "by_source": {}}
    conn = _open(db, dim=1)
    by_source: dict[str, int] = {}
    for src, n in conn.execute("SELECT source, COUNT(*) FROM chunks GROUP BY source"):
        by_source[src] = n
    total = sum(by_source.values())
    return {"total": total, "by_source": by_source, "path": str(db)}
