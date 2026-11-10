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


class TimelineModelError(ValueError):
    """A safe diagnostic for an unusable model response (never includes evidence)."""


def model_json(prompt, system, field):
    """Retry incomplete JSON once, with a larger, bounded output allowance."""
    from apps.antropic.config import get_config
    from apps.antropic.references.web.base_api_service import BaseApiServiceAnthropic
    from workflows.hfl.tasks.ingest_git import _parse_model_json
    client = BaseApiServiceAnthropic(get_config("ANTHROPIC"))
    for budget in (4096, 8192):
        response = client.send_message(prompt=prompt, system=system,
            model="claude-haiku-4-5-20251001", max_tokens=budget)
        if response.stop_reason == 'max_tokens':
            reason = 'The model response reached its output limit.'
            continue
        text = '\n'.join(block.text for block in response.content if block.type == 'text')
        result = _parse_model_json(text)
        if isinstance(result, dict) and isinstance(result.get(field), list):
            return result
        reason = 'The model response was not valid structured JSON.'
    raise TimelineModelError(reason + ' Both attempts failed; cached suggestions were preserved. Retry Explore.')


def synthesize(evidence, *, start, end, existing_intents=()):
    from workflows.hfl.prompts import load_prompt
    from apps.hfl_corpus.config import CONFIG
    from apps.hfl_corpus.references.web.api.ideas import ApiServiceHflCorpusIdeas
    from workflows.hfl.tasks.activity_radar import redact_secrets
    boards = ApiServiceHflCorpusIdeas(CONFIG).get_board_context()['boards']
    return model_json(redact_secrets(json.dumps({"period":{"start":start,"end":end},"evidence":evidence,"available_boards":boards,"existing_intents":existing_intents})),
                      load_prompt("timeline_suggestions"), 'findings')


def intent_batches(existing, limit=100000):
    """Partition the full comparison set without silently dropping old intents."""
    batches, batch, size = [], [], 2
    for record in existing:
        length = len(json.dumps(record, ensure_ascii=False)) + 2
        if length + 2 > limit:
            raise TimelineModelError('An existing intent exceeds the review limit; cached ideas were preserved.')
        if batch and size + length > limit:
            batches.append(batch)
            batch, size = [], 2
        batch.append(record)
        size += length
    if batch:
        batches.append(batch)
    return batches or [[]]


def review_ideas(candidates, existing):
    """Review survivors against every batch before allowing persistence."""
    original_count = len(candidates)
    if not candidates:
        return [], 0
    for batch in intent_batches(existing):
        candidates, _ = _review_ideas_batch(candidates, batch)
        if not candidates:
            break
    return candidates, original_count - len(candidates)


def _review_ideas_batch(candidates, existing):
    """Reject semantic repeats before they become reviewable cards."""
    if not candidates or (not existing and len(candidates) == 1):
        return candidates, 0
    from workflows.hfl.prompts import load_prompt
    from workflows.hfl.tasks.activity_radar import redact_secrets
    compact = [{'id': f'candidate:{index}', 'title': item['title'],
                'outcome': item.get('expected_outcome', ''),
                'observation': item.get('observation', ''),
                'resolution_check': item.get('resolution_check', '')}
               for index, item in enumerate(candidates)]
    payload = redact_secrets(json.dumps({'candidates': compact, 'existing_intents': existing}, ensure_ascii=False))
    if len(payload) > 250000:
        raise TimelineModelError('Idea duplicate-check context exceeds the review limit; cached ideas were preserved.')
    system = load_prompt('timeline_idea_review')
    for attempt in range(2):
        decisions = model_json(payload, system, 'decisions')['decisions']
        try:
            return _validate_idea_review(candidates, existing, compact, decisions)
        except TimelineModelError as exc:
            if attempt:
                raise TimelineModelError(
                    f'{exc} Both duplicate-review attempts failed.'
                ) from exc
            # Only our safe validation diagnosis is echoed, never model output.
            system = load_prompt('timeline_idea_review') + (
                '\nThe previous review failed validation: ' + str(exc)
                + '\nRe-review all candidates against the supplied IDs. Return a complete '
                'corrected decisions list. Do not invent IDs or keep a duplicate merely '
                'to avoid a validation error.'
            )


def _validate_idea_review(candidates, existing, compact, decisions):
    """Validate the entire review before returning any cards for persistence."""
    expected = {item['id'] for item in compact}
    if len(decisions) != len(expected) or any(not isinstance(d, dict) or not isinstance(d.get('id'), str) for d in decisions):
        raise TimelineModelError('Incomplete idea duplicate review; cached ideas were preserved.')
    by_id = {d['id']: d for d in decisions}
    if set(by_id) != expected:
        raise TimelineModelError('Invalid idea duplicate review; cached ideas were preserved.')
    targets = {item['id'] for item in existing}
    kept = []
    for index, candidate in enumerate(candidates):
        identity = f'candidate:{index}'
        decision = by_id[identity]
        if 'duplicate_of' not in decision:
            raise TimelineModelError('Missing idea duplicate decision; cached ideas were preserved.')
        duplicate = decision['duplicate_of']
        if duplicate is None:
            kept.append(candidate)
            targets.add(identity)
        elif not isinstance(duplicate, str) or duplicate not in targets:
            if not isinstance(duplicate, str):
                reason = 'non-string reference'
            elif duplicate == identity:
                reason = 'self reference'
            elif duplicate in expected:
                reason = ('forward reference' if int(duplicate.split(':')[1]) > index
                          else 'reference to a suppressed candidate')
            else:
                reason = 'unknown ID'
            # The candidate ID is generated locally. Never expose the rejected
            # model value: it could contain private evidence or arbitrary text.
            raise TimelineModelError(
                f'Invalid idea duplicate target for {identity}: {reason}; '
                'duplicate_of must reference an existing intent or an earlier retained '
                'candidate, not a date. Cached ideas were preserved.'
            )
    return kept, len(candidates) - len(kept)


def review_actions(candidates, snapshot, evidence):
    from workflows.hfl.prompts import load_prompt
    from workflows.hfl.tasks.activity_radar import redact_secrets
    actions=[{key:item.get(key) for key in ('id','title','expected_outcome','status','source')} for item in snapshot['actions']]
    dismissed=[{key:item.get(key) for key in ('id','title','expected_outcome','source')} for item in snapshot['dismissed_ideas']]
    payload=redact_secrets(json.dumps({'candidates':candidates,'existing_actions':actions,'dismissed_ideas':dismissed,'evidence':evidence},ensure_ascii=False))
    if len(payload)>250000:
        raise ValueError('Duplicate-check context exceeds the bounded review limit.')
    return model_json(payload, load_prompt('timeline_action_review'), 'decisions')['decisions']


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


def explore_period(start, end, *, run_id=None, store=None, collect=collect_period, related=collect_related, analyze=synthesize, auto_review=review_actions, idea_review=review_ideas):
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
        snapshot = canonical.idea_generation_snapshot()
        # Generation gets bounded context; the mandatory review below still
        # compares every surviving proposal against the entire snapshot.
        generation_intents = intent_batches(snapshot['records'])[0]
        suggestions = []
        for offset in range(0,len(rows),40):
            batch = rows[offset:offset+40]
            compact, lookup = _evidence_rows(batch,history)
            findings = validate_findings(analyze(compact,start=start,end=end,existing_intents=generation_intents),set(lookup),lookup=lookup,include_matrix=True,include_boards=True)
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
        suggestions, duplicates = idea_review(suggestions, snapshot['records'])
        result = {**coverage,"suggestions":len(suggestions),"duplicate_ideas_suppressed":duplicates,"related_entries":len(history),"model":"claude-haiku-4-5-20251001","analysis":"bounded evidence review; absence of evidence is not proof of non-completion"}
        if not canonical.save_suggestions(start,end,run_id,suggestions,result,state="running",expected_idea_digest=snapshot['digest']):
            return {'state':'superseded'}
        compact,_ = _evidence_rows(rows,history)
        try:
            result['automatic_actions']=create_automatic_actions(start,end,canonical,compact,review=auto_review)
        except Exception as exc:
            result['automatic_actions']={'state':'failed','message':'Automatic creation did not finish. Cached ideas remain available; Explore can retry.','error':type(exc).__name__}
        canonical.finish_period(start,end,run_id,result)
        return {"state":"complete",**result}
    except Exception as exc:
        message = str(exc) if isinstance(exc, TimelineModelError) else "Analysis did not finish. Previous cached suggestions are preserved; retry exploration."
        canonical.finish_period(start,end,run_id,{"error":type(exc).__name__,"message":message},state="failed")
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
