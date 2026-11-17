from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import anyio
import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


REPO_ROOT = Path(__file__).resolve().parents[2]
SERVER_PATH = REPO_ROOT / "mcp" / "server.py"


@pytest.mark.parametrize('entrypoint', ['direct', 'launcher'])
def test_stdio_server_keeps_non_json_output_off_stdout(caplog, entrypoint):
    async def exercise_server() -> None:
        with anyio.fail_after(30):
            params = StdioServerParameters(
                command=sys.executable,
                args=([str(SERVER_PATH)] if entrypoint == 'direct'
                      else [str(REPO_ROOT / 'scripts' / 'launch.py'), 'mcp']),
                env={
                    **os.environ,
                    "MCP_ENABLED_APPS": "trello",
                    "MCP_STDIO_LEAK_PROBE": "1",
                    "PYTHONPATH": str(REPO_ROOT),
                },
            )
            async with stdio_client(params) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    tools = await session.list_tools()
                    probe = await session.call_tool("stdio_leak_probe")

        assert any(tool.name == "get_trello_my_boards" for tool in tools.tools)
        assert probe.isError is False
        assert probe.content[0].text == "isolated"

    with caplog.at_level(logging.ERROR, logger="mcp.client.stdio"):
        anyio.run(exercise_server)

    parse_errors = [
        record
        for record in caplog.records
        if record.name == "mcp.client.stdio"
        and "Failed to parse JSONRPC message from server" in record.getMessage()
    ]
    assert parse_errors == []


def test_stdio_server_drops_disabled_tools():
    async def list_tool_names() -> set[str]:
        with anyio.fail_after(30):
            params = StdioServerParameters(
                command=sys.executable,
                args=[str(SERVER_PATH)],
                env={
                    **os.environ,
                    "MCP_ENABLED_APPS": "trello",
                    "MCP_DISABLED_TOOLS": " GET_TRELLO_MY_* , no_such_tool ",
                    "PYTHONPATH": str(REPO_ROOT),
                },
            )
            async with stdio_client(params) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    return {tool.name for tool in (await session.list_tools()).tools}

    names = anyio.run(list_tool_names)
    assert names, "the remaining trello tools should still be registered"
    assert not any(name.startswith("get_trello_my_") for name in names)
