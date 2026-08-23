from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import anyio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


REPO_ROOT = Path(__file__).resolve().parents[2]
SERVER_PATH = REPO_ROOT / "mcp" / "server.py"


def test_stdio_server_keeps_non_json_output_off_stdout(caplog):
    async def exercise_server() -> None:
        params = StdioServerParameters(
            command=sys.executable,
            args=[str(SERVER_PATH)],
            env={
                **os.environ,
                "MCP_ENABLED_APPS": "trello",
                "PYTHONPATH": str(REPO_ROOT),
            },
        )
        async with stdio_client(params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                tools = await session.list_tools()

        assert any(tool.name == "get_trello_my_boards" for tool in tools.tools)

    with caplog.at_level(logging.ERROR, logger="mcp.client.stdio"):
        anyio.run(exercise_server)

    parse_errors = [
        record
        for record in caplog.records
        if record.name == "mcp.client.stdio"
        and "Failed to parse JSONRPC message from server" in record.getMessage()
    ]
    assert parse_errors == []
