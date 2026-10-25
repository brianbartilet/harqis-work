"""Opt-in briefings use the existing Hermes sweep as their sole schedule owner."""
import json
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from modules.agents import service
from workflows.hfl.agent_fleet_store import FleetConflict

DEFAULT = {'cadence':'off', 'hour':9, 'weekday':0, 'timezone':'Asia/Singapore', 'version':0}


def read(user):
    with service.store().connect() as db:
        row = db.execute('SELECT * FROM fleet_briefings WHERE user=?', (user,)).fetchone()
    return {**json.loads(row['payload']), 'version':row['version']} if row else dict(DEFAULT)


def save(user, raw):
    if set(raw) != set(DEFAULT) or raw['cadence'] not in {'off','daily','weekly'}:
        raise ValueError('Choose off, daily or weekly briefings.')
    for key, maximum in [('hour',23),('weekday',6)]:
        if type(raw[key]) is not int or not 0 <= raw[key] <= maximum:
            raise ValueError('Invalid briefing ' + key + '.')
    try:
        ZoneInfo(raw['timezone'])
    except (ZoneInfoNotFoundError, TypeError, ValueError):
        raise ValueError('Choose an IANA timezone.') from None
    with service.store().connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT version FROM fleet_briefings WHERE user=?', (user,)).fetchone()
        version = row[0] if row else 0
        if type(raw['version']) is not int or raw['version'] != version:
            raise FleetConflict('Briefing schedule changed. Reload before saving.')
        db.execute('INSERT INTO fleet_briefings VALUES (?,?,?) ON CONFLICT(user) DO UPDATE SET version=excluded.version,payload=excluded.payload',
                   (user,version+1,json.dumps(raw)))
    return read(user)


def sweep(instant=None):
    from modules.agents.butler import send
    from fastapi import HTTPException
    with service.store().connect() as db:
        schedules = [(r['user'],json.loads(r['payload'])) for r in db.execute('SELECT * FROM fleet_briefings')]
    for user, config in schedules:
        local = (instant or datetime.now(ZoneInfo('UTC'))).astimezone(ZoneInfo(config['timezone']))
        if config['cadence']=='off' or local.hour < config['hour'] or (config['cadence']=='weekly' and local.weekday()!=config['weekday']):
            continue
        key = str(uuid.uuid5(uuid.NAMESPACE_URL, 'fleet-briefing:' + user + ':' + local.date().isoformat()))
        try:
            send(user, {'request_id':key, 'message':'Scheduled read-only briefing: summarize recent activity, open commitments, upcoming work and agent failures. Cite the evidence and its freshness. Do not perform writes, development, scheduling, or external communications.',
                        'context':{'path':'/agents','space':''}})
        except (HTTPException, ValueError, KeyError):
            continue  # Next sweep retries the same occurrence, never duplicates it.
