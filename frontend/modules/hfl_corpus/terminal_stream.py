"""Authenticated, bounded terminal streams. No process-local session ownership."""
import asyncio
import json
import logging
from urllib.parse import urlsplit
import anyio

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from starlette.concurrency import run_in_threadpool

from workflows.hfl.terminal_events import subscribe
from modules.hfl_corpus import action_agents as api

router = APIRouter()


async def receive(ws):
    raw = await ws.receive_text()
    if len(raw) > 524288:
        raise ValueError('Terminal message is too large.')
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError('Expected a terminal message.')
    return value


def bounded_rows(rows):
    result, size = [], 0
    for row in rows:
        size += len(row['data'])
        if result and size > 262144:
            break
        result.append(row)
    return result


async def serve(ws, identity, worker=False):
    # Auth is explicit: HTTP Request dependencies cannot authenticate WebSockets.
    stage = 'credentials and origin'
    try:
        if worker:
            api.bridge.worker_auth(ws)
        else:
            user = api.bridge.get_current_user(ws)
            origin = urlsplit(ws.headers.get('origin', ''))
            if not user or origin.scheme not in {'http', 'https'} or origin.netloc != ws.headers.get('host'):
                raise ValueError('Sign in from the same origin.')
        await ws.accept()
        stage = 'initial frame'
        hello = await asyncio.wait_for(receive(ws), 10)
        # Schema initialization takes locks; keep it outside the message path.
        # The object holds a path, not a shared SQLite connection.
        db = await run_in_threadpool(api.store)
        if worker:
            token = hello.get('token')
            await run_in_threadpool(db.verify, identity, token)
        else:
            stage = 'CSRF'
            if not api.bridge.verify_csrf_token(hello.get('csrf', ''), user):
                raise ValueError('Refresh the page before connecting.')
            from modules.agents.sessions import owned
            await run_in_threadpool(owned, identity, user)
        cursor = hello.get('after', 0)
        if type(cursor) is not int or cursor < 0:
            raise ValueError('Invalid replay cursor.')
        replay_through = 0
        if not worker:
            def replay_cursor():
                with db.connect() as connection:
                    return connection.execute('SELECT COALESCE(MAX(seq),0) FROM action_agent_io WHERE session=? AND direction=?', (identity, 'out')).fetchone()[0]
            replay_through = await run_in_threadpool(replay_cursor)
    except (HTTPException, ValueError, KeyError, asyncio.TimeoutError):
        logging.getLogger(__name__).info('Terminal stream rejected at %s', stage)
        await ws.close(code=1008)
        return

    lock = asyncio.Lock()
    async def send(message):
        async with lock:
            await asyncio.wait_for(ws.send_json(message), 10)

    with subscribe(identity, loop=asyncio.get_running_loop()) as changed:
        pending_output = None
        async def push():
            nonlocal cursor, pending_output
            last = None
            while True:
                changed.clear()
                item, rows = await run_in_threadpool(db.stream_snapshot, identity, 'in' if worker else 'out', cursor,
                                                    token=token if worker else None, include_io=worker or pending_output is None)
                if not worker and not api.bridge.get_current_user(ws):
                    raise ValueError('Session expired. Sign in again.')
                if worker:
                    data = {'type': 'control', 'input': bounded_rows(rows),
                            'cols': item['cols'], 'rows': item['rows'],
                            'close': bool(item['closed']) or item['state'] in {'failed', 'closed', 'expired'}}
                else:
                    output = bounded_rows(rows)
                    # One bounded batch in flight. xterm acknowledges after rendering.
                    if output:
                        pending_output = output[-1]['seq']
                    data = {'type': 'snapshot', 'session': item, 'output': output, 'replay_through': replay_through}
                if data != last:
                    await send(data)
                    last = data
                # Local mutations wake immediately; reconcile other ASGI processes
                # and legacy HTTP clients once a second against durable SQLite.
                try:
                    await asyncio.wait_for(changed.wait(), 1)
                except asyncio.TimeoutError:
                    pass

        async def commands():
            nonlocal cursor, pending_output
            while True:
                message = await receive(ws)
                kind, key = message.get('type'), message.get('key')
                try:
                    if worker:
                        if kind == 'heartbeat':
                            after = message.get('after', cursor)
                            if type(after) is not int or after < cursor:
                                raise ValueError('Invalid input cursor.')
                            cursor = after
                            result = await run_in_threadpool(api.poll_terminal, db, identity, {**message, 'token': token})
                        elif kind == 'output':
                            await run_in_threadpool(db.io, identity, 'out', key, message.get('data'), token=token)
                            result = {'ok': True}
                        elif kind == 'input_ack':
                            await run_in_threadpool(db.verify, identity, token)
                            after = message.get('after')
                            if type(after) is not int or after < cursor:
                                raise ValueError('Invalid input cursor.')
                            cursor = after
                            changed.set()
                            continue
                        else:
                            raise ValueError('Unsupported worker message.')
                    else:
                        if not api.bridge.get_current_user(ws):
                            raise ValueError('Session expired.')
                        if kind == 'output_ack':
                            if message.get('after') != pending_output:
                                raise ValueError('Invalid output acknowledgement.')
                            cursor, pending_output = pending_output, None
                            changed.set()
                            continue
                        if kind == 'input':
                            await run_in_threadpool(db.io, identity, 'in', key, message.get('data'))
                            result = {'ok': True}
                        elif kind == 'resize':
                            result = await run_in_threadpool(api.edit_terminal, db, identity, {k: message[k] for k in ('cols', 'rows')})
                        else:
                            raise ValueError('Unsupported browser message.')
                    await send({'type': 'ack', 'key': key, 'result': result})
                    changed.set()
                except (HTTPException, ValueError, KeyError) as exc:
                    await send({'type': 'error', 'key': key, 'message': str(getattr(exc, 'detail', 'Terminal request rejected.'))})

        tasks = [asyncio.create_task(push()), asyncio.create_task(commands())]
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        except (WebSocketDisconnect, RuntimeError, ValueError, KeyError, HTTPException, asyncio.TimeoutError, asyncio.CancelledError):
            pass
        finally:
            # ASGI/test clients may cancel admission while the peer disconnects.
            # Finish both child tasks without leaking a cancelled scope to them.
            with anyio.CancelScope(shield=True):
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                try:
                    await ws.close()
                except (RuntimeError, WebSocketDisconnect, asyncio.CancelledError):
                    pass


@router.websocket('/hfl-corpus/agent-bridge/sessions/{identity}/stream')
async def browser_stream(ws: WebSocket, identity: str):
    await serve(ws, identity)


@router.websocket('/api/hfl-agent/terminals/{identity}/stream')
async def worker_stream(ws: WebSocket, identity: str):
    await serve(ws, identity, worker=True)
