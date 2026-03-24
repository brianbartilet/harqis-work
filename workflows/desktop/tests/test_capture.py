import pytest
from workflows.desktop.tasks.capture import (run_capture_logging, generate_daily_desktop_summary,
                                             generate_weekly_desktop_summary)


@pytest.mark.skip(reason="Manual test only")
def test__run_capture_logging():
    run_capture_logging("DESKTOP")

def test__generate_daily_desktop_summary():
    generate_daily_desktop_summary(hud_item_name="DESKTOP LOGS", logs_output_path="logs/daily")

def test__generate_weekly_desktop_summary():
    generate_weekly_desktop_summary(logs_daily_path="logs/daily", logs_output_path="logs/weekly")
