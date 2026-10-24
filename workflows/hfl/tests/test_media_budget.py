from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from workflows.hfl import media_budget


def test_daily_budget_serializes_concurrent_runs_and_resets_next_day(tmp_path, monkeypatch):
    monkeypatch.setenv('HARQIS_DESKTOP_DAILY_MAX_FILES', '7')
    class Clock:
        day = datetime(2026, 10, 24)
        @classmethod
        def now(cls):
            return cls.day
    monkeypatch.setattr(media_budget, 'datetime', Clock)
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(lambda _: media_budget.reserve_desktop_attempt(tmp_path), range(30))) == 7
    assert not media_budget.reserve_desktop_attempt(tmp_path)
    Clock.day = datetime(2026, 10, 25)
    assert media_budget.reserve_desktop_attempt(tmp_path)
