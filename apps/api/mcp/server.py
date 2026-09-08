from apps.api.mcp import tools
from core.facade import AftermindService


def _import_server_class():
    """The `mcp` package renamed FastMCP -> MCPServer in its 2.x
    release (mcp.server.fastmcp -> mcp.server.mcpserver). Try both so
    this works whichever major version is installed. Imported lazily so
    this module (and apps/api/mcp/tools.py) can be unit-tested without
    `mcp` installed at all — only actually building the server requires it."""
    try:
        from mcp.server.fastmcp import FastMCP  # mcp < 2

        return FastMCP
    except ImportError:
        pass
    try:
        from mcp.server.mcpserver import MCPServer  # mcp >= 2

        return MCPServer
    except ImportError as exc:
        raise ImportError("The MCP server requires the 'mcp' package: pip install mcp") from exc


def build_server(service: AftermindService):
    """Build the Aftermind MCP server, registering memory_observe/
    memory_recall/memory_checkpoint/memory_search."""
    server_class = _import_server_class()
    server = server_class("aftermind")

    @server.tool()
    def memory_observe(
        scope: dict[str, str] | None = None, input: str = "", output: str = "", event_type: str = "agent_message"
    ) -> dict:
        """Learn from one turn of agent experience."""
        return tools.memory_observe(service, scope=scope, input=input, output=output, event_type=event_type)

    @server.tool()
    def memory_recall(scope: dict[str, str] | None = None, text: str = "", limit: int = 10) -> dict:
        """Reconstruct context (checkpoint + relevant memories) for a request."""
        return tools.memory_recall(service, scope=scope, text=text, limit=limit)

    @server.tool()
    def memory_checkpoint(
        scope: dict[str, str] | None = None,
        goal: str = "",
        current: str = "",
        completed: list[str] | None = None,
        blockers: list[str] | None = None,
        next_steps: list[str] | None = None,
    ) -> dict:
        """Explicitly record a checkpoint of where the agent's work stands."""
        return tools.memory_checkpoint(
            service, scope=scope, goal=goal, current=current, completed=completed, blockers=blockers, next_steps=next_steps
        )

    @server.tool()
    def memory_search(scope: dict[str, str] | None = None, query: str = "", limit: int = 5) -> dict:
        """Direct memory search, no checkpoint or context compression."""
        return tools.memory_search(service, scope=scope, query=query, limit=limit)

    return server


def build_asgi_app(service: AftermindService):
    """Return an ASGI app serving MCP over streamable HTTP, mountable
    into the FastAPI app at "/mcp" (see apps/api/main.py). Internally
    serves at its own root "/" so the external URL is exactly
    "http://<host>:<port>/mcp" — matching a typical MCP client config's
    `url` field — with no doubled-up "/mcp/mcp" path.
    """
    server = build_server(service)
    return server.streamable_http_app(streamable_http_path="/", stateless_http=True)


if __name__ == "__main__":
    from apps.api.deps import get_service

    build_server(get_service()).run()
