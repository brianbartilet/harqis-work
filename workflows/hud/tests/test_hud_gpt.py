from workflows.hud.tasks.hud_gpt import get_desktop_logs, get_events_world_check, take_screenshots_for_gpt_capture


def test__get_desktop_logs():
    get_desktop_logs("DESKTOP", calendar_cfg_id="GOOGLE_APPS")

def test__get_events_world_check():
    get_events_world_check(countries_list=['Philippines', 'Switzerland', 'Singapore'], calendar_cfg_id="GOOGLE_APPS")

def test__take_screenshots_for_gpt_capture():
    take_screenshots_for_gpt_capture("DESKTOP")