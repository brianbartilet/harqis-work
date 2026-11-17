"""Inspect or install Codex for the HARQIS service user.

Usage: python scripts/setup_codex.py [--install] [--remote MACHINE]
Default is inspection only. --install installs only when no binary is found.
Remote targets use machines.local.toml; no login or service restart is performed.
"""
import argparse
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import urllib.request

INSTALLER_URL = 'https://chatgpt.com/codex/install.sh'


def usable(path):
    path = Path(path).expanduser()
    return path.is_file() and path.suffix.lower() not in {'.cmd', '.bat', '.ps1', '.js'} and os.access(path, os.X_OK)


def find_executable():
    """Prefer an explicit override, then managed packages, then PATH.

    An invalid explicit override is an error, never permission to install a
    second copy. The current symlinks survive managed package upgrades.
    """
    configured = os.environ.get('HARQIS_CODEX_BINARY')
    if configured:
        if not usable(configured):
            raise RuntimeError('HARQIS_CODEX_BINARY is invalid; correct the host machine variable first.')
        return str(Path(configured).expanduser())
    name = 'codex.exe' if os.name == 'nt' else 'codex'
    candidates = [Path.home() / '.codex/packages' / package / 'current/bin' / name
                  for package in ('app-server-daemon', 'standalone')]
    candidates += [Path.home() / '.local/bin' / name]
    found = shutil.which(name)
    if found:
        candidates.append(Path(found))
    return next((str(p) for p in candidates if usable(p)), None)


def install_if_missing(install=False):
    binary = find_executable()
    if binary:
        return binary
    if not install:
        raise RuntimeError('Codex not found. Run again with --install to install it for this host user.')
    if sys.platform not in {'darwin', 'linux'}:
        raise RuntimeError('Automatic installation supports macOS/Linux hosts. Install Codex on Windows using https://learn.chatgpt.com/docs/cli, then rerun this check.')
    shell = shutil.which('sh')
    if not shell:
        raise RuntimeError('The official installer requires sh on the host.')
    print('Installing missing Codex using the official OpenAI standalone installer.', flush=True)
    with urllib.request.urlopen(INSTALLER_URL, timeout=30) as response:
        payload = response.read(2 * 1024 * 1024 + 1)
    if len(payload) > 2 * 1024 * 1024 or not payload.startswith(b'#!'):
        raise RuntimeError('Unexpected installer response; nothing executed.')
    with tempfile.TemporaryDirectory(prefix='harqis-codex-setup-') as directory:
        script = Path(directory) / 'install.sh'
        script.write_bytes(payload)
        subprocess.run([shell, str(script)], check=True, timeout=300, stdin=subprocess.DEVNULL)
    binary = find_executable()
    if not binary:
        raise RuntimeError('Installer finished but Codex was not found. Configure HARQIS_CODEX_BINARY and retry.')
    return binary


def remote_setup(machine, install):
    from scripts.deploy import load_remote_target, _remote_path_expression
    target = load_remote_target(machine)
    # Send this version over stdin: setup can precede deployment of this script.
    # No local credentials or local machine environment are sent with the source.
    command = ('cd ' + _remote_path_expression(target['path']) +
               ' && .venv/bin/python -' + (' --install' if install else ''))
    return subprocess.run(['ssh', '-o', 'ConnectTimeout=10',
                           target['user'] + '@' + target['host'], command],
                          input=Path(__file__).read_bytes(), timeout=420).returncode


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--remote', help='Configured SSH target (macOS/Linux HARQIS checkout)')
    parser.add_argument('--install', action='store_true', help='Install only if Codex is missing')
    args = parser.parse_args(argv)
    root = Path.cwd() if __file__ == '<stdin>' else Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    try:
        if args.remote:
            return remote_setup(args.remote, args.install)
        from scripts.deploy import load_env_into_os, load_machine_config, machine_env_vars
        load_env_into_os()
        os.environ.update(machine_env_vars(load_machine_config(None)))
        binary = install_if_missing(args.install)
        version = subprocess.run([binary, '--version'], check=True, capture_output=True, text=True, timeout=15)
        print('Codex executable: ' + binary)
        print(version.stdout.strip())
        status = subprocess.run([binary, 'login', 'status'], capture_output=True, timeout=15)
        print('Authentication: ' + ('signed in' if status.returncode == 0 else 'sign-in required or status unavailable'))
        if status.returncode:
            print('On the host, as the HARQIS service user, run: ' + shlex.quote(binary) + ' login')
        print('Then open Integrations > Codex > Test local host > Save and enable.')
        print('Setup does not create a connector, start tasks, or restart services.')
        return 0 if status.returncode == 0 else 2
    except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
        print('Codex setup failed: ' + str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
