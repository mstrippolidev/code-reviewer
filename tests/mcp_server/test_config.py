import pytest

from mcp_server.config import McpSettings


@pytest.fixture(autouse=True)
def clean_listen_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the developer's own MCP_HOST and MCP_PORT out of these tests."""
    monkeypatch.delenv("MCP_HOST", raising=False)
    monkeypatch.delenv("MCP_PORT", raising=False)


def test_settings_listen_on_localhost_by_default() -> None:
    """Verify that a local run is reachable only from the developer's own machine.

    A server bound to every interface on a laptop would be exposed to the network.
    """
    settings = McpSettings(_env_file=None)

    assert settings.mcp_host == "127.0.0.1"


def test_settings_listen_on_port_8001_by_default() -> None:
    """Verify that the default port stays apart from api/, which uses 8000 locally."""
    settings = McpSettings(_env_file=None)

    assert settings.mcp_port == 8001


def test_settings_read_the_listen_host_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that a pod can bind every interface by setting MCP_HOST."""
    monkeypatch.setenv("MCP_HOST", "0.0.0.0")

    settings = McpSettings(_env_file=None)

    assert settings.mcp_host == "0.0.0.0"


def test_settings_read_the_listen_port_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that the listen port can be changed without editing code."""
    monkeypatch.setenv("MCP_PORT", "9001")

    settings = McpSettings(_env_file=None)

    assert settings.mcp_port == 9001
