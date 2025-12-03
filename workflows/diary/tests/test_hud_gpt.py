from workflows.hud.tasks.hud_gpt import get_activity_logs, get_events_world_check


def test__got_helper_information():
    get_activity_logs("DESKTOP", calendar_cfg_id="GOOGLE_APPS")

def test__get_events_world_check():
    get_events_world_check(countries_list=['Philippines', 'Switzerland', 'Singapore'], calendar_cfg_id="GOOGLE_APPS")