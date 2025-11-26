from workflows.hud.tasks.hud_gpt import get_helper_information, get_events_world_check


def test__got_helper_information():
    get_helper_information("DESKTOP_JOBS", calendar_cfg_id="GOOGLE_APPS")

def test__get_events_world_check():
    get_events_world_check(countries_list=['Philippines', 'Switzerland', 'Singapore'], calendar_cfg_id="GOOGLE_APPS")