from types import SimpleNamespace

from frontend.modules.hfl_corpus import document_edit
from workflows.hfl import write_lock


def test_document_edit_holds_corpus_wide_lock(tmp_path, monkeypatch):
    day = tmp_path / "2026-08-01.md"
    day.write_text("before\n", encoding="utf-8")
    events = []

    class Lock:
        def __enter__(self):
            events.append("entered")

        def __exit__(self, *_args):
            events.append("exited")

    monkeypatch.setattr(
        write_lock, "corpus_write_lock",
        lambda root: (events.append(root) or Lock()),
    )
    document = SimpleNamespace(path=day, relative_path=day.name)
    result = document_edit.update_document_text(
        document,
        "after\n",
        corpus_dir=tmp_path,
    )
    assert result == day
    assert day.read_text(encoding="utf-8") == "after\n"
    assert events == [tmp_path.resolve(), "entered", "exited"]
