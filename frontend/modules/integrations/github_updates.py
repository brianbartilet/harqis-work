"""Published PRs become provenance-linked memories and ordinary review cards."""
import json
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import HTTPException
from config import get_settings
from modules.integrations import service, store
from modules.integrations.providers import repository, branch, segment
from modules.integrations.github_updates_store import Inbox

SOURCE = 'github-updates'
TAGS = ('git', 'github', 'review', 'pull-request')


def snapshot(repo, raw):
    repo = repository(repo)
    number = int(raw['number'])
    if number < 1 or not raw.get('id'):
        raise ValueError('Invalid PR identity.')
    head, base = raw['head'], raw['base']
    return dict(identity=str(raw['id']), repository=repo, number=number,
                url=f'https://github.com/{repo}/pull/{number}', title=str(raw['title'])[:500],
                body=str(raw.get('body') or '')[:30000], created_at=raw['created_at'],
                updated_at=raw['updated_at'], draft=bool(raw.get('draft')),
                state='merged' if raw.get('merged_at') or raw.get('merged') else raw['state'],
                branch=branch(head['ref']), base=branch(base['ref']),
                head_repository=repository(head['repo']['full_name']) if head.get('repo') else '',
                author=str((raw.get('user') or {}).get('login') or 'unknown'))


def peon_workspace():
    from modules.hfl_corpus.workspace_views import connection, schema, WorkspaceState
    with connection() as db:
        schema(db)
        db.execute('BEGIN IMMEDIATE')
        rows = db.execute("SELECT * FROM corpus_workspace_views WHERE lower(trim(name))='peon'").fetchall()
        if len(rows) != 1:
            raise ValueError('Exactly one peon workspace is required.')
        row = rows[0]
        state = json.loads(row['state'])
        sources = [s.strip() for s in state.get('source', '').split(',') if s.strip()]
        # Empty means all sources; narrowing that would remove existing membership.
        if sources and SOURCE not in sources:
            state['source'] = ','.join([*sources, SOURCE])
            WorkspaceState.model_validate(state)
            db.execute('UPDATE corpus_workspace_views SET state=?,revision=revision+1 WHERE id=?', (json.dumps(state), row['id']))
            prefs = db.execute('SELECT payload FROM corpus_view_preferences WHERE singleton=1').fetchone()
            if prefs:
                value = json.loads(prefs[0])
                value['revision'] += 1
                db.execute('UPDATE corpus_view_preferences SET payload=? WHERE singleton=1', (json.dumps(value),))
        return row['id']


def persist_entry(pr):
    from workflows.hfl.dto import HflEntry
    from workflows.hfl.persistence import make_envelope, persist_envelope
    from modules.hfl_corpus.corpus import resolve_corpus_root
    entry = HflEntry(
        when=datetime.fromisoformat(pr['created_at'].replace('Z', '+00:00')),
        moment=f"Pull request published: {pr['repository']} #{pr['number']} — {pr['title']}",
        what_happened=f"Author: {pr['author']}\nBranch: {pr['head_repository']}:{pr['branch']} → {pr['base']}\n\n{pr['body']}",
        why_it_stayed='Published work awaits review.', possible_use='Review the linked pull request.',
        tags=TAGS, references=(pr['url'],))
    envelope = make_envelope(entry, source=SOURCE, machine='github', dedup_key='github-pr:' + pr['identity'])
    return persist_envelope(envelope, corpus_dir=resolve_corpus_root())


def action_source(pr, receipt):
    from modules.hfl_corpus.corpus import resolve_corpus_root
    path = Path(receipt['path']).resolve().relative_to(resolve_corpus_root().resolve()).as_posix()
    return {'entry_id': receipt['entry_id'], 'path': path, 'title': pr['title'], 'date': pr['created_at'][:10]}


def reconcile(inbox, value, user, account, workspace):
    from modules.hfl_corpus.timeline import store as actions
    from workflows.hfl.timeline import write_completion
    first, pr = value['initial'], value['latest']
    identity = first['identity']
    canonical = actions()
    if value.get('receipt', {}).get('delivery') != 'persisted' or not value.get('receipt', {}).get('indexed'):
        value['receipt'] = persist_entry(first)
        inbox.save(identity, value)
        if value['receipt'].get('delivery') != 'persisted' or not value['receipt'].get('indexed'):
            raise ValueError('Entry indexing is pending; action creation deferred.')
    links = [link for link in store.links(user, 'github') if link.get('account_key') == account]
    matches = [link for link in links if link.get('pr_id') == identity or
               (str(link.get('pr_number')) == str(pr['number']) and link.get('repository', '').casefold() == pr['repository'].casefold())]
    ids = {link['action_id'] for link in matches if link.get('action_id')}
    if len(ids) > 1:
        raise ValueError('Multiple existing actions link this PR; resolve the conflict.')
    if not value.get('action_id') and ids:
        value['action_id'] = next(iter(ids))
        inbox.save(identity, value)
    if not value.get('action_id'):
        if value.get('creation') is None:
            value['creation'] = dict(request_id=str(uuid.uuid5(uuid.NAMESPACE_URL, inbox.account + ':pr:' + identity)),
                title=f"Review {first['repository']} #{first['number']}: {first['title']}"[:200],
                body=f"Review the published pull request: {first['url']}\n\n{first['body']}"[:30000],
                expected_outcome='Review the PR and record the decision or required changes.',
                workspace_ids=[workspace], agent_enabled=False)
            inbox.save(identity, value)
        item, _ = canonical.create(value['creation'], actor=SOURCE, source=action_source(first, value['receipt']))
        value['action_id'] = item['id']
        inbox.save(identity, value)
    item = canonical.get(value['action_id'])
    spaces = item.get('workspace_ids', [])
    if workspace not in spaces:
        item = canonical.update(item['id'], {'version': item['version'], 'workspace_ids': [*spaces, workspace]}, actor=SOURCE)
    link = next((link for link in matches if link.get('action_id') == item['id']), None)
    resource = link['resource'] if link else item['id'] + ':github-pr:' + identity
    link = {**(link or {}), 'action_id': item['id'], 'account_key': account, 'repository': pr['repository'],
            'head_repository': pr['head_repository'], 'branch': pr['branch'], 'base': pr['base'],
            'pr_id': identity, 'pr_number': pr['number'], 'pr_url': pr['url'], 'pr_state': pr['state'],
            'draft': pr['draft'], 'url': 'https://github.com/' + pr['head_repository'] + '/tree/' + segment(pr['branch']) if pr['head_repository'] else pr['url']}
    store.link(user, 'github', resource, link)
    target = {'merged': 'done', 'closed': 'dismissed'}.get(pr['state'])
    if target and item['status'] not in {'done', 'dismissed'}:
        item = canonical.update(item['id'], {'version': item['version'], 'status': target,
            'completion_note': f"GitHub PR {pr['state']}: {pr['url']}"}, actor=SOURCE)
    if target == 'done' and item['status'] == 'done':
        write_completion(item['id'], item['version'], store=canonical)
    value['link_receipt'] = {'resource': resource, 'state': pr['state']}
    inbox.save(identity, value, pending=False)
    return item['id']


def discover(inbox, client, pages, errors):
    cursor = inbox.cursor()
    complete = False
    for _ in range(pages):
        repos = cursor.get('repos', [])
        if not repos:
            if cursor.get('last_repo_page'):
                cursor = {}
                complete = True
                inbox.save_cursor(cursor)
                break
            page = cursor.get('repo_page', 1)
            rows = client.request('GET', '/user/repos', params={'per_page': 100, 'page': page, 'sort': 'full_name', 'direction': 'asc'})
            cursor.update(repos=[repository(row['full_name']) for row in rows], repo_page=page + 1, last_repo_page=len(rows) < 100, pr_page=1)
        else:
            repo, page = repos[0], cursor.get('pr_page', 1)
            try:
                rows = client.request('GET', '/repos/' + repo + '/pulls', params={'state': 'open', 'per_page': 100, 'page': page, 'sort': 'created', 'direction': 'asc'})
            except HTTPException as exc:
                if exc.status_code not in {403, 404} or exc.headers:
                    raise
                errors.append({'stage': 'repository', 'repository': repo, 'status': exc.status_code})
                rows = []
            for raw in rows:
                try:
                    inbox.observe(snapshot(repo, raw))
                except (ValueError, KeyError, TypeError, HTTPException):
                    errors.append({'stage': 'pr-validation', 'repository': repo})
            if len(rows) < 100:
                cursor.update(repos=repos[1:], pr_page=1)
            else:
                cursor['pr_page'] = page + 1
        inbox.save_cursor(cursor)
    return complete


def run(*, pages=10, limit=25, run_id=''):
    if get_settings().hfl_corpus_api_url:
        raise HTTPException(409, 'Run GitHub intake on the canonical owner API, not a remote-reader frontend.')
    user = get_settings().app_username
    data, client = service.connected(user, 'github')
    account = service.account_key(data)
    inbox = Inbox(user + ':' + account)
    lease = inbox.acquire()
    if not lease:
        return {'status': 'busy', 'run_id': run_id}
    errors, applied = [], []
    try:
        workspace = peon_workspace()
        complete = discover(inbox, client, pages, errors)
        for value in inbox.refresh_due(limit):
            pr = value['latest']
            try:
                raw = client.request('GET', f"/repos/{pr['repository']}/pulls/{pr['number']}")
                inbox.observe(snapshot(pr['repository'], raw))
            except HTTPException as exc:
                errors.append({'stage': 'refresh', 'pr_id': pr['identity'], 'status': exc.status_code})
                if exc.status_code in {401, 403, 429}:
                    raise
            finally:
                inbox.mark_refresh(pr['identity'])
        for value in inbox.pending(limit):
            try:
                applied.append(reconcile(inbox, value, user, account, workspace))
            except Exception as exc:
                # No provider bodies, credentials, or personal PR text in job logs.
                value['error'] = type(exc).__name__
                inbox.save(value['initial']['identity'], value)
                errors.append({'stage': 'apply', 'pr_id': value['initial']['identity'], 'error': type(exc).__name__})
        return {'status': 'partial' if errors else 'complete', 'run_id': run_id,
                'discovery_complete': complete, **inbox.counts(), 'applied': len(applied),
                'action_ids': applied, 'errors': errors, 'workspace_id': workspace}
    finally:
        inbox.release(lease)
