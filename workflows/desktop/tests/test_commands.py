from workflows.desktop.tasks.commands import git_pull_on_paths, set_desktop_hud_to_back, move_files_targeted


def test__git_pull_on_paths():
    git_pull_on_paths()

def test__set_desktop_hud_to_back():
    set_desktop_hud_to_back()

def test__move_files_targeted():
    move_files_targeted()