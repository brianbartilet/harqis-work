"""Cached, bounded timeline suggestions using Activity Radar evidence validation."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from urllib.parse import quote, urlencode

from workflows.hfl.timeline_store import FollowUpStore, store_path

SGT = ZoneInfo("Asia/Singapore")


def period(start, end):
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    if first > last or (last - first).days > 30:
        raise ValueError("Choose a period of 1–31 days.")
    return first, last


def corpus_client():
    from apps.hfl_corpus.config import CONFIG
    from apps.hfl_corpus.references.web.api.documents import ApiServiceHflCorpusDocuments
    return ApiServiceHflCorpusDocuments(CONFIG)


def parsed_row(match, *, include_outcomes=False):
    from workflows.hfl.dto import HflEntry
    from workflows.hfl.tasks.activity_radar import _row
    raw = match["entry"]
    entry = HflEntry.from_markdown(raw["header"], raw.get("text", ""))
    if not entry.entry_id or raw.get("secret") or "secrets" in {tag.lower().lstrip('#') for tag in entry.tags}:
        return None
    if entry.source in {"activity-radar", "hfl-timeline-suggestions"} or (entry.source == "hfl-followup-outcome" and not include_outcomes):
        return None
    return _row(entry, match["relative_path"])


def collect_period(start, end, *, client=None):
    """Use the canonical privacy-filtered day API, including nested documents."""
    first, last = period(start, end)
    client = client or corpus_client()
    rows, total, seen, fetched = [], 0, set(), 0
    day = first
    while day <= last:
        offset = 0
        while True:
            payload = client._raw_request("GET", f"day-matches/{day.isoformat()}", params={"offset":offset,"limit":20,"include_secrets":"false"}, timeout=30).json()
            if offset == 0:
                total += payload["total"]
            for match in payload["matches"]:
                row = parsed_row(match)
                if row and row["entry_id"] not in seen:
                    rows.append(row); seen.add(row["entry_id"])
            fetched += len(payload["matches"])
            offset += len(payload["matches"])
            if offset >= payload["total"] or not payload["matches"] or len(rows) >= 200 or fetched >= 400:
                break
        if len(rows) >= 200 or fetched >= 400:
            break
        day += timedelta(days=1)
    return rows[:200], {"matched_entries":total,"selected_entries":min(len(rows),200),"bounded":len(rows)>=200 or fetched>=400,"range_end_reached":day.isoformat()}


def collect_related(rows, start, *, client=None):
    """Include later records through today, so old plans are checked for closure."""
    from workflows.hfl.tasks.activity_radar import infer_topics
    client = client or corpus_client()
    history, seen = [], {row["entry_id"] for row in rows}
    # Recent outcomes supplement topical recall, including a later completion
    # whose wording or tags changed. Keep this context bounded too.
    for age in range(2):
        day = (datetime.now(SGT).date() - timedelta(days=age)).isoformat()
        payload = client._raw_request('GET', 'day-matches/'+day, params={'limit':20,'include_secrets':'false'}, timeout=30).json()
        for match in payload.get('matches', []):
            row = parsed_row(match, include_outcomes=True)
            if row and row['entry_id'] not in seen:
                history.append(row); seen.add(row['entry_id'])
    metadata = {'prompt-audit', 'ai-session', 'manual-entry', 'notes', 'hfl', 'session', 'automation', 'hermes-cli', 'codex', 'codex-cli', 'claude-code', 'unknown', 'work'}
    topical = [{**row, 'tags': [tag for tag in row.get('tags', []) if tag.lstrip('#').lower() not in metadata and not tag.lstrip('#').lower().startswith(('surface-', 'agent-'))]} for row in rows]
    tags = {tag.lstrip('#').lower() for row in topical for tag in row['tags']}
    for topic in infer_topics(topical, limit=3):
        query = '#' + topic if topic in tags else topic
        payload = client._raw_request("GET", "documents", params={"q":query,"date_field":"entry","date_from":(date.fromisoformat(start)-timedelta(days=90)).isoformat(),"date_to":datetime.now(SGT).date().isoformat(),"sort":"desc","page_size":20,"compact":"true","include_secrets":"false"}, timeout=30).json()
        for document in payload.get("results", [])[:4]:
            matches = client._raw_request("GET", "matches/"+quote(document["relative_path"],safe="/"), params={"q":query,"limit":20,"include_secrets":"false"}, timeout=30).json()
            for value in matches.get("entries", []):
                # The per-document matches API returns entry dictionaries.
                entry = value.get("entry", value)
                row = parsed_row({"entry":entry,"relative_path":document["relative_path"]}, include_outcomes=True)
                if row and row["entry_id"] not in seen:
                    history.append(row); seen.add(row["entry_id"])
                if len(history) >= 60:
                    return history
    return history


def synthesize(evidence, *, start, end):
    from apps.antropic.config import get_config
    from apps.antropic.references.web.base_api_service import BaseApiServiceAnthropic
    from workflows.hfl.prompts import load_prompt
    from workflows.hfl.tasks.ingest_git import _parse_model_json
    client = BaseApiServiceAnthropic(get_config("ANTHROPIC"))
    response = client.send_message(prompt=json.dumps({"period":{"start":start,"end":end},"evidence":evidence}), system=load_prompt("timeline_suggestions"), model="claude-haiku-4-5-20251001", max_tokens=2200)
    result = _parse_model_json(response.content[0].text)
    if not isinstance(result, dict) or not isinstance(result.get("findings"),list):
        raise ValueError("Suggestion analysis returned invalid JSON.")
    return result


def review_actions(candidates, snapshot, evidence):
    from apps.antropic.config import get_config
    from apps.antropic.references.web.base_api_service import BaseApiServiceAnthropic
    from workflows.hfl.prompts import load_prompt
    from workflows.hfl.tasks.ingest_git import _parse_model_json
    from workflows.hfl.tasks.activity_radar import redact_secrets
    actions=[{key:item.get(key) for key in ('id','title','expected_outcome','status','source')} for item in snapshot['actions']]
    dismissed=[{key:item.get(key) for key in ('id','title','expected_outcome','source')} for item in snapshot['dismissed_ideas']]
    payload=redact_secrets(json.dumps({'candidates':candidates,'existing_actions':actions,'dismissed_ideas':dismissed,'evidence':evidence},ensure_ascii=False))
    if len(payload)>250000:
        raise ValueError('Duplicate-check context exceeds the bounded review limit.')
    client=BaseApiServiceAnthropic(get_config('ANTHROPIC'))
    response=client.send_message(prompt=payload,system=load_prompt('timeline_action_review'),model='claude-haiku-4-5-20251001',max_tokens=3000)
    result=_parse_model_json(response.content[0].text)
    if not isinstance(result,dict) or not isinstance(result.get('decisions'),list):
        raise ValueError('Automatic action review returned invalid JSON.')
    return result['decisions']


def create_automatic_actions(start,end,canonical,evidence,*,review=review_actions,today=None):
    today=today or datetime.now(SGT).date()
    candidates=[item for item in canonical.suggestions(start,end) if item['status']=='suggested' and item.get('confidence')=='high']
    result={'state':'complete','created':0,'duplicates':0,'deferred':0,'created_ids':[]}
    # Full comparison is required: exceeding the bound defers, never truncates old actions.
    for offset in range(0,min(len(candidates),40),8):
        batch=candidates[offset:offset+8]
        snapshot=canonical.automation_snapshot()
        if len(snapshot['actions'])+len(snapshot['dismissed_ideas'])>500:
            result.update(state='deferred',message='Too many existing records for a complete duplicate check. Review manually.')
            result['deferred']+=len(candidates)-offset
            return result
        try:
            decisions=review(batch,snapshot,evidence)
            applied=canonical.apply_auto_decisions(batch,decisions,snapshot['digest'],today)
        except Exception as exc:
            result.update(state='failed',message='Automatic creation paused; review or duplicate check could not finish. Explore can retry.',error=type(exc).__name__)
            result['deferred']+=len(candidates)-offset
            return result
        for key in ('created','duplicates','deferred'): result[key]+=applied[key]
        result['created_ids']+=applied['created_ids']
    result['deferred']+=max(0,len(candidates)-40)
    return result


def explore_period(start, end, *, run_id=None, store=None, collect=collect_period, related=collect_related, analyze=synthesize, auto_review=review_actions):
    from workflows.hfl.tasks.activity_radar import _evidence_rows, validate_findings
    canonical = store or FollowUpStore(store_path())
    first, last = period(start,end)
    if last > datetime.now(SGT).date():
        raise ValueError("Future dates have no observed activity to explore.")
    run_id = run_id or canonical.claim_period(start,end)
    if not run_id or not canonical.start_period(start,end,run_id):
        return {"state":"cached","run":canonical.run_for(start,end)}
    try:
        rows, coverage = collect(start,end)
        history = related(rows,start) if rows else []
        suggestions = []
        for offset in range(0,len(rows),40):
            batch = rows[offset:offset+40]
            compact, lookup = _evidence_rows(batch,history)
            findings = validate_findings(analyze(compact,start=start,end=end),set(lookup),lookup=lookup)
            for finding in findings[:8]:
                ids = finding["evidence"]
                primary_ids = [eid for eid in ids if eid.startswith("N")]
                if not ids or not primary_ids or finding["category"] not in {"recommendations","missed_commitments","related_history"} or finding["status"] == "resolved":
                    continue
                if not finding["resolution_check"] or not finding["recommendation"]:
                    continue
                refs = [{"entry_id":lookup[eid]["entry_id"],"path":lookup[eid]["path"],"title":lookup[eid]["moment"],"date":str(lookup[eid]["when"])[:10]} for eid in ids]
                primary = lookup[primary_ids[0]]
                suggestions.append({**finding,"evidence":refs,"source":{"entry_id":primary["entry_id"],"path":primary["path"],"title":primary["moment"],"date":str(primary["when"])[:10]},"expected_outcome":finding["recommendation"],"generated_at":datetime.now(SGT).isoformat()})
        result = {**coverage,"suggestions":len(suggestions),"related_entries":len(history),"model":"claude-haiku-4-5-20251001","analysis":"bounded evidence review; absence of evidence is not proof of non-completion"}
        if not canonical.save_suggestions(start,end,run_id,suggestions,result,state="running"):
            return {'state':'superseded'}
        compact,_ = _evidence_rows(rows,history)
        try:
            result['automatic_actions']=create_automatic_actions(start,end,canonical,compact,review=auto_review)
        except Exception as exc:
            result['automatic_actions']={'state':'failed','message':'Automatic creation did not finish. Cached ideas remain available; Explore can retry.','error':type(exc).__name__}
        canonical.finish_period(start,end,run_id,result)
        return {"state":"complete",**result}
    except Exception as exc:
        canonical.finish_period(start,end,run_id,{"error":type(exc).__name__,"message":"Analysis did not finish. Previous cached suggestions are preserved; retry exploration."},state="failed")
        raise


def write_completion(followup_id, version, *, store=None, submit=None):
    from workflows.hfl.dto import HflEntry
    from workflows.hfl.persistence import submit_hfl_entry
    import os
    canonical=store or FollowUpStore(store_path())
    revision=next(row for row in canonical.history(followup_id) if row["item"]["version"]==version)
    item=revision['item']
    agent_completion=revision['actor'].startswith('agent:')
    origin=os.environ.get("HFL_CORPUS_WEB_URL", "").rstrip("/")
    refs=[]
    if origin and item.get("source"):
        refs.append(origin+"/hfl-corpus/timeline/evidence?"+urlencode({"path":item["source"]["path"],"entry_id":item["source"]["entry_id"]}))
    source = item.get('source') or {}
    source_note = f"Original HFL: {source.get('path', '')} · {source.get('entry_id', '')}"
    label='Agent completion' if agent_completion else 'Manual completion'
    entry=HflEntry(when=datetime.fromisoformat(item["updated_at"]).astimezone(SGT),moment="Completed: "+item["title"],what_happened=f"Expected outcome: {item['expected_outcome']}\n\n{label}: {item['completion_note'] or 'Marked complete by the owner.'}\n\nTimeline action: {followup_id}; revision {version}.\n\n{source_note}",why_it_stayed="Closes the loop between the original memory, intended action, and recorded outcome.",tags=("follow-up","agent-completion" if agent_completion else "manual-completion"),references=tuple(refs),source="hfl-followup-outcome")
    if submit is None and os.getenv('HFL_TIMELINE_LOCAL_PREVIEW') == '1':
        result = {'delivery': 'preview', 'message': 'Completion retained in the local preview; no corpus entry submitted.'}
        canonical.record_receipt(followup_id, version, result)
        return result
    try:
        result=(submit or submit_hfl_entry)(entry,source="hfl-followup-outcome",dedup_key=f"timeline:{followup_id}:{version}",synthesized=False)
    except Exception as exc:
        result={"delivery":"pending","error":type(exc).__name__}
    canonical.record_receipt(followup_id,version,result)
    return result
