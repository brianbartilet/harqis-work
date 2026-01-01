from workflows.hud.tasks.hud_calendar import show_calendar_information


def test__show_calendar_information():
    show_calendar_information(cfg_id__gsuite="GOOGLE_APPS" , cfg_id__elevenlabs="ELEVEN_LABS")