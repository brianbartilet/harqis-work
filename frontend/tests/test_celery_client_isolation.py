from types import SimpleNamespace

import celery_client


def test_dispatch_namespaces_requested_queue(monkeypatch):
    captured = {}

    class FakeCelery:
        def send_task(self, task_path, *, kwargs, queue):
            captured.update(task_path=task_path, kwargs=kwargs, queue=queue)
            return SimpleNamespace(id="task-123")

    monkeypatch.setenv("HARQIS_INSTANCE", "alam-tech-labs")
    monkeypatch.delenv("HARQIS_QUEUE_PREFIX", raising=False)
    monkeypatch.setattr(celery_client, "_get_celery", lambda: FakeCelery())

    assert celery_client.dispatch("workflows.example", {"ok": True}, "default") == "task-123"
    assert captured["queue"] == "alam-tech-labs.default"
