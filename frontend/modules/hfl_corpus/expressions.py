"""Bounded corpus expression grammar; never evaluate user input as code."""
import json
import re
from datetime import date
from functools import lru_cache
from pathlib import PurePosixPath
from urllib.parse import urlsplit

TOKEN = re.compile(r'\s*("(?:\\.|[^"\\])*"|>=|<=|!=|!~|[=~><(),]|[A-Za-z_][A-Za-z_0-9]*|\d+)')
FIELDS = {'q', 'text', 'tags', 'source', 'hasMedia', 'entryDate', 'created', 'updated',
          'dateField', 'dateFrom', 'dateTo', 'rolling', 'sort', 'pageSize'}
SETTINGS = {'dateField': 'date_field', 'dateFrom': 'date_from', 'dateTo': 'date_to',
            'rolling': 'rolling', 'sort': 'sort', 'pageSize': 'page_size'}


@lru_cache(maxsize=256)
def parse(expression):
    if len(expression) > 12000:
        raise ValueError('Expression is too long (maximum 12,000 characters).')
    tokens, pos = [], 0
    while pos < len(expression.rstrip()):
        match = TOKEN.match(expression, pos)
        if not match:
            raise ValueError(f'Unexpected character at position {pos + 1}. Quote text values.')
        tokens.append(match[1]); pos = match.end()
    if len(tokens) > 1000:
        raise ValueError('Expression has too many terms.')
    index = 0
    def peek():
        return tokens[index] if index < len(tokens) else ''
    def take(expected=None):
        nonlocal index
        value = peek()
        if not value or (expected and value.upper() != expected):
            raise ValueError(f'Expected {expected or "a value"} at token {index + 1}.')
        index += 1
        return value
    def value():
        raw = take()
        if raw.startswith('"'):
            try:
                return json.loads(raw)
            except ValueError as exc:
                raise ValueError('Invalid quoted value.') from exc
        if raw.lower() in {'true', 'false'}:
            return raw.lower() == 'true'
        if raw.isdigit():
            return int(raw)
        raise ValueError('Text and date values must be double-quoted.')
    def primary(depth):
        if depth > 24:
            raise ValueError('Expression nesting is too deep.')
        if peek().upper() == 'NOT':
            take(); return ('not', primary(depth + 1))
        if peek() == '(':
            take(); node = boolean(depth + 1); take(')'); return node
        field = take()
        if field not in FIELDS:
            raise ValueError(f'Unknown field: {field}.')
        op = take().upper()
        if op == 'NOT':
            take('IN'); op = 'NOT IN'
        if op in {'IN', 'NOT IN'}:
            take('('); values = [value()]
            while peek() == ',':
                take(); values.append(value())
            take(')'); val = tuple(values)
        else:
            val = value()
        allowed = {'=', '!=', 'IN', 'NOT IN', '~', '!~'}
        if field in {'entryDate', 'created', 'updated'}:
            allowed = {'=', '!=', '>', '>=', '<', '<='}
            if not isinstance(val, str):
                raise ValueError('Dates must be quoted ISO dates.')
            date.fromisoformat(val)
        elif field == 'hasMedia':
            allowed = {'=', '!='}
            if not isinstance(val, bool):
                raise ValueError('hasMedia requires true or false.')
        elif field in SETTINGS:
            allowed = {'='}
        elif field == 'q':
            allowed = {'~', '!~'}
            if not isinstance(val, str):
                raise ValueError('q requires quoted text.')
        elif not all(isinstance(v, str) for v in (val if isinstance(val, tuple) else (val,))):
            raise ValueError(f'{field} requires quoted text values.')
        if op not in allowed:
            raise ValueError(f'Operator {op} is not supported for {field}.')
        return ('term', field, op, val)
    def conjunction(depth):
        node = primary(depth)
        while peek().upper() == 'AND':
            take(); node = ('and', node, primary(depth))
        return node
    def boolean(depth):
        node = conjunction(depth)
        while peek().upper() == 'OR':
            take(); node = ('or', node, conjunction(depth))
        return node
    if not tokens:
        return None
    node = boolean(0)
    if peek():
        raise ValueError(f'Expected AND or OR at token {index + 1}.')
    return node


def render(node):
    if node is None:
        return ''
    if node[0] == 'term':
        _, field, op, value = node
        literal = '(' + ', '.join(json.dumps(v, ensure_ascii=False) for v in value) + ')' if isinstance(value, tuple) else json.dumps(value, ensure_ascii=False)
        return f'{field} {op} {literal}'
    if node[0] == 'not':
        return f'NOT ({render(node[1])})'
    return f'({render(node[1])} {node[0].upper()} {render(node[2])})'


def terms(node):
    if node and node[0] == 'and':
        yield from terms(node[1]); yield from terms(node[2])
    elif node:
        yield node


def normalize_tags(value):
    return ','.join(dict.fromkeys(tag.strip().lstrip('#').casefold() for tag in value.split(',') if tag.strip().lstrip('#')))


def has_media(entry):
    from modules.hfl_corpus.corpus import _entry_metadata
    refs = _entry_metadata(entry.header, entry.text)[1]
    # Recognized media references, plus Markdown/HTML media embedded in the entry.
    candidates = [*refs, *re.findall(r'!\[[^\]]*\]\(([^)]+)\)', entry.text),
                  *re.findall(r'<(?:img|video|source)\b[^>]*src=["\x27]([^"\x27]+)', entry.text, re.I)]
    extensions = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.avif', '.bmp', '.svg', '.heic', '.mp4', '.webm', '.mov', '.m4v', '.avi', '.mkv'}
    for raw in candidates:
        try:
            if PurePosixPath(urlsplit(str(raw).replace('\\', '/')).path).suffix.lower() in extensions:
                return True
        except ValueError:
            continue
    return False


def compile_expression(expression):
    node = parse(expression)
    def compile_node(node):
        if node is None:
            return lambda doc, entry: True
        kind = node[0]
        if kind == 'not':
            child = compile_node(node[1]); return lambda doc, entry: not child(doc, entry)
        if kind in {'and', 'or'}:
            left, right = compile_node(node[1]), compile_node(node[2])
            return (lambda doc, entry: left(doc, entry) and right(doc, entry)) if kind == 'and' else (lambda doc, entry: left(doc, entry) or right(doc, entry))
        _, field, op, value = node
        if field in SETTINGS:
            raise ValueError(f'{field} must be a top-level AND condition.')
        def matches(doc, entry):
            from modules.hfl_corpus.corpus import entry_occurrence_date, parse_search_query
            if field in {'entryDate', 'created', 'updated'}:
                actual = entry_occurrence_date(entry) if field == 'entryDate' else getattr(doc, field + '_at').date()
                if actual is None:
                    return False
                target = date.fromisoformat(value)
                return {'=': actual == target, '!=': actual != target, '>': actual > target,
                        '>=': actual >= target, '<': actual < target, '<=': actual <= target}[op]
            if field == 'hasMedia':
                result = has_media(entry) == value
            else:
                values = value if isinstance(value, tuple) else (value,)
                actuals = entry.tags if field == 'tags' else (entry.source,) if field == 'source' else (entry.text,)
                if field == 'q':
                    def query_match(v):
                        tags, phrase = parse_search_query(v)
                        return all(any(t in tag.casefold() for tag in entry.tags) for t in tags) and phrase in entry.text.casefold()
                    result = any(query_match(v) for v in values)
                else:
                    normalize = lambda v: v.casefold().lstrip('#') if field == 'tags' else v.casefold()
                    result = any(normalize(v) in normalize(a) if op in {'~', '!~'} else normalize(v) == normalize(a) for a in actuals for v in values)
            return not result if op in {'!=', '!~', 'NOT IN'} else result
        return matches
    return compile_node(node)


def project(expression):
    """Extract only faithfully representable global conditions; retain all branches."""
    from modules.hfl_corpus.ordering import split_order, parse_order
    expression, order_by = split_order(expression)
    state, remaining = {}, []
    for node in terms(parse(expression)):
        if node[0] != 'term':
            remaining.append(node); continue
        _, field, op, value = node
        key, converted = None, value
        if field in SETTINGS and op == '=':
            key = SETTINGS[field]
        elif op == '~' and (field == 'q' or (field == 'text' and '#' not in value and ' '.join(value.split()) == value)):
            key = 'q'
        elif field == 'source' and op in {'=', 'IN'} and all(v and ',' not in v and v.strip() == v for v in (value if isinstance(value, tuple) else (value,))):
            key, converted = 'source', ','.join(value) if isinstance(value, tuple) else value
        elif field == 'hasMedia' and op == '=' and value is True:
            key = 'has_media'
        elif field == 'tags' and op == 'NOT IN' and all(',' not in v for v in value):
            key, converted = 'exclude_tags', normalize_tags(','.join(value))
        if key and key not in state:
            state[key] = converted
        else:
            remaining.append(node)
    state['expression'] = ' AND '.join(f'({render(node)})' for node in remaining)
    compile_expression(state['expression'])
    if order_by:
        direction = parse_order(order_by)[0][1].lower()
        if 'sort' in state and state['sort'] != direction:
            raise ValueError('sort conflicts with the first ORDER BY direction.')
        state.update(order_by=order_by, sort=direction)
    return state


def generate(state):
    clauses = []
    def add(field, op, value):
        clauses.append(render(('term', field, op, value)))
    if state.get('q'):
        add('q', '~', state['q'])
    if state.get('source'):
        add('source', 'IN', tuple(state['source'].split(',')))
    if state.get('has_media'):
        add('hasMedia', '=', True)
    if state.get('exclude_tags'):
        add('tags', 'NOT IN', tuple(normalize_tags(state['exclude_tags']).split(',')))
    for field, key in SETTINGS.items():
        if key == 'sort' and state.get('order_by'):
            continue
        if state.get(key) not in ('', None, 0):
            add(field, '=', state[key])
    if state.get('expression'):
        clauses.append('(' + state['expression'] + ')')
    expression = ' AND '.join(clauses)
    if state.get('order_by'):
        from modules.hfl_corpus.ordering import normalize_order
        expression += ' ORDER BY ' + normalize_order(state['order_by'], state.get('sort'))
    return expression.strip()
