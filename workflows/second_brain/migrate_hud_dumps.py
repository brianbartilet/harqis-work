"""One-time bounded ingestion of legacy dumps. No collectors or desktop commands.

Run with the normal HARQIS environment bootstrap. Default is metadata-only preview;
``--publish`` writes redacted projections, preserving file timestamps/freshness.
"""
import argparse
from datetime import datetime, timezone
from pathlib import Path

from workflows.second_brain.hud_projection import (
    HUD_PROJECTION_INDEX, _bounded_payload, _projection_source,
)
from workflows.second_brain.models import isoformat
from workflows.second_brain.registry import OPERATIONS

MIGRATION_INDEX = 'harqis-second-brain-hud-migration'


def legacy_dump(projection: dict, skins_root: Path):
    payload = projection.get('payload') or {}
    if payload.get('text') or payload.get('feed_text'):
        return None
    raw_path = payload.get('notes_path')
    if not isinstance(raw_path, str) or not raw_path:
        return None
    path = Path(raw_path).resolve()
    try:
        path.relative_to(skins_root.resolve())
    except ValueError:
        return None
    if path.name != 'dump.txt' or not path.is_file():
        return None
    with path.open('rb') as stream:
        raw = stream.read(64 * 1024)
    try:
        text = raw.decode('utf-8')
    except UnicodeDecodeError:
        text = raw.decode('cp1252', errors='replace')
    if not text.strip():
        return None
    captured = isoformat(datetime.fromtimestamp(path.stat().st_mtime, timezone.utc))
    # A historical file cannot make an older capture appear freshly generated.
    return _bounded_payload({'text': text, 'links': payload.get('links', {}), 'migration': 'legacy-dump'}), captured


def migrate(*, publish=False):
    from apps.rainmeter.config import CONFIG
    from core.apps.es_logging.app.elasticsearch import get_index_data, post
    root = Path(CONFIG['write_skin_to_path']) / CONFIG['skin_name']
    allowed = {op.source_task for op in OPERATIONS.values() if op.source_task}
    rows = [_projection_source(row) for row in get_index_data(HUD_PROJECTION_INDEX, fetch_docs=250, timeout=8)]
    latest = {}
    for row in rows:
        source = row.get('source_task')
        if source in allowed and str(row.get('captured_at', '')) > str(latest.get(source, {}).get('captured_at', '')):
            latest[source] = row
    results = []
    for source, row in latest.items():
        migrated = legacy_dump(row, root)
        if not migrated:
            continue
        payload, captured = migrated
        if publish:
            # Keep the live index untouched while old workers still publish
            # path-only payloads. Stable IDs make rerunning this idempotent.
            post(json_dump={'source_task': source, 'captured_at': captured, 'payload': payload},
                 index_name=MIGRATION_INDEX, location_key=source, use_interval_map=False)
        results.append({'source_task': source, 'captured_at': captured, 'characters': len(payload.get('text', '')), 'published': publish})
    return results


if __name__ == '__main__':
    import json
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--publish', action='store_true')
    print(json.dumps(migrate(publish=parser.parse_args().publish), indent=2))
