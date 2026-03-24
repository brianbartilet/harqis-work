import pytest
from workflows.desktop.tasks.commands import (git_pull_on_paths, set_desktop_hud_to_back, copy_files_targeted,
                                              run_n8n_sequence)
from workflows.desktop.tasks.capture import (run_capture_logging, generate_daily_desktop_summary,
                                             generate_weekly_desktop_summary)


def test__git_pull_on_paths():
    git_pull_on_paths()

def test__set_desktop_hud_to_back():
    set_desktop_hud_to_back()

def test__copy_files_targeted():
    copy_files_targeted("DESKTOP")

@pytest.mark.skip(reason="Manual test only")
def test__run_n8n_sequence():
    run_n8n_sequence()

@pytest.mark.skip(reason="Manual test only")
def test__run_capture_logging():
    run_capture_logging("DESKTOP")

def test__generate_daily_desktop_summary():
    generate_daily_desktop_summary(hud_item_name="DESKTOP LOGS", logs_output_path="logs/daily")

def test__generate_weekly_desktop_summary():
    generate_weekly_desktop_summary(logs_daily_path="logs/daily", logs_output_path="logs/weekly")