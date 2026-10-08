"""Native Hermes terminal support for agent_bridge_runner.py --watch.

The parent holds bridge credentials. The native CLI uses a local control file to
request execution slots, while all terminal input/output stays on a real PTY.
"""
from __future__ import annotations

import codecs
import json
import logging
import os
import re
import socket
import subprocess
import threading
import time
import uuid
import zipfile
from pathlib import Path


NATIVE_HOOK = r'''
import time
from pathlib import Path
from cli import HermesCLI
control = Path(os.environ['HFL_TERMINAL_CONTROL'])
permit = control.with_suffix('.permit')
def publish(state, cli):
    data = {'state': state, 'native_id': str(getattr(cli, 'session_id', '') or '')}
    temporary = control.with_suffix('.tmp')
    temporary.write_text(json.dumps(data), encoding='utf-8')
    temporary.replace(control)
original_init, original_chat = HermesCLI.__init__, HermesCLI.chat
def initialize(self, *args, **kwargs):
    original_init(self, *args, **kwargs)
    publish('idle', self)
def chat(self, message, *args, **kwargs):
    permit.unlink(missing_ok=True)
    publish('waiting', self)
    print('\nWaiting for an execution slot…', flush=True)
    try:
        while not permit.exists():
            time.sleep(.2)
        publish('running', self)
        user_message = message
        if getattr(self, '_hfl_context_session', None) != self.session_id:
            context = json.loads(Path(os.environ['HFL_TERMINAL_CONTEXT']).read_text(encoding='utf-8'))
            message = ('Action context and initial instructions (follow-up instructions take precedence):\n'
                       + json.dumps(context, ensure_ascii=False)
                       + '\nWrite deliverable files into ' + os.environ['HFL_TERMINAL_ARTIFACTS']
                       + '\nCurrent instruction:\n' + message)
            self._hfl_context_session = self.session_id
        answer = original_chat(self, message, *args, **kwargs)
        with (Path(os.environ['HFL_TERMINAL_ARTIFACTS']) / 'conversation.md').open('a', encoding='utf-8') as transcript:
            transcript.write('\n## You\n\n' + str(user_message) + '\n\n## Hermes\n\n' + str(answer or '') + '\n')
        return answer
    finally:
        publish('idle', self)
HermesCLI.__init__, HermesCLI.chat = initialize, chat
# The action dialog already identifies the agent; omit the native welcome art.
HermesCLI.show_banner = lambda self, *args, **kwargs: None
main(toolsets=toolsets, model=selected_model, provider=selected_provider,
     max_turns=settings.get('agent_max_turns', 30),
     ignore_user_config=not trusted, ignore_rules=not trusted,
     resume=os.environ.get('HFL_TERMINAL_RESUME') or None)
'''


def git(repo, *args, binary=False):
    return subprocess.check_output(['git', '-C', str(repo), *args], text=not binary,
                                   stderr=subprocess.PIPE, timeout=120)


class Workspace:
    def __init__(self, root, identity, settings):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.repo = Path(settings['agent_repository']).expanduser().resolve() if settings.get('agent_repository') else None
        self.path = self.root / 'checkout'
        self.base = ''
        self.branch = 'actions-agent/' + identity
        if self.repo:
            if not self.repo.is_dir():
                raise ValueError('Configured repository is unavailable on this worker.')
            metadata = self.root / 'worktree.json'
            self.base = json.loads(metadata.read_text())['base'] if metadata.exists() else git(self.repo, 'rev-parse', '--verify', (settings.get('agent_base_branch') or 'HEAD') + '^{commit}').strip()
            if not self.path.exists():
                git(self.repo, 'worktree', 'add', '-b', self.branch, str(self.path), self.base)
                metadata.write_text(json.dumps({'base': self.base, 'repository': str(self.repo)}))
        else:
            self.path.mkdir(exist_ok=True)

    def preserve(self, destination):
        """Make a recoverable patch archive before any worktree removal."""
        if not self.repo or not self.path.exists():
            return None
        archive = destination / 'repository-changes.zip'
        with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as z:
            z.writestr('base.txt', self.base + '\nBranch: ' + self.branch)
            z.writestr('commits.patch', git(self.path, 'format-patch', '--stdout', '--binary', self.base + '..HEAD', binary=True))
            z.writestr('working-tree.patch', git(self.path, 'diff', '--binary', 'HEAD', binary=True))
            for name in git(self.path, 'ls-files', '--others', '--exclude-standard', '-z').split('\0'):
                if not name:
                    continue
                path = (self.path / name).resolve()
                if path.is_relative_to(self.path.resolve()) and path.is_file() and not path.is_symlink():
                    z.write(path, 'untracked/' + name)
        return archive

    def cleanup(self):
        if self.repo and self.path.exists():
            # Fixed child directory, checked before Git recursively removes it.
            if self.path.resolve().parent != self.root or self.path.is_symlink():
                raise ValueError('Refusing to remove an unexpected worktree location.')
            git(self.repo, 'worktree', 'remove', '--force', str(self.path))
            # Keep the branch: commits remain directly recoverable as well as archived.


class Pty:
    def __init__(self, command, cwd, env, cols, rows):
        self.windows = os.name == 'nt'
        if self.windows:
            from winpty import PtyProcess
            self.process = PtyProcess.spawn(subprocess.list2cmdline(command), cwd=str(cwd), env=env, dimensions=(rows, cols))
        else:
            import pty
            import fcntl
            import termios
            import struct
            master, slave = pty.openpty()
            fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', rows, cols, 0, 0))
            self.master = master
            self.process = subprocess.Popen(command, cwd=cwd, env=env, stdin=slave, stdout=slave, stderr=slave, start_new_session=True)
            os.close(slave)
        self.decoder = codecs.getincrementaldecoder('utf-8')('replace')

    def read(self):
        import select
        if self.windows:
            if not select.select([self.process.fileobj], [], [], .02)[0]:
                return ''
            try:
                return self.process.read(16384)
            except EOFError:
                return ''
        if select.select([self.master], [], [], .02)[0]:
            try:
                return self.decoder.decode(os.read(self.master, 16384))
            except OSError:
                return ''
        return ''

    def write(self, text):
        if self.windows:
            self.process.write(text)
        else:
            data = text.encode('utf-8')
            while data:
                data = data[os.write(self.master, data):]

    def resize(self, rows, cols):
        if self.windows:
            self.process.setwinsize(rows, cols)
        else:
            import fcntl, termios, struct
            fcntl.ioctl(self.master, termios.TIOCSWINSZ, struct.pack('HHHH', rows, cols, 0, 0))

    def alive(self):
        return self.process.isalive() if self.windows else self.process.poll() is None

    def close(self):
        if self.windows:
            if self.alive():
                self.process.terminate(force=True)
        else:
            import signal
            if self.alive():
                os.killpg(self.process.pid, signal.SIGTERM)
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(self.process.pid, signal.SIGKILL)
                    self.process.wait(timeout=5)
            os.close(self.master)


class TerminalWorker:
    def __init__(self, client, session, runner):
        self.client, self.session, self.runner = client, session, runner
        self.identity = session['id']
        self.prefix = 'terminals/' + self.identity
        self.token = session['token']
        self.after = 0
        self.native_id = session['native_id']
        self.state = 'starting'
        self.sent = {}

    def call(self, suffix, **payload):
        return self.client.call(self.prefix + suffix, {'token': self.token, **payload})

    def upload(self, path):
        import hashlib
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 20 * 1024 * 1024:
            raise ValueError('Deliverable must be a regular file no larger than 20 MB: ' + path.name)
        content = path.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        if self.sent.get(path.name) == digest:
            return
        response = self.client.client.post(self.prefix + '/files/' + path.name,
            headers={'X-Terminal-Lease': self.token}, content=content)
        response.raise_for_status()
        self.sent[path.name] = digest

    def download_input(self, item, inputs):
        download_heartbeat = time.monotonic()
        if not re.fullmatch(r'[a-f0-9]{32}(?:\.[a-z0-9]{1,12})?', item['filename']):
            raise ValueError('Invalid supporting filename.')
        path = inputs / item['filename']
        if path.is_symlink():
            raise ValueError('Supporting file cannot be a symlink.')
        import hashlib
        digest = hashlib.sha256()
        size = 0
        with self.client.client.stream('GET', self.prefix + '/inputs/' + item['id'], headers={'X-Terminal-Lease': self.token}) as response:
            response.raise_for_status()
            with path.open('wb') as target:
                for chunk in response.iter_bytes():
                    if time.monotonic() - download_heartbeat > 10:
                        reply = self.call('/poll', state=self.state, native_id=self.native_id, after=self.after)
                        if reply['close']:
                            raise RuntimeError('Session closed while downloading supporting files.')
                        download_heartbeat = time.monotonic()
                    size += len(chunk)
                    if size > 500 * 1024 * 1024:
                        raise ValueError('Supporting file exceeds limit.')
                    digest.update(chunk)
                    target.write(chunk)
        if size != item['size'] or digest.hexdigest() != item['digest']:
            raise ValueError('Supporting file changed during download.')
        return path.resolve()

    def deliver_input(self, event, terminal, inputs):
        if event.get('type') == 'image':
            try:
                path = self.download_input(json.loads(event['data']), inputs)
                # Literal, single-line reference: never submit the user's prompt.
                terminal.write(' ' + json.dumps(path.as_posix(), ensure_ascii=True) + ' ')
            except Exception:
                logging.exception('Could not deliver pasted image to terminal %s', self.identity)
                self.call('/output', key='image-error-' + str(event['seq']),
                          data='\r\nImage could not be loaded. It remains attached to the action; paste it again to retry.\r\n')
        else:
            terminal.write(event['data'])

    def run(self):
        command, hermes_root = self.runner.hermes_command()
        root = self.runner.spool_root() / 'terminals' / self.identity
        root.mkdir(parents=True, exist_ok=True)
        artifacts = root / 'outputs'
        artifacts.mkdir(exist_ok=True)
        control = root / 'state.json'
        control.unlink(missing_ok=True)
        settings = dict(self.session['settings'])
        settings['agent_repository'] = settings.get('agent_repository') or str(self.runner.REPO_ROOT)
        inputs = root / 'inputs'
        inputs.mkdir(exist_ok=True)
        manifest = []
        for item in self.session.get('attachments', []):
            path = self.download_input(item, inputs)
            manifest.append({'name': item['name'], 'path': str(path)})
        settings.setdefault('initial_context', {})['supporting_files'] = manifest
        workspace = Workspace(root, self.identity, settings)
        settings.setdefault('initial_context', {})['repository_policy'] = (
            'Use the isolated checkout at ' + str(workspace.path) + '. Do not edit the primary checkout. '
            'For another repository, ask the owner to configure that repository before editing it. '
            'Do not merge or push unless explicitly instructed.')
        program = command[-1].split('main(query=sys.stdin.read()')[0] + NATIVE_HOOK
        # A script file avoids Windows ConPTY command-line quoting of multiline -c.
        launcher = root / 'native_cli.py'
        launcher.write_text(program, encoding='utf-8')
        command = [command[0], str(launcher)]
        if os.name != 'nt':
            # Become the controlling terminal after setsid, without preexec_fn
            # (unsafe in this multithreaded worker).
            command = [command[0], '-c',
                       'import fcntl,termios,runpy,sys; fcntl.ioctl(0,termios.TIOCSCTTY,0); runpy.run_path(sys.argv[1],run_name="__main__")',
                       str(launcher)]
        env = dict(os.environ)
        env.pop('HFL_AGENT_BRIDGE_TOKEN', None)
        env.pop('HFL_AGENT_CAPABILITY_CHECK', None)
        # Rich and shutil must read the live PTY dimensions, not inherited shell sizes.
        env.pop('COLUMNS', None)
        env.pop('LINES', None)
        context_path = root / 'context.json'
        context_path.write_text(json.dumps(settings.get('initial_context', {})), encoding='utf-8')
        runtime_settings = {key: value for key, value in settings.items() if key != 'initial_context'}
        env.update(HFL_AGENT_HERMES_ROOT=str(hermes_root), HFL_AGENT_EXECUTION_SETTINGS=json.dumps(runtime_settings),
                   HFL_TERMINAL_CONTROL=str(control), HFL_TERMINAL_RESUME=self.native_id,
                   HFL_TERMINAL_ARTIFACTS=str(artifacts), HFL_TERMINAL_CONTEXT=str(context_path),
                   TERMINAL_CWD=str(workspace.path), TERMINAL_ENV='local', TERM='xterm-256color',
                   PYTHONUTF8='1', PYTHONIOENCODING='utf-8')
        terminal = Pty(command, workspace.path, env, self.session['cols'], self.session['rows'])
        transcript = root / 'transcript.txt'
        last_input = time.monotonic()
        last_poll = 0
        last_heartbeat = 0
        heartbeat_state = None
        action_closed = False
        previous_state = 'starting'
        turn_started = None
        ran_turn = False
        previous_closed = None
        expiry = settings.get('agent_session_expiry_minutes', 60)
        exit_state = 'closed'
        dimensions = (self.session['rows'], self.session['cols'])
        pending = ''
        pending_key = uuid.uuid4().hex
        last_file_scan = 0
        try:
            while terminal.alive():
                chunk = terminal.read()
                if chunk:
                    chunk = self.runner.redact_credentials(chunk, env)
                    with transcript.open('a', encoding='utf-8') as stream:
                        stream.write(chunk)
                    pending += chunk
                interval = .05 if pending or time.monotonic() - last_input < 3 else .25
                if time.monotonic() - last_poll < interval:
                    continue
                last_poll = time.monotonic()
                if pending:
                    self.call('/output', key=pending_key, data=pending[:65536])
                    pending = pending[65536:]
                    pending_key = uuid.uuid4().hex
                if control.exists():
                    state = json.loads(control.read_text(encoding='utf-8'))
                    self.state = state['state']
                    self.native_id = state['native_id'] or self.native_id
                if self.state != previous_state:
                    last_input = time.monotonic()
                    if self.state == 'running':
                        turn_started = time.monotonic()
                        ran_turn = True
                    if self.state == 'idle':
                        turn_started = None
                    previous_state = self.state
                # Retry collection while idle, including files written after the
                # state transition. A failed upload must not terminate the CLI.
                if self.state == 'idle' and time.monotonic() - last_file_scan >= 3:
                    last_file_scan = time.monotonic()
                    self.collect_outputs(artifacts)
                full_poll = self.state != heartbeat_state or time.monotonic() - last_heartbeat >= (.3 if self.state == 'waiting' else 2)
                reply = self.call('/poll', state=self.state, native_id=self.native_id, after=self.after, io_only=not full_poll)
                if full_poll:
                    last_heartbeat = time.monotonic()
                    heartbeat_state = self.state
                    expiry = reply['expiry_minutes']
                    action_closed = reply['action_closed']
                if reply['close']:
                    break
                if workspace.repo and action_closed and (previous_closed is False or (ran_turn and self.state == 'idle')):
                    break
                previous_closed = action_closed
                if turn_started and time.monotonic() - turn_started > settings.get('agent_timeout_seconds', 1200):
                    exit_state = 'failed'
                    break
                if self.state == 'waiting' and reply.get('granted'):
                    control.with_suffix('.permit').touch()
                if dimensions != (reply['rows'], reply['cols']):
                    dimensions = (reply['rows'], reply['cols'])
                    terminal.resize(*dimensions)
                for event in reply['input']:
                    self.deliver_input(event, terminal, inputs)
                    self.after = event['seq']
                    last_input = time.monotonic()
                if self.state == 'idle' and time.monotonic() - last_input >= expiry * 60:
                    exit_state = 'expired'
                    break
        finally:
            terminal.close()
            if pending:
                for offset in range(0, len(pending), 65536):
                    self.call('/output', key=uuid.uuid4().hex, data=pending[offset:offset+65536])
            # Upload everything before removing a worktree; failure leaves it recoverable.
            archive = workspace.preserve(artifacts)
            for path in artifacts.iterdir():
                if re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,119}', path.name):
                    self.upload(path)
            if transcript.exists():
                portable = artifacts / 'session-transcript.txt'
                portable.write_text(re.sub(r'\x1b\][^\x07]*(?:\x07|\x1b\\)|\x1b\[[0-?]*[ -/]*[@-~]', '', transcript.read_text(encoding='utf-8')), encoding='utf-8')
                self.upload(portable)
            self.call('/poll', state=exit_state, native_id=self.native_id, after=self.after)
            if archive:
                workspace.cleanup()

    def collect_outputs(self, artifacts):
        for path in artifacts.iterdir():
            if re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,119}', path.name):
                try:
                    self.upload(path)
                except Exception as exc:
                    logging.getLogger(__name__).warning('Terminal file upload will retry (%s): %s', type(exc).__name__, path.name)


def watch_terminals(runner, stop):
    """Independent PTY threads; turn capacity is enforced atomically by the server."""
    active = {}
    host = socket.gethostname()
    while not stop.is_set():
        client = runner.BridgeClient()
        try:
            active = {key: thread for key, thread in active.items() if thread.is_alive()}
            queued = client.call('terminals')['sessions']
            for session in reversed(queued):
                # Bound idle PTY overhead too, independently of execution slots.
                if len(active) >= 16:
                    break
                if session['settings'].get('agent_host') not in {'', host}:
                    continue
                try:
                    claimed = client.call('terminals/' + session['id'] + '/claim', {'host': host})
                except Exception:
                    continue
                def execute(item=claimed):
                    connection = runner.BridgeClient()
                    terminal = TerminalWorker(connection, item, runner)
                    try:
                        terminal.run()
                    except Exception as exc:
                        logging.getLogger(__name__).error('Action terminal %s stopped (%s); local session files retained.', item['id'], type(exc).__name__)
                        try:
                            terminal.call('/output', key=uuid.uuid4().hex, data='\r\nTerminal stopped (' + type(exc).__name__ + '). Check the worker; any unarchived files remain in its session workspace.\r\n')
                            terminal.call('/poll', state='failed', native_id=terminal.native_id, after=terminal.after)
                        except Exception:
                            pass
                    finally:
                        connection.client.close()
                thread = threading.Thread(target=execute, daemon=True)
                active[session['id']] = thread
                thread.start()
        except Exception as exc:
            logging.getLogger(__name__).warning('Terminal dispatcher unavailable (%s); queued sessions will retry.', type(exc).__name__)
        finally:
            client.client.close()
        stop.wait(2)
