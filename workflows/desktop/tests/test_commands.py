import pytest
from workflows.desktop.tasks.commands import (git_pull_on_paths, set_desktop_hud_to_back, copy_files_targeted,
                                              run_n8n_sequence)


@pytest.mark.skip(reason="Manual integration test: mutates local repos")
def test__git_pull_on_paths():
    git_pull_on_paths()

def test__set_desktop_hud_to_back():
    set_desktop_hud_to_back()

@pytest.mark.skip(reason="Manual integration test: requires host-specific desktop sync paths")
def test__copy_files_targeted():
    copy_files_targeted("DESKTOP")

@pytest.mark.skip(reason="Manual test only")
def test__run_n8n_sequence():
    run_n8n_sequence()
