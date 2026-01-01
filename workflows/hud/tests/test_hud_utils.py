from workflows.hud.tasks.hud_utils import (show_hud_profiles, show_mouse_bindings, build_summary_mouse_bindings,
                                           show_ai_helper)


def test__show_hud_profiles():
    show_hud_profiles()


def test__show_mouse_bindings():
    show_mouse_bindings(cfg_id__calendar="GOOGLE_APPS")


def test__build_summary_mouse_bindings():
    build_summary_mouse_bindings(cfg_id__desktop="DESKTOP")


def test__show_ai_helper():
    show_ai_helper(cfg_id__n8n="N8N", cfg_id__eleven="ELEVEN_LABS", cfg_id__py="PYTHON_RUNNER")