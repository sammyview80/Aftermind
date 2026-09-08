from apps.api.mcp import tools
from core.facade import AftermindService


def build_server(service: AftermindService):
    """Build the Aftermind MCP server, registering memory_observe/
    memory_recall/memory_checkpoint/memory_search. The `mcp` package is
    imported lazily so this module (and apps/api/mcp/tools.py) can be
    unit-tested without it installed — only actually running the server
    requires it."""
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:
        raise ImportError("The MCP server requires the 'mcp' package: pip install mcp") from exc

    server = FastMCP("aftermind")

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


if __name__ == "__main__":
    from apps.api.deps import get_service

    build_server(get_service()).run()
