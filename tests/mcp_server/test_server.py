import pytest
from mcp.client import Client
from mcp.types import Tool

from mcp_server.server import mcp


@pytest.mark.asyncio
async def test_list_tools_exposes_ping() -> None:
    """Verify that the server advertises the ping tool to connecting clients."""
    async with Client(mcp) as client:
        result = await client.list_tools()

    assert "ping" in [tool.name for tool in result.tools]


async def _listed_tool(name: str) -> Tool:
    async with Client(mcp) as client:
        result = await client.list_tools()
    return next(tool for tool in result.tools if tool.name == name)


@pytest.mark.asyncio
async def test_list_tools_exposes_index_repo() -> None:
    """Verify that the server advertises the index_repo tool to connecting clients."""
    tool = await _listed_tool("index_repo")

    assert tool.name == "index_repo"


@pytest.mark.asyncio
async def test_index_repo_is_annotated_as_idempotent() -> None:
    """Verify that clients are told a repeated index_repo call has no additional effect."""
    tool = await _listed_tool("index_repo")

    assert tool.annotations.idempotent_hint is True


@pytest.mark.asyncio
async def test_index_repo_is_annotated_as_non_destructive() -> None:
    """Verify that clients are told index_repo only adds and never deletes or overwrites."""
    tool = await _listed_tool("index_repo")

    assert tool.annotations.destructive_hint is False


@pytest.mark.asyncio
async def test_index_repo_is_annotated_as_not_read_only() -> None:
    """Verify that clients are told index_repo changes state, since it starts a billed indexing job."""
    tool = await _listed_tool("index_repo")

    assert tool.annotations.read_only_hint is False


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
