from workflows.desktop.tasks.commands import (git_pull_on_paths, set_desktop_hud_to_back, copy_files_targeted,
                                              run_n8n_sequence)


def test__git_pull_on_paths():
    git_pull_on_paths()

def test__set_desktop_hud_to_back():
    set_desktop_hud_to_back()

def test__copy_files_targeted():
    copy_files_targeted()

def test__run_n8n_sequence():
    run_n8n_sequence()