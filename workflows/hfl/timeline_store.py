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
FIELDS = {"title", "expected_outcome", "notes", "prompt", "review_date", "due_date", "status", "completion_note"}


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
        for key, limit in {"title": 200, "expected_outcome": 3000, "notes": 6000, "prompt": 20000, "completion_note": 3000}.items():
            value = result.get(key, "")
            if not isinstance(value, str) or len(value if key == "prompt" else value.strip()) > limit:
                raise ValueError(f"{key.replace('_', ' ')} must be text of at most {limit} characters")
            result[key] = value if key == "prompt" else value.strip()
        if not result["title"] or not result["expected_outcome"]:
            raise ValueError("A title and expected outcome are required.")
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

    def create(self, raw, *, actor, source=None, suggestion_id=None):
        unknown = set(raw) - FIELDS - {"request_id"}
        if unknown:
            raise ValueError("Unsupported follow-up fields.")
        request_id = str(uuid.UUID(str(raw.get("request_id", ""))))
        item = self.validate({key: value for key, value in raw.items() if key in FIELDS})
        if item["status"] != "open":
            raise ValueError("New follow-ups start open.")
        now = isoformat()
        item.update(id=f"followup-{uuid.uuid4().hex}", version=1, created_at=now,
                    updated_at=now, completed_at="", source=source, timezone="Asia/Singapore")
        with self.connect() as db:
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
                if any(original.get(k, "") != item.get(k, "") for k in FIELDS) or original.get("source") != source:
                    raise FollowUpConflict("This creation request was already used. Reload before creating another follow-up.")
                return existing, True
            encoded = json.dumps(item)
            db.execute("INSERT INTO followups VALUES (?, ?, ?, ?, ?, ?)",
                       (item["id"], request_id, 1, item["status"], now, encoded))
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
        return json.loads(row["payload"])

    def update(self, followup_id, raw, *, actor):
        if set(raw) - FIELDS - {"version"}:
            raise ValueError("Unsupported follow-up fields.")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT payload FROM followups WHERE id=?", (followup_id,)).fetchone()
            if not row:
                raise KeyError(followup_id)
            old = json.loads(row["payload"])
            if type(raw.get("version")) is not int or raw["version"] != old["version"]:
                raise FollowUpConflict("This follow-up changed in another window. Reload it before saving.")
            item = self.validate({**old, **{k: v for k, v in raw.items() if k in FIELDS}})
            item.update(version=old["version"] + 1, updated_at=isoformat())
            item["completed_at"] = (old["completed_at"] or item["updated_at"]) if item["status"] == "done" else ""
            encoded = json.dumps(item)
            db.execute("UPDATE followups SET version=?, status=?, updated_at=?, payload=? WHERE id=?",
                       (item["version"], item["status"], item["updated_at"], encoded, followup_id))
            db.execute("INSERT INTO followup_history VALUES (?, ?, ?, ?, ?)",
                       (followup_id, item["version"], actor, item["updated_at"], encoded))
            if item["status"] == "done" and old["status"] != "done":
                db.execute("INSERT INTO timeline_receipts(followup_id,version,state) VALUES (?,?,'pending')", (followup_id,item["version"]))
        return item

    def list(self, *, closed=False):
        with self.connect() as db:
            rows = db.execute("SELECT payload FROM followups WHERE (status IN ('done','dismissed')) = ? ORDER BY updated_at DESC", (int(closed),)).fetchall()
        return [json.loads(row["payload"]) for row in rows]

    def history(self, followup_id):
        self.get(followup_id)
        with self.connect() as db:
            rows = db.execute("SELECT payload, actor, changed_at FROM followup_history WHERE followup_id=? ORDER BY version DESC", (followup_id,)).fetchall()
        return [{"item": json.loads(row["payload"]), "actor": row["actor"], "changed_at": row["changed_at"]} for row in rows]

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

    def save_suggestions(self, start, end, run_id, suggestions, result, *, state="complete"):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            run = db.execute("SELECT run_id FROM timeline_runs WHERE period_key=?", (f"{start}:{end}",)).fetchone()
            if not run or run["run_id"] != run_id:
                return False
            db.execute("DELETE FROM timeline_suggestion_periods WHERE start_date=? AND end_date=?", (start,end))
            for item in suggestions:
                identity = json.dumps([item["category"], item["title"].strip().casefold(), sorted(ref["entry_id"] for ref in item["evidence"])])
                sid = "suggestion-" + hashlib.sha256(identity.encode()).hexdigest()[:24]
                item = {**item, "id": sid, "analysis_status": item.get("status", "uncertain")}
                db.execute("INSERT INTO timeline_suggestions(id,status,payload,updated_at) VALUES (?,'suggested',?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload,updated_at=excluded.updated_at", (sid,json.dumps(item),isoformat()))
                db.execute("INSERT OR IGNORE INTO timeline_suggestion_periods VALUES (?,?,?)", (sid,start,end))
            db.execute("UPDATE timeline_runs SET state=?,payload=?,updated_at=? WHERE period_key=? AND run_id=?", (state,json.dumps(result),isoformat(),f"{start}:{end}",run_id))
        return True

    def suggestions(self, start, end, *, include_dismissed=False):
        with self.connect() as db:
            rows = db.execute("SELECT DISTINCT s.* FROM timeline_suggestions s JOIN timeline_suggestion_periods p ON s.id=p.suggestion_id WHERE p.start_date<=? AND p.end_date>=? ORDER BY s.updated_at DESC", (end,start)).fetchall()
        return [{**json.loads(row["payload"]), "status":row["status"],"followup_id":row["followup_id"]} for row in rows if include_dismissed or row["status"] != "dismissed"]

    def suggestion(self, sid):
        with self.connect() as db:
            row = db.execute("SELECT * FROM timeline_suggestions WHERE id=?", (sid,)).fetchone()
        if not row:
            raise KeyError(sid)
        return {**json.loads(row["payload"]),"status":row["status"],"followup_id":row["followup_id"]}

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
                item=self.validate(raw)
                now=isoformat()
                item.update(id='followup-'+uuid.uuid4().hex,version=1,created_at=now,updated_at=now,completed_at='',
                            source=candidate['source'],timezone='Asia/Singapore',suggestion_id=sid,
                            creation_mode='automatic',automatic_basis=str(decision['reason'])[:3000])
                encoded=json.dumps(item)
                request_id=str(uuid.uuid5(uuid.NAMESPACE_URL,'hfl-auto:'+sid))
                db.execute('INSERT INTO followups VALUES (?,?,?,?,?,?)',(item['id'],request_id,1,'open',now,encoded))
                db.execute('INSERT INTO followup_history VALUES (?,?,?,?,?)',(item['id'],1,'timeline-automation',now,encoded))
                db.execute("UPDATE timeline_suggestions SET status='adopted',followup_id=? WHERE id=?",(item['id'],sid))
                existing[item['id']]=item;resolved[sid]=item['id']
                counts['created']+=1;counts['created_ids'].append(item['id'])
            counts['deferred']+=len(set(available)-seen)
        return counts
