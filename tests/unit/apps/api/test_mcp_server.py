import sys

import pytest

from apps.api.mcp.server import build_server


def test_build_server_raises_clear_error_without_mcp_package(monkeypatch):
    # Force the "mcp not installed" branch deterministically, regardless
    # of whether this environment actually has `mcp` installed.
    monkeypatch.setitem(sys.modules, "mcp.server.fastmcp", None)
    monkeypatch.setitem(sys.modules, "mcp.server.mcpserver", None)

    with pytest.raises(ImportError, match="pip install mcp"):
        build_server(service=None)
