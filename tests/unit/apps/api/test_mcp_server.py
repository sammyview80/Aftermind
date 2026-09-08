import pytest

from apps.api.mcp.server import build_server


def test_build_server_raises_clear_error_without_mcp_package():
    with pytest.raises(ImportError, match="pip install mcp"):
        build_server(service=None)
