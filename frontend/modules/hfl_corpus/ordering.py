"""Stable, entry-aware ordering shared by corpus, feeds, and recipes."""
import re
from dataclasses import replace
from datetime import datetime, timezone
from functools import cmp_to_key

ORDER_FIELDS = ('source', 'entryDate', 'created', 'updated')


def parse_order(value):
    if not value:
        return ()
    if not isinstance(value, str) or len(value) > 200:
        raise ValueError('ORDER BY is too long.')
    result = []
    for part in value.split(','):
        match = re.fullmatch(r'\s*([A-Za-z]+)(?:\s+(ASC|DESC))?\s*', part, re.I)
        if not match or match[1] not in ORDER_FIELDS:
            raise ValueError('ORDER BY accepts source, entryDate, created, updated and ASC/DESC.')
        if any(field == match[1] for field, _ in result):
            raise ValueError(f'Duplicate ORDER BY field: {match[1]}.')
        result.append((match[1], (match[2] or 'ASC').upper()))
    return tuple(result)


def normalize_order(value, direction=None):
    parts = list(parse_order(value))
    if parts and direction:
        parts[0] = (parts[0][0], direction.upper())
    return ', '.join(f'{field} {order}' for field, order in parts)


def split_order(expression):
    # Quoted text can contain ORDER BY literally; only unquoted tokens are clauses.
    matches = [m for m in re.finditer(r'"(?:\\.|[^"\\])*"|\bORDER\s+BY\b', expression, re.I) if not m[0].startswith('"')]
    if not matches:
        return expression, ''
    if len(matches) != 1:
        raise ValueError('Use one trailing ORDER BY clause.')
    clause = expression[matches[0].end():].strip()
    if not clause:
        raise ValueError('ORDER BY requires at least one field.')
    return expression[:matches[0].start()].strip(), normalize_order(clause)


def entry_key(document, entry, ordering):
    values = []
    for field, _ in ordering:
        if field == 'source':
            value = entry.source.strip().casefold() or None if entry else None
        else:
            when = None
            if field == 'entryDate':
                if entry:
                    try:
                        when = datetime.fromisoformat(entry.header.strip())
                    except ValueError:
                        pass
            else:
                when = getattr(document, field + '_at', None)
            try:
                value = when.replace(tzinfo=when.tzinfo or timezone.utc).timestamp() if when else None
            except (ValueError, OverflowError, OSError):
                value = None
        values.append(value)
    return (*values, document.relative_path, entry.anchor if entry else '')


def compare_keys(left, right, ordering):
    for index, (_, direction) in enumerate(ordering):
        a, b = left[index], right[index]
        if a is None or b is None:
            if a is not b:
                return 1 if a is None else -1  # Missing values always last.
            continue
        if a != b:
            return ((a > b) - (a < b)) * (-1 if direction == 'DESC' else 1)
    return (tuple(left[-2:]) > tuple(right[-2:])) - (tuple(left[-2:]) < tuple(right[-2:]))


def sorted_pairs(pairs, order_by):
    ordering = parse_order(order_by)
    keyed = [(entry_key(doc, entry, ordering), doc, entry) for doc, entry in pairs]
    keyed.sort(key=cmp_to_key(lambda a, b: compare_keys(a[0], b[0], ordering)))
    return keyed


def sorted_documents(documents, order_by):
    ordering = parse_order(order_by)
    result = []
    for document in documents:
        entries = sorted_pairs(((document, entry) for entry in document.entries), order_by)
        ordered = replace(document, entries=tuple(row[2] for row in entries))
        result.append((entries[0][0] if entries else entry_key(document, None, ordering), ordered))
    result.sort(key=cmp_to_key(lambda a, b: compare_keys(a[0], b[0], ordering)))
    return [row[1] for row in result]
