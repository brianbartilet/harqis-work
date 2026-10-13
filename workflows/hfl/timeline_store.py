"""Persistent, manually managed intent; feed refreshes never own this state."""
from __future__ import annotations

import json
import sqlite3
import uuid
import os
import hashlib
from datetime import date
from datetime import datetime, timedelta, timezone
from pathlib import Path

def isoformat():
    return datetime.now(timezone.utc).isoformat()


def store_path():
    configured = os.environ.get("HFL_TIMELINE_STORE_PATH", "")
    root = Path(os.environ.get("HARQIS_DATA_ROOT") or Path(__file__).resolve().parents[2] / ".harqis-data")
    return Path(configured).expanduser().resolve() if configured else root / "runtime" / "hfl-timeline.sqlite3"


STATES = {"open", "active", "in_progress", "incomplete", "done", "dismissed"}
FIELDS = {"title", "expected_outcome", "notes", "prompt", "review_date", "due_date", "status", "completion_note", "agent_enabled", "matrix", "matrix_confidence", "matrix_reason", "description", "body", "checklists", "hide_ticked", "workspace_ids", "board_ids", "recurrence"}


def validate_matrix(payload):
    matrix = payload.get('matrix', '')
    confidence = payload.get('matrix_confidence', '')
    reason = payload.get('matrix_reason', '')
    if not isinstance(matrix, str) or matrix not in {'', 'Q1', 'Q2', 'Q3', 'Q4'}:
        raise ValueError('Matrix must be Q1, Q2, Q3, Q4 or unclassified.')
    if not isinstance(confidence, str) or confidence not in {'', 'high', 'medium', 'low'}:
        raise ValueError('Matrix confidence must be high, medium, low or unassessed.')
    if not isinstance(reason, str) or len(reason) > 3000:
        raise ValueError('Matrix reason must be text of at most 3000 characters.')
    if not matrix and (confidence or reason.strip()):
        raise ValueError('Choose a Matrix quadrant before adding confidence or a reason.')
    return {'matrix': matrix, 'matrix_confidence': confidence, 'matrix_reason': reason.strip()}


def priority_key(item):
    """Keep important work ahead of less important urgency; closed work comes last."""
    closed = {'done': 1, 'dismissed': 2}.get(item['status'], 0)
    return (closed, {'Q1': 0, 'Q2': 1, 'Q3': 2, 'Q4': 3}.get(item.get('matrix'), 4),
            min(filter(None, (item.get('due_date'), item.get('review_date'))), default='9999'),
            item.get('due_date') or '9999', item.get('created_at', ''), item['id'])


class FollowUpConflict(ValueError):
    pass


class FollowUpStore:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS followups (
                    id TEXT PRIMARY KEY,
                    request_id TEXT NOT NULL UNIQUE,
                    version INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS followup_history (
                    followup_id TEXT NOT NULL REFERENCES followups(id),
                    version INTEGER NOT NULL,
                    actor TEXT NOT NULL,
                    changed_at TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    PRIMARY KEY (followup_id, version)
                );
                CREATE TABLE IF NOT EXISTS followup_board_order (
                    id TEXT PRIMARY KEY REFERENCES followups(id), position INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS timeline_runs (
                    period_key TEXT PRIMARY KEY, start_date TEXT NOT NULL, end_date TEXT NOT NULL,
                    state TEXT NOT NULL, lease_until TEXT NOT NULL, run_id TEXT NOT NULL,
                    payload TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS timeline_suggestions (
                    id TEXT PRIMARY KEY, status TEXT NOT NULL, followup_id TEXT NOT NULL DEFAULT '',
                    payload TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS timeline_suggestion_periods (
                    suggestion_id TEXT NOT NULL REFERENCES timeline_suggestions(id),
                    start_date TEXT NOT NULL, end_date TEXT NOT NULL,
                    PRIMARY KEY(suggestion_id,start_date,end_date)
                );
                CREATE TABLE IF NOT EXISTS timeline_receipts (
                    followup_id TEXT NOT NULL, version INTEGER NOT NULL,
                    state TEXT NOT NULL, payload TEXT NOT NULL DEFAULT '{}',
                    PRIMARY KEY(followup_id,version)
                );
            """)
            from workflows.hfl.object_content import migrate_content
            migrate_content(db, 'followups')
            migrate_content(db, 'timeline_suggestions')
            # Rename current values without rewriting immutable history snapshots.
            for row in db.execute("SELECT id,payload FROM followups WHERE status='waiting'").fetchall():
                item = json.loads(row['payload'])
                item['status'] = 'in_progress'
                db.execute("UPDATE followups SET status='in_progress',payload=? WHERE id=? AND status='waiting' AND payload=?", (json.dumps(item),row['id'],row['payload']))

    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        return db

    @staticmethod
    def validate(payload):
        result = dict(payload)
        from workflows.hfl.object_content import content_fields
        result.update(content_fields(result))
        result.update(validate_matrix(result))
        from workflows.hfl.intent_reuse import workspaces, recurrence
        result['workspace_ids'] = workspaces(result)
        result['recurrence'] = recurrence(result)
        if type(result.get("agent_enabled", True)) is not bool:
            raise ValueError("agent_enabled must be a boolean.")
        if type(result.get('hide_ticked', False)) is not bool:
            raise ValueError('hide_ticked must be a boolean.')
        result.setdefault('hide_ticked', False)
        for key, limit in {"title": 200, "expected_outcome": 3000, "notes": 6000, "prompt": 20000, "completion_note": 3000}.items():
            value = result.get(key, "")
            if not isinstance(value, str) or len(value if key == "prompt" else value.strip()) > limit:
                raise ValueError(f"{key.replace('_', ' ')} must be text of at most {limit} characters")
            result[key] = value if key == "prompt" else value.strip()
        if not result["title"]:
            raise ValueError("A title is required.")
        if result.get("status", "open") not in STATES:
            raise ValueError("Unknown follow-up status.")
        result.setdefault("status", "open")
        for key in ("review_date", "due_date"):
            value = result.get(key, "")
            if not isinstance(value, str):
                raise ValueError("Dates must use YYYY-MM-DD.")
            if value:
                try:
                    if date.fromisoformat(value).isoformat() != value:
                        raise ValueError()
                except ValueError:
                    raise ValueError("Dates must use YYYY-MM-DD.") from None
            result[key] = value
        return result

    def create(self, raw, *, actor, source=None, suggestion_id=None, connection=None):
        unknown = set(raw) - FIELDS - {"request_id"}
        if unknown:
            raise ValueError("Unsupported follow-up fields.")
        request_id = str(uuid.UUID(str(raw.get("request_id", ""))))
        item = self.validate({key: value for key, value in raw.items() if key in FIELDS})
        from workflows.hfl.intent_boards import board_ids, sync
        item['board_ids'] = board_ids(raw.get('board_ids', []))
        if item["status"] != "open":
            raise ValueError("New follow-ups start In Review.")
        now = isoformat()
        item.update(id=f"item-{uuid.uuid4().hex}", version=1, created_at=now,
                    updated_at=now, completed_at="", source=source, timezone="Asia/Singapore")
        from contextlib import nullcontext
        with (nullcontext(connection) if connection is not None else self.connect()) as db:
            if connection is None:
                db.execute("BEGIN IMMEDIATE")
            if suggestion_id:
                suggestion = db.execute("SELECT * FROM timeline_suggestions WHERE id=?", (suggestion_id,)).fetchone()
                if not suggestion or suggestion['status'] == 'dismissed':
                    raise FollowUpConflict('This suggestion is no longer available.')
                if suggestion['status'] == 'adopted':
                    existing = db.execute("SELECT payload FROM followups WHERE id=?", (suggestion['followup_id'],)).fetchone()
                    return json.loads(existing['payload']), True
                item['suggestion_id'] = suggestion_id
            previous = db.execute("SELECT payload FROM followups WHERE request_id=?", (request_id,)).fetchone()
            if previous:
                existing = json.loads(previous["payload"])
                original = json.loads(db.execute("SELECT payload FROM followup_history WHERE followup_id=? AND version=1", (existing["id"],)).fetchone()["payload"])
                from workflows.hfl.object_content import content_fields
                original.update(content_fields(original))
                original.setdefault('workspace_ids', [])
                original.setdefault('board_ids', [])
                original.setdefault('recurrence', None)
                original.setdefault('hide_ticked', False)
                if any(original.get(k, True if k == "agent_enabled" else [] if k == 'checklists' else "") != item.get(k, True if k == "agent_enabled" else [] if k == 'checklists' else "") for k in FIELDS) or original.get("source") != source:
                    raise FollowUpConflict("This creation request was already used. Reload before creating another follow-up.")
                return existing, True
            item['board_ids'] = sync(db, 'action:' + item['id'], item['board_ids'])
            encoded = json.dumps(item)
            db.execute("INSERT INTO followups VALUES (?, ?, ?, ?, ?, ?)",
                       (item["id"], request_id, 1, item["status"], now, encoded))
            from workflows.hfl.intent_boards import prepend_action
            prepend_action(db, item['id'])
            db.execute("INSERT INTO followup_history VALUES (?, ?, ?, ?, ?)",
                       (item["id"], 1, actor, now, encoded))
            if suggestion_id:
                db.execute("UPDATE timeline_suggestions SET status='adopted',followup_id=? WHERE id=?", (item['id'],suggestion_id))
        return item, False

    def get(self, followup_id):
        with self.connect() as db:
            row = db.execute("SELECT payload FROM followups WHERE id=?", (followup_id,)).fetchone()
            if not row:
                raise KeyError(followup_id)
            from workflows.hfl.intent_boards import project
            return project(db, [json.loads(row['payload'])], 'action:')[0]

    def update(self, followup_id, raw, *, actor, connection=None):
        if set(raw) - FIELDS - {"version"}:
            raise ValueError("Unsupported follow-up fields.")
        from contextlib import nullcontext
        with (nullcontext(connection) if connection is not None else self.connect()) as db:
            if connection is None:
                db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT payload FROM followups WHERE id=?", (followup_id,)).fetchone()
            if not row:
                raise KeyError(followup_id)
            old = json.loads(row["payload"])
            if type(raw.get("version")) is not int or raw["version"] != old["version"]:
                raise FollowUpConflict("This follow-up changed in another window. Reload it before saving.")
            item = self.validate({**old, **{k: v for k, v in raw.items() if k in FIELDS}})
            from workflows.hfl.intent_boards import sync, memberships, board_ids
            added_to_board = bool(set(board_ids(raw.get('board_ids', []))) - set(memberships(db, 'action:' + followup_id)))
            item['board_ids'] = (sync(db, 'action:' + followup_id, raw['board_ids']) if 'board_ids' in raw
                                 else memberships(db, 'action:' + followup_id))
            if added_to_board:
                from workflows.hfl.intent_boards import prepend_action
                item['status'] = 'open'
                prepend_action(db, followup_id)
            item.update(version=old["version"] + 1, updated_at=isoformat())
            item["completed_at"] = (old["completed_at"] or item["updated_at"]) if item["status"] == "done" else ""
            encoded = json.dumps(item)
            db.execute("UPDATE followups SET version=?, status=?, updated_at=?, payload=? WHERE id=?",
                       (item["version"], item["status"], item["updated_at"], encoded, followup_id))
            db.execute("INSERT INTO followup_history VALUES (?, ?, ?, ?, ?)",
                       (followup_id, item["version"], actor, item["updated_at"], encoded))
            if item["status"] == "done" and old["status"] != "done":
                db.execute("INSERT INTO timeline_receipts(followup_id,version,state) VALUES (?,?,'pending')", (followup_id,item["version"]))
                if item.get('recurrence'):
                    from zoneinfo import ZoneInfo
                    from workflows.hfl.intent_reuse import next_occurrence, copy_lists
                    request_id = str(uuid.uuid5(uuid.NAMESPACE_URL, 'hfl:recurrence:' + followup_id))
                    if not db.execute('SELECT 1 FROM followups WHERE request_id=?', (request_id,)).fetchone():
                        today = datetime.now(ZoneInfo(item.get('timezone', 'Asia/Singapore'))).date()
                        planned = max(today, date.fromisoformat(item.get('due_date') or item['recurrence']['start']))
                        next_date = next_occurrence(item['recurrence'], planned)
                        if next_date:
                            successor = {k: v for k, v in item.items() if k in FIELDS}
                            from workflows.hfl.intent_boards import boards
                            active = {b['id'] for b in boards(db) if b.get('active', True)}
                            successor['board_ids'] = [i for i in item['board_ids'] if i in active]
                            successor.update(request_id=request_id, status='open', completion_note='', review_date='', due_date=next_date,
                                             checklists=copy_lists(item['checklists'], reset=True), agent_enabled=False)
                            self.create(successor, actor=actor, source=item.get('source'), connection=db)
        return item

    def list(self, *, closed=False):
        with self.connect() as db:
            rows = db.execute("SELECT payload FROM followups WHERE (status IN ('done','dismissed')) = ? ORDER BY updated_at DESC", (int(closed),)).fetchall()
            from workflows.hfl.intent_boards import project
            return project(db, [json.loads(row['payload']) for row in rows], 'action:')

    def history(self, followup_id):
        self.get(followup_id)
        with self.connect() as db:
            rows = db.execute("SELECT payload, actor, changed_at FROM followup_history WHERE followup_id=? ORDER BY version DESC", (followup_id,)).fetchall()
        return [{"item": json.loads(row["payload"]), "actor": row["actor"], "changed_at": row["changed_at"]} for row in rows]

    def board_order(self):
        with self.connect() as db:
            return {row['id']: row['position'] for row in db.execute('SELECT * FROM followup_board_order')}

    def reorder_board(self, state, entries):
        if state not in STATES or not isinstance(entries, list) or not entries:
            raise ValueError('Choose a status and card order.')
        if any(not isinstance(entry, dict) or set(entry) != {'id', 'version'}
               or not isinstance(entry['id'], str) or type(entry['version']) is not int for entry in entries):
            raise ValueError('Each card needs its ID and current version.')
        identities = [entry['id'] for entry in entries]
        if len(set(identities)) != len(identities):
            raise ValueError('Card IDs must be unique.')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            rows = [json.loads(row['payload']) for row in db.execute('SELECT payload FROM followups WHERE status=?', (state,))]
            available = {row['id']: row for row in rows}
            if any(entry['id'] not in available or available[entry['id']]['version'] != entry['version'] for entry in entries):
                raise FollowUpConflict('Cards changed. Reload before reordering.')
            positions = {row['id']: row['position'] for row in db.execute('SELECT * FROM followup_board_order')}
            rows.sort(key=lambda row: (positions.get(row['id'], 2147483647), priority_key(row)))
            # Reorder visible slots only; filtered-out cards retain their positions.
            selected, replacement = set(identities), iter(identities)
            ordered = [next(replacement) if row['id'] in selected else row['id'] for row in rows]
            db.executemany('INSERT OR REPLACE INTO followup_board_order VALUES (?,?)', [(identity, index) for index, identity in enumerate(ordered)])

    def claim_period(self, start, end, *, force=False):
        key = f"{start}:{end}"
        now = isoformat()
        run_id = uuid.uuid4().hex
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM timeline_runs WHERE period_key=?", (key,)).fetchone()
            if row and ((row["state"] in {"queued","running"} and row["lease_until"] > now) or (row["state"] == "complete" and not force)):
                return None
            lease = (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()
            db.execute("INSERT OR REPLACE INTO timeline_runs VALUES (?,?,?,?,?,?,?,?)", (key,start,end,"queued",lease,run_id,"{}",now))
        return run_id

    def start_period(self, start, end, run_id):
        with self.connect() as db:
            result = db.execute("UPDATE timeline_runs SET state='running',updated_at=? WHERE period_key=? AND run_id=? AND state='queued'", (isoformat(),f'{start}:{end}',run_id))
            return result.rowcount == 1

    def finish_period(self, start, end, run_id, result, *, state="complete"):
        with self.connect() as db:
            db.execute("UPDATE timeline_runs SET state=?,payload=?,updated_at=? WHERE period_key=? AND run_id=?",
                       (state,json.dumps(result),isoformat(),f"{start}:{end}",run_id))

    def run_for(self, start, end):
        with self.connect() as db:
            row = db.execute("SELECT * FROM timeline_runs WHERE period_key=?", (f"{start}:{end}",)).fetchone()
        if not row:
            return None
        result = dict(row)
        result["result"] = json.loads(result.pop("payload"))
        if result["state"] in {"queued","running"} and result["lease_until"] < isoformat():
            result["state"] = "interrupted"
        return result

    @staticmethod
    def _idea_generation_snapshot(db):
        rows = [dict(row) for row in db.execute('SELECT id,status,payload FROM timeline_suggestions ORDER BY id')]
        has_edits = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='idea_edits'").fetchone()
        edits = [dict(row) for row in db.execute('SELECT id,payload FROM idea_edits ORDER BY id')] if has_edits else []
        actions = [dict(row) for row in db.execute('SELECT id,payload FROM followups ORDER BY id')]
        digest = hashlib.sha256(json.dumps([rows, edits, actions], sort_keys=True).encode()).hexdigest()
        ideas = {row['id']: {**json.loads(row['payload']), 'id': row['id'], 'status': row['status']} for row in rows}
        for row in edits:
            previous = ideas.get(row['id'])
            ideas[row['id']] = {**(previous or {}), **json.loads(row['payload']), 'id': row['id']}
            if previous:
                ideas[row['id']]['status'] = previous['status']
        records = []
        for kind, items in [('idea', ideas.values()), ('action', [json.loads(row['payload']) for row in actions])]:
            for item in items:
                records.append({'id': kind + ':' + item['id'], 'status': item.get('status'),
                    'title': item.get('title', ''),
                    'outcome': item.get('expected_outcome') or item.get('recommendation', ''),
                    'context': (item.get('body') or item.get('description') or '')[:2000]})
        return {'records': records, 'digest': digest}

    def idea_generation_snapshot(self):
        with self.connect() as db:
            db.execute('BEGIN')
            return self._idea_generation_snapshot(db)

    def save_suggestions(self, start, end, run_id, suggestions, result, *, state="complete", expected_idea_digest=None):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            run = db.execute("SELECT run_id FROM timeline_runs WHERE period_key=?", (f"{start}:{end}",)).fetchone()
            if not run or run["run_id"] != run_id:
                return False
            if expected_idea_digest is not None and self._idea_generation_snapshot(db)['digest'] != expected_idea_digest:
                raise FollowUpConflict('Ideas or actions changed during duplicate review. Retry exploration.')
            db.execute("DELETE FROM timeline_suggestion_periods WHERE start_date=? AND end_date=?", (start,end))
            for item in suggestions:
                identity = json.dumps([item["category"], item["title"].strip().casefold(), sorted(ref["entry_id"] for ref in item["evidence"])])
                sid = "suggestion-" + hashlib.sha256(identity.encode()).hexdigest()[:24]
                previous = db.execute('SELECT payload,updated_at FROM timeline_suggestions WHERE id=?', (sid,)).fetchone()
                created_at = json.loads(previous['payload']).get('created_at', previous['updated_at']) if previous else isoformat()
                item = {**item, "id": sid, "created_at": created_at, "analysis_status": item.get("status", "uncertain")}
                from workflows.hfl.intent_boards import associate
                item['board_ids'] = associate(db, 'idea:' + sid, item.get('board_ids', []))
                db.execute("INSERT INTO timeline_suggestions(id,status,payload,updated_at) VALUES (?,'suggested',?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload,updated_at=excluded.updated_at", (sid,json.dumps(item),isoformat()))
                db.execute("INSERT OR IGNORE INTO timeline_suggestion_periods VALUES (?,?,?)", (sid,start,end))
            db.execute("UPDATE timeline_runs SET state=?,payload=?,updated_at=? WHERE period_key=? AND run_id=?", (state,json.dumps(result),isoformat(),f"{start}:{end}",run_id))
        return True

    def suggestions(self, start, end, *, include_dismissed=False):
        with self.connect() as db:
            rows = db.execute("SELECT DISTINCT s.* FROM timeline_suggestions s JOIN timeline_suggestion_periods p ON s.id=p.suggestion_id WHERE p.start_date<=? AND p.end_date>=? ORDER BY s.updated_at DESC", (end,start)).fetchall()
        from workflows.hfl.ideas_store import IdeasStore, local_day
        identities = {row['id'] for row in rows}
        ideas = IdeasStore(self).ideas()
        return [item for item in ideas if (item['id'] in identities or (item.get('origin') == 'manual' and
                any(start <= day <= end for day in {item.get('source_date', ''), (item.get('source') or {}).get('date', ''), local_day(item['created_at'])} if day)))
                and (include_dismissed or item['status'] != 'dismissed')]

    def suggestion(self, sid):
        from workflows.hfl.ideas_store import IdeasStore
        return IdeasStore(self).idea(sid)

    def mark_suggestion(self, sid, status, followup_id=""):
        if status not in {"dismissed","adopted"}:
            raise ValueError("Unsupported suggestion state.")
        with self.connect() as db:
            db.execute("UPDATE timeline_suggestions SET status=?,followup_id=? WHERE id=? AND status!='adopted'", (status,followup_id,sid))

    def receipts(self, *, pending_only=False):
        with self.connect() as db:
            rows = db.execute("SELECT * FROM timeline_receipts WHERE state NOT IN ('delivered','preview')" if pending_only else "SELECT * FROM timeline_receipts").fetchall()
        return [{**dict(row),"result":json.loads(row["payload"])} for row in rows]

    def record_receipt(self, followup_id, version, result):
        state = "preview" if result.get("delivery") == "preview" else "delivered" if result.get("delivery") in {"persisted","forwarded","delivered"} else "pending"
        with self.connect() as db:
            db.execute("UPDATE timeline_receipts SET state=?,payload=? WHERE followup_id=? AND version=?",(state,json.dumps(result),followup_id,version))


    @staticmethod
    def _automation_snapshot(db):
        actions=[json.loads(row['payload']) for row in db.execute('SELECT payload FROM followups ORDER BY id')]
        suggestions=[dict(row) for row in db.execute('SELECT id,status,followup_id,payload FROM timeline_suggestions ORDER BY id')]
        runs=[tuple(row) for row in db.execute('SELECT period_key,run_id FROM timeline_runs ORDER BY period_key')]
        digest=hashlib.sha256(json.dumps([actions,suggestions,runs],sort_keys=True).encode()).hexdigest()
        suppressed=[{**json.loads(row['payload']),'status':row['status'],'followup_id':row['followup_id']} for row in suggestions if row['status']=='dismissed']
        return {'actions':actions,'dismissed_ideas':suppressed,'digest':digest}

    def automation_snapshot(self):
        with self.connect() as db:
            db.execute('BEGIN')
            return self._automation_snapshot(db)

    def apply_auto_decisions(self, candidates, decisions, expected_digest, today):
        """Commit a reviewed batch only if the full duplicate-check snapshot is current."""
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            snapshot=self._automation_snapshot(db)
            if snapshot['digest'] != expected_digest:
                raise FollowUpConflict('Actions or ideas changed during review; automatic creation deferred.')
            existing={item['id']:item for item in snapshot['actions']}
            suppressed={item['id'] for item in snapshot['dismissed_ideas']}
            available={item['id']:item for item in candidates}
            resolved={}
            counts={'created':0,'duplicates':0,'deferred':0,'created_ids':[]}
            seen=set()
            for decision in decisions:
                sid=decision.get('suggestion_id') if isinstance(decision,dict) else None
                if sid not in available or sid in seen: continue
                seen.add(sid)
                candidate=available[sid]
                current=db.execute('SELECT status,payload FROM timeline_suggestions WHERE id=?',(sid,)).fetchone()
                if not current or current['status']!='suggested': continue
                stored=json.loads(current['payload'])
                stored['automatic_review']={key:str(decision.get(key) or '')[:3000] for key in ('decision','confidence','completion_check','reason')}
                stored['automatic_review']['reviewed_at']=isoformat()
                db.execute('UPDATE timeline_suggestions SET payload=? WHERE id=?',(json.dumps(stored),sid))
                duplicate=decision.get('existing_action_id') or resolved.get(decision.get('duplicate_suggestion_id'))
                dismissed=decision.get('duplicate_suggestion_id') in suppressed
                if decision.get('decision')=='duplicate' and (duplicate in existing or dismissed):
                    db.execute('UPDATE timeline_suggestions SET status=?,followup_id=? WHERE id=?',('dismissed' if dismissed else 'adopted','' if dismissed else duplicate,sid))
                    counts['duplicates']+=1
                    if duplicate in existing: resolved[sid]=duplicate
                    continue
                if (decision.get('decision')!='create' or decision.get('confidence')!='high'
                    or decision.get('completion_check')!='clear' or not str(decision.get('reason') or '').strip()
                    or candidate.get('confidence')!='high'):
                    counts['deferred']+=1
                    continue
                raw={'title':candidate['title'][:200],'expected_outcome':candidate['expected_outcome'][:3000],
                     'review_date':today.isoformat(),'due_date':'','status':'open'}
                raw.update(validate_matrix(candidate))
                item=self.validate(raw)
                now=isoformat()
                item.update(id='item-'+uuid.uuid4().hex,version=1,created_at=now,updated_at=now,completed_at='',
                            source=candidate['source'],timezone='Asia/Singapore',suggestion_id=sid,
                            creation_mode='automatic',automatic_basis=str(decision['reason'])[:3000])
                from workflows.hfl.intent_boards import associate, memberships
                item['board_ids'] = associate(db, 'action:' + item['id'], memberships(db, 'idea:' + sid))
                encoded=json.dumps(item)
                request_id=str(uuid.uuid5(uuid.NAMESPACE_URL,'hfl-auto:'+sid))
                db.execute('INSERT INTO followups VALUES (?,?,?,?,?,?)',(item['id'],request_id,1,'open',now,encoded))
                db.execute('INSERT INTO followup_history VALUES (?,?,?,?,?)',(item['id'],1,'timeline-automation',now,encoded))
                db.execute("UPDATE timeline_suggestions SET status='adopted',followup_id=? WHERE id=?",(item['id'],sid))
                existing[item['id']]=item;resolved[sid]=item['id']
                counts['created']+=1;counts['created_ids'].append(item['id'])
            counts['deferred']+=len(set(available)-seen)
        return counts
