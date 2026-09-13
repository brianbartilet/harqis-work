import errno

import pytest

from scripts.agents.dumps import archive_google_drive_logs as archive


def test_nested_files_and_existing_conflicts_are_preserved(tmp_path):
    source, target = tmp_path / 'source', tmp_path / 'archive'
    (source / 'nested').mkdir(parents=True)
    target.mkdir()
    (source / 'nested/log.txt').write_bytes(b'nested content')
    (source / 'log.txt').write_bytes(b'new content')
    (target / 'log.txt').write_bytes(b'older content')
    assert archive.archive(source, target) == 0
    assert (target / 'log.txt').read_bytes() == b'older content'
    assert (target / 'nested/log.txt').read_bytes() == b'nested content'
    assert next(target.glob('log__archived_*.txt')).read_bytes() == b'new content'
    assert list(source.iterdir()) == []


def test_transient_deadlock_retries_with_bounded_delays(tmp_path, monkeypatch):
    source = tmp_path / 'log'; source.write_bytes(b'content')
    target = tmp_path / 'destination'; target.mkdir()
    original = archive.copy_verified
    calls, delays = [], []
    def flaky(*args):
        calls.append(1)
        if len(calls) < 3:
            raise OSError(errno.EDEADLK, 'Resource deadlock avoided')
        return original(*args)
    monkeypatch.setattr(archive, 'copy_verified', flaky)
    archive.archive_file(source, target / 'log', sleep=delays.append)
    assert delays == [1, 2]
    assert not source.exists()


def test_bad_copy_keeps_source_and_removes_temporary(tmp_path, monkeypatch):
    source = tmp_path / 'log'; source.write_bytes(b'content')
    target = tmp_path / 'archive'; target.mkdir()
    monkeypatch.setattr(archive, 'digest', lambda path: b'wrong')
    with pytest.raises(ValueError, match='verification'):
        archive.copy_verified(source, target / 'log')
    assert source.read_bytes() == b'content'
    assert list(target.iterdir()) == []


def test_retry_exhaustion_keeps_source(tmp_path, monkeypatch):
    source = tmp_path / 'log'; source.write_bytes(b'keep')
    calls = []
    def blocked(*args):
        calls.append(1)
        raise OSError(errno.EAGAIN, 'Unavailable')
    monkeypatch.setattr(archive, 'copy_verified', blocked)
    with pytest.raises(OSError):
        archive.archive_file(source, tmp_path / 'dest/log', sleep=lambda _: None)
    assert len(calls) == 3
    assert source.read_bytes() == b'keep'


def test_overlapping_directories_are_rejected(tmp_path):
    source = tmp_path / 'source'; source.mkdir()
    with pytest.raises(ValueError, match='overlap'):
        archive.archive(source, source / 'nested-archive')


def test_failure_continues_other_files_and_returns_nonzero(tmp_path, monkeypatch):
    source, target = tmp_path / 'source', tmp_path / 'archive'
    source.mkdir()
    (source / 'bad').write_bytes(b'keep')
    (source / 'good').write_bytes(b'archive')
    original = archive.archive_file
    def fail_one(src, dst):
        if src.name == 'bad':
            raise OSError(errno.EACCES, 'blocked')
        return original(src, dst)
    monkeypatch.setattr(archive, 'archive_file', fail_one)
    assert archive.archive(source, target) == 1
    assert (source / 'bad').read_bytes() == b'keep'
    assert (target / 'good').read_bytes() == b'archive'


def test_repeat_after_source_delete_failure_reuses_verified_archive(tmp_path, monkeypatch):
    source, target = tmp_path / 'source', tmp_path / 'archive'
    source.mkdir(); target.mkdir()
    (source / 'log').write_bytes(b'same')
    (target / 'log').write_bytes(b'same')
    assert archive.archive(source, target) == 0
    assert sorted(p.name for p in target.iterdir()) == ['.archive.lock', 'log']


def test_dry_run_does_not_create_destination(tmp_path):
    source = tmp_path / 'source'; source.mkdir()
    (source / 'log').write_bytes(b'keep')
    target = tmp_path / 'new-archive'
    assert archive.archive(source, target, dry_run=True) == 0
    assert not target.exists()
    assert (source / 'log').exists()


def test_source_change_keeps_both_source_and_existing_archive(tmp_path, monkeypatch):
    source = tmp_path / 'log'; source.write_bytes(b'old')
    target = tmp_path / 'archive'; target.mkdir()
    original = archive.digest
    def mutate(path):
        if path == source:
            source.write_bytes(b'changed')
        return original(path)
    monkeypatch.setattr(archive, 'digest', mutate)
    with pytest.raises(ValueError, match='Source changed'):
        archive.copy_verified(source, target / 'log')
    assert source.read_bytes() == b'changed'
    assert list(target.iterdir()) == []
