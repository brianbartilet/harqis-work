from workflows.desktop.tasks.commands import (git_pull_on_paths, set_desktop_hud_to_back, copy_files_targeted,
                                              run_n8n_sequence)
from workflows.desktop.tasks.capture import run_capture_logging

def test__git_pull_on_paths():
    git_pull_on_paths()

def test__set_desktop_hud_to_back():
    set_desktop_hud_to_back()

def test__copy_files_targeted():
    copy_files_targeted("DESKTOP_JOBS")

def test__run_n8n_sequence():
    run_n8n_sequence()

def test__run_capture_logging():
    run_capture_logging("DESKTOP_JOBS")