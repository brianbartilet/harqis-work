"""Owner documentation hub; discover MCP source without importing app services."""
import ast
import json
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, Request
from tools.catalog import APP_CATALOG
from web import page_context, require_user, templates

router = APIRouter()
ROOT = Path(__file__).resolve().parents[1]


@lru_cache(maxsize=128)
def _read_tools(path: str, modified: int, size: int, registrar: str):
    tree = ast.parse(Path(path).read_text(encoding='utf-8-sig'))
    registration = next((node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == registrar), None)
    if registration is None:
        raise ValueError('Registrar not found')
    tools = []
    for node in ast.walk(registration):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        decorator = next((d for d in node.decorator_list if isinstance(d, ast.Call)
            and isinstance(d.func, ast.Attribute) and d.func.attr == 'tool'), None)
        if decorator is None:
            continue
        name = next((k.value.value for k in decorator.keywords if k.arg == 'name'
            and isinstance(k.value, ast.Constant) and isinstance(k.value.value, str)), node.name)
        tools.append({'name': name, 'description': ast.get_docstring(node) or 'No description supplied.',
                      'signature': name + '(' + ast.unparse(node.args) + ')'})
    return sorted(tools, key=lambda tool: tool['name'])


def mcp_catalogue():
    apps = []
    for spec in APP_CATALOG:
        module, registrar = spec.registrar.rsplit('.', 1)
        relative = module.replace('.', '/') + '.py'
        path = ROOT / relative
        try:
            stat = path.stat()
            tools = _read_tools(str(path), stat.st_mtime_ns, stat.st_size, registrar)
            note = '' if tools else 'No decorated tools found in this registrar. Check the runtime tool list for dynamic registrations.'
        except (OSError, SyntaxError, ValueError):
            tools, note = [], 'Source documentation is unavailable for this app.'
        apps.append({'key': spec.key, 'label': spec.label, 'source': relative, 'tools': tools, 'note': note})
    return apps


@router.get('/developer-tools', include_in_schema=False)
def hub(request: Request):
    user, redirect = require_user(request)
    if redirect:
        return redirect
    schema = request.app.openapi()
    apps = mcp_catalogue()
    examples = {
        'mac': {'mcpServers': {'harqis-work': {'command': '/absolute/path/to/harqis-work/.venv/bin/python',
            'args': ['/absolute/path/to/harqis-work/mcp/server.py'], 'env': {}}}},
        'windows': {'mcpServers': {'harqis-work': {'command': 'C:\\path\\to\\harqis-work\\.venv\\Scripts\\python.exe',
            'args': ['C:\\path\\to\\harqis-work\\mcp\\server.py'], 'env': {}}}},
    }
    return templates.TemplateResponse(request, 'developer_tools.html', page_context(
        request, user, 'api_docs', api_paths=len(schema['paths']),
        api_operations=sum(len(ops) for ops in schema['paths'].values()),
        mcp_apps=apps, mcp_tool_count=sum(len(app['tools']) for app in apps),
        mcp_examples={key: json.dumps(value, indent=2) for key, value in examples.items()}))
