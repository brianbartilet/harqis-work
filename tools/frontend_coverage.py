"""Check the reviewed frontend-to-MCP coverage contract without loading apps.

Run ``python -m tools.frontend_coverage --check`` after changing frontend routes.
The manifest records explicit aliases/exclusions as well as implemented tools.
"""
from __future__ import annotations

import argparse
import ast
from collections import Counter
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / 'frontend/mcp_coverage.json'
METHODS = {'get', 'post', 'put', 'patch', 'delete', 'head', 'options', 'websocket', 'api_route'}


def inventory(root: Path = ROOT) -> dict[tuple[str, str], dict]:
    """Resolve mounted routes from source, including nested and aliased routers."""
    cache = {}

    def module(name):
        if name in cache:
            return cache[name]
        path = root.joinpath(*name.split('.')).with_suffix('.py')
        imports, routers, routes, includes = {}, {}, [], []
        tree = ast.parse(path.read_text(encoding='utf-8-sig'))
        for node in tree.body:
            if isinstance(node, ast.ImportFrom) and node.module:
                source = node.module
                if source.startswith('modules.'):
                    source = 'frontend.' + source
                for alias in node.names:
                    imports[alias.asname or alias.name] = (source, alias.name)
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
                call = node.value
                if isinstance(call.func, ast.Name) and call.func.id in {'APIRouter', 'FastAPI'}:
                    prefix = next((ast.literal_eval(k.value) for k in call.keywords if k.arg == 'prefix'), '')
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            routers[target.id] = prefix
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for call in node.decorator_list:
                    if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Attribute) or call.func.attr not in METHODS:
                        continue
                    methods = next((ast.literal_eval(k.value) for k in call.keywords if k.arg == 'methods'), [call.func.attr.upper()])
                    for method in methods:
                        routes.append((call.func.value.id, method, ast.literal_eval(call.args[0]), node.name, call.lineno))
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Attribute):
                call = node.value
                if call.func.attr in {'add_api_route', 'add_route'}:
                    raise ValueError(f'Review dynamic registration in {path}:{node.lineno}')
                if call.func.attr == 'include_router':
                    prefix = next((ast.literal_eval(k.value) for k in call.keywords if k.arg == 'prefix'), '')
                    includes.append((call.func.value.id, call.args[0].id, prefix))
        cache[name] = imports, routers, routes, includes
        return cache[name]

    result = {}

    def mount(name, router, prefix=''):
        imports, routers, routes, includes = module(name)
        prefix += routers[router]
        for owner, method, path, handler, line in routes:
            if owner == router:
                key = method, prefix + path
                if key in result:
                    raise ValueError(f'Duplicate frontend route: {key}')
                result[key] = {'source': name.replace('.', '/') + '.py', 'handler': handler, 'line': line}
        for owner, child, extra in includes:
            if owner == router:
                child_module, child_router = imports.get(child, (name, child))
                mount(child_module, child_router, prefix + extra)

    mount('frontend.main', 'app')
    return result


def check(root: Path = ROOT) -> dict:
    actual = inventory(root)
    document = json.loads((root / 'frontend/mcp_coverage.json').read_text(encoding='utf-8'))
    entries = document['endpoints']
    recorded = {(row['method'], row['path']): row for row in entries}
    errors = []
    if len(entries) != len(recorded):
        errors.append('Duplicate method/path rows in MCP coverage manifest')
    for method, path in sorted(actual.keys() - recorded.keys()):
        errors.append(f'Unreviewed frontend route: {method} {path}')
    for method, path in sorted(recorded.keys() - actual.keys()):
        errors.append(f'Stale coverage row: {method} {path}')
    tools = set()
    for base in ('apps', 'workflows'):
        for path in (root / base).glob('*/mcp.py'):
            for node in ast.walk(ast.parse(path.read_text(encoding='utf-8-sig'))):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and any(
                    isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.func.attr == 'tool'
                    for d in node.decorator_list
                ):
                    tools.add(node.name)
    for key, row in recorded.items():
        status = row['status']
        if status not in {'covered', 'service', 'alias', 'deferred', 'ui', 'protocol'}:
            errors.append(f'Unknown coverage status for {key}: {status}')
        if not row.get('reason'):
            errors.append(f'Missing coverage rationale for {key}')
        if status in {'covered', 'service', 'alias'} and not row.get('tools'):
            errors.append(f'Missing tool mapping for {key}')
        for tool in row.get('tools', []):
            if tool not in tools:
                errors.append(f'Missing MCP tool {tool} for {key}')
        if key[1].startswith('/api/hfl/') and status != 'covered':
            errors.append(f'Canonical HFL endpoint needs a dedicated tool: {key}')
    return {'ok': not errors, 'endpoints': len(actual), 'coverage': dict(Counter(r['status'] for r in entries)), 'errors': errors}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Fail if routes or tool mappings drift')
    parser.parse_args()
    result = check()
    print(json.dumps(result, indent=2))
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
