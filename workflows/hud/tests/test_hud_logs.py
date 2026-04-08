from workflows.hud.tasks.hud_logs import get_failed_jobs, get_schedules


def test__get_failed_jobs():
    get_failed_jobs()

def test__get_schedules():
    get_schedules(cfg_id__calendar="GOOGLE_APPS")