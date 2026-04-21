from workflows.hud.tasks.hud_utils import (show_hud_profiles, show_mouse_bindings, build_summary_mouse_bindings,
                                           show_ai_helper, show_ahk_bindings, _parse_ahk_bindings)


def test__show_hud_profiles():
    show_hud_profiles()


def test__show_mouse_bindings():
    show_mouse_bindings(cfg_id__calendar="GOOGLE_APPS")


def test__build_summary_mouse_bindings():
    build_summary_mouse_bindings(cfg_id__desktop="DESKTOP")


def test__show_ai_helper():
    show_ai_helper(cfg_id__n8n="N8N", cfg_id__eleven="ELEVEN_LABS", cfg_id__py="PYTHON_RUNNER")


def test__show_ahk_bindings():
    show_ahk_bindings(ahk_path=r'G:\My Drive\Bin.Deploy\Bin.Scripts\AHK\keypadmacro.ahk')