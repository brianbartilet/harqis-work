"""Best-effort registration of declared generated files; never fails a producer."""
import logging
import os
from celery.signals import task_success

log = logging.getLogger(__name__)


def output_paths(value, depth=0):
    if depth > 5:
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {'path', 'file_path', 'output_path', 'output_file', 'artifact_path', 'markdown_path', 'pdf_path'} and isinstance(item, str):
                yield item
            elif isinstance(item, (dict, list, tuple)):
                yield from output_paths(item, depth + 1)
    elif isinstance(value, (list, tuple)):
        for item in value[:500]:
            yield from output_paths(item, depth + 1)


@task_success.connect(weak=False)
def register_generated_outputs(sender=None, result=None, **kwargs):
    if os.environ.get('FILES_ENABLED', '').lower() not in {'1', 'true', 'yes'}:
        return
    try:
        from apps.file_index.service import register_output
        provenance = {'task': getattr(sender, 'name', ''), 'task_id': getattr(getattr(sender, 'request', None), 'id', '')}
        for path in list(dict.fromkeys(output_paths(result)))[:500]:
            register_output(path, provenance)
    except Exception as exc:
        log.warning('File output registration failed (%s); configured scans can recover the file', type(exc).__name__)
