from workflows.hud.tasks.hud_gpt import get_desktop_logs, get_events_world_check


def test__got_helper_information():
    get_desktop_logs(cfg_id__desktop="DESKTOP", cfg_id__calendar="GOOGLE_APPS")

def test__get_events_world_check():
    get_events_world_check(countries_list=['Philippines', 'Switzerland', 'Singapore'], cfg_id__calendar="GOOGLE_APPS")