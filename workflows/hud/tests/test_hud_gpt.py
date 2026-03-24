from workflows.hud.tasks.hud_gpt import get_desktop_logs, take_screenshots_for_gpt_capture, generate_daily_desktop_summary


def test__get_desktop_logs():
    get_desktop_logs(cfg_id__desktop="DESKTOP", cfg_id__calendar="GOOGLE_APPS")

def test__take_screenshots_for_gpt_capture():
    take_screenshots_for_gpt_capture(cfg_id__desktop="DESKTOP")

def test__generate_daily_desktop_summary():
    generate_daily_desktop_summary(logs_output_path="logs/daily")