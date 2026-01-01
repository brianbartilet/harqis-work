from workflows.hud.tasks.hud_gpt import get_desktop_logs, get_events_world_check, take_screenshots_for_gpt_capture


def test__get_desktop_logs():
    get_desktop_logs("DESKTOP", cfg_id__calendar="GOOGLE_APPS")

def test__get_events_world_check():
    get_events_world_check(countries_list=['Philippines', 'Switzerland', 'Singapore'], cfg_id__calendar="GOOGLE_APPS")

def test__take_screenshots_for_gpt_capture():
    take_screenshots_for_gpt_capture(cfg_id__desktop="DESKTOP")