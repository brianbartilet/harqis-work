"""Import a pinned Agency Agents source archive without executing upstream code.

Usage: python -m tools.agency_catalog archive.zip --revision <40-character SHA>
"""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import zipfile

import yaml

ROOT = Path(__file__).resolve().parents[1] / 'agents/prompts/agency'


def import_catalog(archive, revision, destination=ROOT):
    if not re.fullmatch(r'[0-9a-f]{40}', revision):
        raise ValueError('Supply a full upstream commit SHA.')
    helpers = json.loads((destination / 'helpers.json').read_text(encoding='utf-8'))
    profiles, files, identities = [], {}, set()
    with zipfile.ZipFile(archive) as source:
        prefix = f'agency-agents-{revision}/'
        divisions = json.loads(source.read(prefix + 'divisions.json'))['divisions']
        for filename in sorted(source.namelist()):
            if not filename.startswith(prefix):
                continue
            relative = PurePosixPath(filename[len(prefix):])
            if not relative.parts or relative.parts[0] not in divisions or relative.suffix != '.md':
                continue
            content = source.read(filename)
            match = re.match(r'\A---\s*\n(.*?)\n---\s*\n', content.decode('utf-8-sig'), re.S)
            if not match:
                continue
            metadata = yaml.safe_load(match.group(1))
            if not isinstance(metadata, dict) or not metadata.get('name') or not metadata.get('description'):
                continue
            identity = relative.stem
            if not re.fullmatch(r'[a-zA-Z0-9_-]+', identity) or identity in identities:
                raise ValueError(f'Invalid or duplicate profile ID: {identity}')
            identities.add(identity)
            division = relative.parts[0]
            classification = 'coding' if division in {'engineering','testing','security','game-development','spatial-computing'} else 'general'
            row = dict(id=identity, name=str(metadata['name']), description=str(metadata['description']),
                       division=divisions[division]['label'], classification=classification,
                       path=str(relative), hash=hashlib.sha256(content).hexdigest(), skills=[])
            row.update(helpers.get(identity, {}))
            profiles.append(row)
            files[identity + '.md'] = content
        license_bytes = source.read(prefix + 'LICENSE')
        divisions_bytes = source.read(prefix + 'divisions.json')
    # Preserve the pilot ordering; all other profiles are sorted by source path.
    profiles.sort(key=lambda row: (list(helpers).index(row['id']) if row['id'] in helpers else len(helpers), row['path']))
    (destination / 'upstream').mkdir(parents=True, exist_ok=True)
    for filename, content in files.items():
        (destination / 'upstream' / filename).write_bytes(content)
    (destination / 'LICENSE').write_bytes(license_bytes)
    (destination / 'divisions.json').write_bytes(divisions_bytes)
    (destination / 'manifest.json').write_text(json.dumps({'revision':revision,'profiles':profiles},indent=2)+'\n',encoding='utf-8')
    return len(profiles)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', type=Path)
    parser.add_argument('--revision', required=True)
    args = parser.parse_args()
    print(f'Imported {import_catalog(args.archive, args.revision)} profiles.')
