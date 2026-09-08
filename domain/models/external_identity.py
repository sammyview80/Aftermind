from dataclasses import dataclass


@dataclass(frozen=True)
class ExternalIdentity:
    """Maps a framework-native identity onto a stable Aftermind agent_id.

    Keeps Aftermind's core scope decoupled from any single framework
    (Hermes profiles, Claude Code agents/subagents, Codex sessions,
    LangGraph nodes, CrewAI agents, ...). Adapters own this mapping;
    MemoryScope never stores provider-specific ids directly.

    Example:
        ExternalIdentity(provider="hermes", kind="profile",
                          external_id="coder", agent_id="agent_coder_123")
        ExternalIdentity(provider="claude-code", kind="agent",
                          external_id="implementation-agent", agent_id="agent_coder_123")
    """

    provider: str        # "hermes" | "claude-code" | "codex" | "langgraph" | "crewai" | ...
    kind: str             # "profile" | "agent" | "session" | "thread" | "subagent" | ...
    external_id: str      # the id as known to that provider
    agent_id: str          # the stable Aftermind agent_id it resolves to
