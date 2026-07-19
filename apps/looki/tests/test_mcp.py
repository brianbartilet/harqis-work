import pytest
from mcp.server.fastmcp import FastMCP

import apps.looki.mcp as looki_mcp
from apps.looki.mcp import register_looki_tools
from apps.looki.references.dto.moment import DtoLookiMoment


def test_registers_expected_looki_tools():
    mcp = FastMCP("looki-test")
    register_looki_tools(mcp)

    assert set(mcp._tool_manager._tools) == {
        "looki_status",
        "list_looki_moments",
        "search_looki_moments",
        "get_looki_moment",
        "list_looki_moment_files",
    }


class _FakeAdapter:
    def __init__(self):
        self.calls = []

    def list_moments(self, **kwargs):
        self.calls.append(("list", kwargs))
        return [DtoLookiMoment(
            id="m-1",
            title="source=https://signed.example/title",
            generated_text="at 103.8198, 1.3521",
            location_label="Tanjong Pagar",
        )]

    def search_moments(self, *args, **kwargs):
        self.calls.append(("search", args, kwargs))
        return self.list_moments()

    def get_moment(self, moment_id):
        self.calls.append(("get", moment_id))
        return {"data": {
            "id": moment_id,
            "title": "[source](https://signed.example/get)",
            "description": "longitude=103.8198; latitude=1.3521",
            "location": "Tanjong Pagar",
            "vendor_secret": "must not survive",
        }}


def _tools(monkeypatch):
    adapter = _FakeAdapter()
    monkeypatch.setattr(looki_mcp, "build_adapter", lambda _config: adapter)
    mcp = FastMCP("looki-test")
    register_looki_tools(mcp)
    return adapter, {name: tool.fn for name, tool in mcp._tool_manager._tools.items()}


def test_list_search_and_get_outputs_are_normalized_and_privacy_safe(monkeypatch):
    _adapter, tools = _tools(monkeypatch)

    outputs = [
        tools["list_looki_moments"]("2026-07-19"),
        tools["search_looki_moments"]("lunch"),
        [tools["get_looki_moment"]("m-1")],
    ]

    for output in outputs:
        rendered = str(output)
        assert "signed.example" not in rendered
        assert "103.8198" not in rendered
        assert "vendor_secret" not in rendered
        assert output[0]["location_label"] == "Tanjong Pagar"


@pytest.mark.parametrize("tool_name", ["get_looki_moment", "list_looki_moment_files"])
@pytest.mark.parametrize("moment_id", [" bad", "bad\nid", "bad/id", ""])
def test_get_and_files_reject_invalid_exact_id_before_service_call(
    monkeypatch, tool_name, moment_id
):
    def must_not_build(_config):
        pytest.fail("invalid IDs must not reach the service")

    monkeypatch.setattr(looki_mcp, "build_adapter", must_not_build)
    mcp = FastMCP("looki-test")
    register_looki_tools(mcp)

    with pytest.raises(ValueError, match="Invalid Looki moment_id"):
        mcp._tool_manager._tools[tool_name].fn(moment_id)
