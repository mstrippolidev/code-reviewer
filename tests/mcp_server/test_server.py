import pytest
from mcp.client import Client

from mcp_server.server import mcp


@pytest.mark.asyncio
async def test_list_tools_exposes_ping() -> None:
    """Verify that the server advertises the ping tool to connecting clients."""
    async with Client(mcp) as client:
        result = await client.list_tools()

    assert "ping" in [tool.name for tool in result.tools]


@pytest.mark.asyncio
async def test_ping_prefixes_message_with_pong() -> None:
    """Verify that ping echoes the given message behind a pong prefix."""
    async with Client(mcp) as client:
        result = await client.call_tool("ping", {"message": "hi"})

    assert result.content[0].text == "pong: hi"


@pytest.mark.asyncio
async def test_ping_without_message_reports_tool_error() -> None:
    """Verify that a call missing the required argument is flagged as an error."""
    async with Client(mcp) as client:
        result = await client.call_tool("ping", {})

    assert result.is_error is True
