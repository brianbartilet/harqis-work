"""
workflows/dumps/transport.py

Cross-platform file shipping primitives. All paths are pathlib; bytes are
piped through stdlib `subprocess` (which is binary-safe on every platform —
unlike PowerShell pipelines, see scripts/sync-to-host.ps1 for the related
saga). Uses Python's `tarfile` for archive construction so the wire format
is identical regardless of which `tar` binary lives on the host.
"""
from __future__ import annotations

import shlex
import shutil
import subprocess
import tarfile
from pathlib import Path

from .files import CollectedFile


def _archive_name(machine_name_dir: str, source_basename: str, relative: Path) -> str:
    """Build the tar archive entry path: <machine-dir>/<source-basename>/<relative>.

    Forces forward slashes (POSIX-style) — tar archives are POSIX paths
    regardless of where they were created.
    """
    parts = [machine_name_dir, source_basename, *relative.parts]
    return "/".join(parts)


# ─────────────────────────────────────────────────────────────────────────────
# Local copy (when the worker IS harqis-server)
# ─────────────────────────────────────────────────────────────────────────────

def copy_locally(
    files: list[CollectedFile],
    inbox_root: Path,
    machine_name_dir: str,
) -> int:
    """Copy files to `<inbox_root>/<machine_name_dir>/<source-basename>/<relative>`.

    Returns the count of files actually copied. Existing files at the
    destination are overwritten — this matches the "snapshot of yesterday's
    state" semantic for daily dumps.
    """
    written = 0
    for cf in files:
        dest = inbox_root / machine_name_dir / cf.source_root.name / cf.relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(cf.path, dest)
            written += 1
        except (OSError, PermissionError):
            continue
    return written


# ─────────────────────────────────────────────────────────────────────────────
# Remote ship — Python tarfile → ssh stdin
# ─────────────────────────────────────────────────────────────────────────────

def ship_via_ssh_tar(
    files: list[CollectedFile],
    ssh_target: str,
    inbox_root: str,
    machine_name_dir: str,
    *,
    ssh_port: int = 22,
) -> int:
    """Stream `files` to `<ssh_target>:<inbox_root>/<machine_name_dir>/...` via ssh+tar.

    One SSH connection per call; the remote runs `mkdir -p <root> && tar -xf -
    -C <root>` and the local Python writes a tar stream into its stdin.
    Archive paths are constructed so the destination tree matches:
        <inbox_root>/<machine_name_dir>/<source-basename>/<relative>

    Returns the count of files added to the archive. Skips silently if the
    file list is empty.
    """
    if not files:
        return 0

    inbox_quoted = shlex.quote(inbox_root)
    remote_cmd = f"mkdir -p {inbox_quoted} && tar -xf - -C {inbox_quoted}"
    ssh_cmd = ["ssh", "-p", str(ssh_port), ssh_target, remote_cmd]

    written = 0
    proc = subprocess.Popen(ssh_cmd, stdin=subprocess.PIPE)
    try:
        # Stream-mode tar: `w|` writes without seek (required for pipes).
        with tarfile.open(fileobj=proc.stdin, mode="w|") as tar:
            for cf in files:
                arcname = _archive_name(machine_name_dir, cf.source_root.name, cf.relative)
                try:
                    tar.add(str(cf.path), arcname=arcname, recursive=False)
                    written += 1
                except (OSError, PermissionError):
                    continue
    finally:
        if proc.stdin and not proc.stdin.closed:
            proc.stdin.close()
        proc.wait()
    if proc.returncode != 0:
        raise RuntimeError(
            f"ssh tar-extract failed (exit {proc.returncode}) "
            f"on {ssh_target}:{inbox_root}"
        )
    return written


# ─────────────────────────────────────────────────────────────────────────────
# Remote pull — list via ssh+find, then ssh+tar back
# ─────────────────────────────────────────────────────────────────────────────

def list_remote_recent_files(
    ssh_target: str,
    paths: list[str],
    start_iso: str | None,
    end_iso: str | None,
    *,
    ssh_port: int = 22,
) -> dict[str, list[str]]:
    """List files on a remote host with mtime in `[start_iso, end_iso)`.

    Uses POSIX `find -newermt` which Termux + GNU find both support. Returns a
    dict of {source_root: [file_path, ...]} with all paths absolute on the
    remote side. Raises on ssh failure.

    Bounds are optional and applied independently — passing both as `None`
    drops the time predicate entirely and lists EVERY file under each root
    (the "full sweep" used by the manual backfill).
    """
    out: dict[str, list[str]] = {}
    for source_root in paths:
        predicate = ""
        if start_iso is not None:
            predicate += f" -newermt {shlex.quote(start_iso)}"
        if end_iso is not None:
            predicate += f" ! -newermt {shlex.quote(end_iso)}"
        find_cmd = (
            f"find {shlex.quote(source_root)} -type f"
            f"{predicate} "
            f"-print0"
        )
        result = subprocess.run(
            ["ssh", "-p", str(ssh_port), ssh_target, find_cmd],
            capture_output=True, check=False,
        )
        # find may emit warnings to stderr (permission denied on subdirs etc.);
        # treat exit code 0 OR 1 as acceptable as long as we got output.
        if result.returncode not in (0, 1):
            raise RuntimeError(
                f"ssh find failed on {ssh_target}:{source_root} "
                f"(exit {result.returncode}): {result.stderr.decode(errors='replace')[:200]}"
            )
        files = [f.decode("utf-8", errors="replace") for f in result.stdout.split(b"\0") if f]
        out[source_root] = files
    return out


def pull_via_ssh_tar(
    ssh_target: str,
    source_root: str,
    files: list[str],
    local_inbox: Path,
    machine_name_dir: str,
    *,
    ssh_port: int = 22,
) -> int:
    """Pull `files` from `<ssh_target>:<source_root>` to local inbox.

    Local destination per-file:
        <local_inbox>/<machine_name_dir>/<basename(source_root)>/<file relative to source_root>

    Streams a remote tar into local extraction so it's a single SSH round
    trip per source root. Returns the count of files extracted.
    """
    if not files:
        return 0

    # File list passed via stdin to remote tar — null-separated to be safe.
    rel_files = []
    for f in files:
        try:
            rel = Path(f).relative_to(source_root)
        except ValueError:
            # Find returned a path outside the source_root somehow; skip.
            continue
        rel_files.append(rel.as_posix())
    if not rel_files:
        return 0
    list_payload = ("\0".join(rel_files) + "\0").encode("utf-8")

    source_quoted = shlex.quote(source_root)
    remote_cmd = (
        f"cd {source_quoted} && tar -cf - --null -T -"
    )
    ssh_cmd = ["ssh", "-p", str(ssh_port), ssh_target, remote_cmd]

    local_dest = local_inbox / machine_name_dir / Path(source_root).name
    local_dest.mkdir(parents=True, exist_ok=True)

    proc = subprocess.Popen(ssh_cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    if proc.stdin is None or proc.stdout is None:
        raise RuntimeError("subprocess pipes were not created")
    try:
        proc.stdin.write(list_payload)
        proc.stdin.close()
        with tarfile.open(fileobj=proc.stdout, mode="r|") as tar:
            extracted = 0
            for member in tar:
                tar.extract(member, path=local_dest)
                if member.isfile():
                    extracted += 1
    finally:
        proc.wait()
    if proc.returncode != 0:
        raise RuntimeError(
            f"ssh remote-tar failed (exit {proc.returncode}) on {ssh_target}:{source_root}"
        )
    return extracted
