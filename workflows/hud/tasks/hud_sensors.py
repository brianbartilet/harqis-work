"""
workflows/hud/tasks/hud_sensors.py

Rainmeter HUD widget for edge sensor telemetry.

Reads the latest reading per ``device_id``/``metric`` from the
``harqis-sensor-telemetry`` Elasticsearch index (written by
``workflows/workers/tasks/ingest_sensor_reading.py``) and renders a compact
table — one row per metric, with a ⚠ marker on any reading that breached its
threshold.

Opt-in: this task is registered (so it can be triggered manually or via
``launch.py trigger-hud-tasks``) but is **not** added to the beat schedule.
To run it on a cadence, add an entry to ``workflows/hud/tasks_config.py``
mirroring the other HUD tasks.
"""
import os
from datetime import datetime, timedelta

from core.apps.sprout.app.celery import SPROUT
from core.apps.es_logging.app.elasticsearch import log_result, get_index_data

from apps.rainmeter.references.helpers.config_builder import ConfigHelperRainmeter, init_meter
from apps.rainmeter.config import CONFIG as RAINMETER_CONFIG
from apps.desktop.helpers.feed import feed

from workflows.hud.tasks.sections import sections__sensors
from workflows.workers.dto.sensor_reading import SENSOR_TELEMETRY_INDEX


def _latest_per_metric(hits: list) -> list:
    """Collapse raw ES hits to the newest reading per (device_id, metric).

    Sorted by ``date`` descending overall so the freshest devices show first.
    """
    newest: dict = {}
    for hit in hits:
        src = hit.get("_source", {}) or {}
        key = (src.get("device_id", ""), src.get("metric", ""))
        prev = newest.get(key)
        if prev is None or str(src.get("date", "")) > str(prev.get("date", "")):
            newest[key] = src
    return sorted(newest.values(), key=lambda s: str(s.get("date", "")), reverse=True)


@SPROUT.task()
@log_result()
@init_meter(RAINMETER_CONFIG, hud_item_name='SENSORS', new_sections_dict=sections__sensors,
            play_sound=False)
@feed()
def show_sensors(ini=ConfigHelperRainmeter(), **kwargs):
    """Render the latest edge-sensor readings into the SENSORS Rainmeter skin."""

    # region Query — readings from the last 24h, newest-per-metric
    since = (datetime.utcnow() - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%S")
    query = {
        "bool": {
            "must": [
                {"range": {"date": {"gte": since}}},
            ]
        }
    }
    try:
        results = get_index_data(index_name=SENSOR_TELEMETRY_INDEX, query=query) or []
    except Exception:
        # ES unreachable / index missing — render an empty widget rather than fail.
        results = []
    rows = _latest_per_metric(results)
    # endregion

    # region Links — KIBANA dev console for the sensor index
    kibana_host = os.environ.get('KIBANA_HOST', 'http://localhost:5601').rstrip('/')
    kibana_url = f'{kibana_host}/app/dev_tools#/console'
    ini['meterLink']['text'] = "KIBANA"
    ini['meterLink']['leftmouseupaction'] = '!Execute ["{0}" 3]'.format(kibana_url)
    ini['meterLink']['tooltiptext'] = kibana_url
    ini['meterLink']['W'] = '100'
    # endregion

    # region Dimensions (mirrors hud_logs.get_failed_jobs)
    width_multiplier = 2.25
    ini['meterSeperator']['W'] = '({0}*186*#Scale#)'.format(width_multiplier)
    ini['MeterDisplay']['W'] = '({0}*186*#Scale#)'.format(width_multiplier)
    ini['MeterDisplay']['H'] = '((42*#Scale#)+(#ItemLines#*22)*#Scale#)'
    ini['MeterDisplay']['X'] = '14'
    ini['MeterDisplay']['MeasureName'] = 'MeasureScrollableText'
    ini['MeterBackground']['Shape'] = ('Rectangle 0,0,({0}*190),(36+(#ItemLines#*22)),2 | Fill Color #fillColor# '
                                       '| StrokeWidth (1*#Scale#) | Stroke Color [#darkColor] '
                                       '| Scale #Scale#,#Scale#,0,0').format(width_multiplier)
    ini['MeterBackgroundTop']['Shape'] = ('Rectangle 3,3,({0}*186),25,2 | Fill Color #headerColor# | StrokeWidth 0 '
                                          '| Stroke Color [#darkColor] | Scale #Scale#,#Scale#,0,0').format(width_multiplier)
    ini['Rainmeter']['SkinWidth'] = '({0}*198*#Scale#)'.format(width_multiplier)
    ini['Rainmeter']['SkinHeight'] = '((42*#Scale#)+(#ItemLines#*22)*#Scale#)'
    ini['meterTitle']['W'] = '({0}*190*#Scale#)'.format(width_multiplier)
    ini['meterTitle']['X'] = '({0}*198*#Scale#)/2'.format(width_multiplier)
    # endregion

    # region Dump data — one row per metric, ⚠ on breach
    dump = ""
    sensor_payload = []
    for src in rows:
        device = str(src.get("device_id", ""))[:18]
        metric = str(src.get("metric", ""))[:14]
        value = src.get("value")
        unit = str(src.get("unit", ""))[:6]
        breached = bool(src.get("breached"))
        flag = "!" if breached else " "
        value_str = "{0}{1}".format(value, unit)
        dump += f"{flag} {device:<18} {metric:<14} {value_str:<10}\n"
        sensor_payload.append({
            "device_id": src.get("device_id"),
            "metric": src.get("metric"),
            "value": value,
            "unit": src.get("unit"),
            "breached": breached,
            "date": src.get("date"),
        })

    if not rows:
        dump += "No readings in the last 24h.\n"

    ini['Variables']['ItemLines'] = '{0}'.format(max(5, min(len(rows), 12)))
    dump += "\n"
    # endregion

    breached_count = sum(1 for r in sensor_payload if r["breached"])
    return {
        "text": dump,
        "summary": "{0} sensor metric(s), {1} breaching".format(len(rows), breached_count),
        "metrics": {
            "metric_count": len(rows),
            "breached_count": breached_count,
            "readings": sensor_payload,
        },
        "links": {
            "kibana": kibana_url,
        },
    }
