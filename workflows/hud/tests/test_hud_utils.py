from workflows.hud.tasks.hud_utils import show_hud_profiles, show_mouse_bindings, build_summary_mouse_bindings


def test__show_hud_profiles():
    show_hud_profiles()


def test__show_mouse_bindings():
    show_mouse_bindings(calendar_cfg_id="GOOGLE_APPS")

def test__build_summary_mouse_bindings():
    build_summary_mouse_bindings("DESKTOP")