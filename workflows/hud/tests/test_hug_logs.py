from workflows.hud.tasks.hud_logs import get_failed_jobs
from core.apps.es_logging.app.elasticsearch import log_result


def test__get_failed_jobs():
    get_failed_jobs()

@log_result()
def test__get_failed_raise():
    raise AttributeError