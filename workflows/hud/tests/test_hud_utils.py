from workflows.hud.tasks.hud_utils import generate_utils_profiles, generate_i_cue_profiles


def test__generate_utilities_hud():
    generate_utils_profiles()


def test__generate_i_cue_profiles():
    generate_i_cue_profiles("DESKTOP", calendar_cfg_id="GOOGLE_APPS")
