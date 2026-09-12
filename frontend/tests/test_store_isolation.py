from pathlib import Path

import pytest

from conftest import _require_test_profile_path, _TEST_PROFILE_PATH


def test_cleanup_rejects_a_non_test_database(tmp_path):
    live_database = tmp_path / "profile.sqlite3"
    live_database.write_bytes(b"must survive test cleanup")

    with pytest.raises(RuntimeError, match="Refusing test cleanup"):
        _require_test_profile_path(live_database)

    assert live_database.read_bytes() == b"must survive test cleanup"


def test_cleanup_accepts_only_the_isolated_profile():
    _require_test_profile_path(Path(_TEST_PROFILE_PATH))
