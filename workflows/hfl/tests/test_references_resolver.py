"""
Tests for workflows/hfl/references.py (resolve_references).

Deterministic/offline: file-path resolution uses tmp_path; the URL path
is exercised by monkeypatching httpx.Client with a fake.
"""

import workflows.hfl.references as refmod
from workflows.hfl.references import resolve_references


# ── Local file resolution ─────────────────────────────────────────────────────

def test__resolves_text_file(tmp_path):
    f = tmp_path / "note.md"
    f.write_text("hello research", encoding="utf-8")
    [r] = resolve_references([str(f)])
    assert r["ok"] is True
    assert r["content"] == "hello research"


def test__missing_path_unresolved():
    [r] = resolve_references([r"C:\definitely\not\here_zzz.md"])
    assert r["ok"] is False
    assert r["reason"] == "not found"


def test__binary_file_skipped(tmp_path):
    f = tmp_path / "blob.bin"
    f.write_bytes(b"PK\x03\x04\x00\x00binary")
    [r] = resolve_references([str(f)])
    assert r["ok"] is False
    assert r["reason"] == "binary file"


def test__per_ref_byte_cap(tmp_path):
    f = tmp_path / "big.txt"
    f.write_text("x" * 5000, encoding="utf-8")
    [r] = resolve_references([str(f)], max_bytes=100)
    assert r["ok"] is True
    assert len(r["content"]) <= 100


def test__total_budget_exhausted(tmp_path):
    a = tmp_path / "a.txt"; a.write_text("a" * 80, encoding="utf-8")
    b = tmp_path / "b.txt"; b.write_text("b" * 80, encoding="utf-8")
    results = resolve_references([str(a), str(b)], max_total=80)
    # first consumes the budget, second is metadata-only
    assert results[0]["ok"] is True
    assert results[1]["ok"] is False
    assert results[1]["reason"] == "budget exhausted"


def test__dedups_preserving_order(tmp_path):
    f = tmp_path / "n.txt"; f.write_text("k", encoding="utf-8")
    results = resolve_references([str(f), str(f)])
    assert len(results) == 1


# ── URL resolution (monkeypatched httpx) ──────────────────────────────────────

class _FakeResp:
    def __init__(self, content=b"page text", status=200):
        self.content = content
        self.status_code = status
        self.encoding = "utf-8"
        self.headers = {"content-type": "text/html"}

    def raise_for_status(self):
        if self.status_code >= 400:
            import httpx
            raise httpx.HTTPStatusError("err", request=None, response=self)


class _FakeClient:
    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get(self, url):
        return _FakeResp()


def test__resolves_url(monkeypatch):
    monkeypatch.setattr(refmod.httpx, "Client", _FakeClient)
    [r] = resolve_references(["https://example.com/x"])
    assert r["ok"] is True
    assert r["content"] == "page text"


def test__url_http_error(monkeypatch):
    class _ErrClient(_FakeClient):
        def get(self, url):
            return _FakeResp(content=b"", status=404)

    monkeypatch.setattr(refmod.httpx, "Client", _ErrClient)
    [r] = resolve_references(["https://example.com/missing"])
    assert r["ok"] is False
    assert "404" in r["reason"]
