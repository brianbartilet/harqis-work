"""Owner-scoped read acknowledgments; never accepts or completes work."""
import time
from modules.agents import service
from workflows.hfl.agent_fleet_store import FleetConflict


def read(user):
    with service.store().connect() as db:
        rows = db.execute('SELECT item_key,reviewed FROM fleet_read_receipts WHERE user=?', (user,)).fetchall()
        row = db.execute('SELECT version FROM fleet_receipt_versions WHERE user=?', (user,)).fetchone()
    return {'version':row[0] if row else 0, 'items':{r[0]:r[1] for r in rows}}


def save(user, raw):
    keys = raw.get('keys')
    if not isinstance(keys, list) or len(keys)>500 or any(not isinstance(k,str) or not 1<=len(k)<=400 for k in keys) or type(raw.get('reviewed')) is not bool or type(raw.get('version')) is not int:
        raise ValueError('Provide up to 500 read acknowledgments and a current revision.')
    with service.store().connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT version FROM fleet_receipt_versions WHERE user=?',(user,)).fetchone()
        version = row[0] if row else 0
        if version != raw['version']:
            raise FleetConflict('Read state changed elsewhere. Refresh and try again.')
        value = int(time.time()*1000) if raw['reviewed'] else 0
        db.executemany('INSERT INTO fleet_read_receipts VALUES (?,?,?) ON CONFLICT(user,item_key) DO UPDATE SET reviewed=excluded.reviewed', [(user,k,value) for k in keys])
        db.execute('INSERT INTO fleet_receipt_versions VALUES (?,?) ON CONFLICT(user) DO UPDATE SET version=excluded.version',(user,version+1))
    return read(user)
