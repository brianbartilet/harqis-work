from core.apps.sprout.app.celery import SPROUT
from core.apps.es_logging.app.elasticsearch import log_result
from random import randint


# @log_result() is required for the manifesto's Review artifact — every task
# must produce something a human (or downstream tooling) can read to verify
# the run happened. Drop the decorator only if the task already produces a
# stronger review surface (e.g. @feed() pushes to the HUD feed, or @init_meter()
# writes a Rainmeter widget). See docs/MANIFESTO.md §PAER loop.
@SPROUT.task()
@log_result()
def add_random_numbers():
    """Demo task — adds two random numbers and returns the result.

    Replace the body when you adapt this template. Keep the @log_result()
    so the task always has a reviewable artifact in Elasticsearch.
    """
    return {"text": "template demo task fired", "result": randint(1, 100) + randint(1, 100)}
