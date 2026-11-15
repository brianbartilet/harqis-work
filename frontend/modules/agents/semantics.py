from pathlib import Path
import json
ENTITY_SEMANTICS = json.loads((Path(__file__).resolve().parents[2] / 'static/entity-semantics.json').read_text(encoding='utf8'))
