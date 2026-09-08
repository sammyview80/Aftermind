from enum import Enum


class MemoryVisibility(str, Enum):
    """Ownership/sharing level of a memory — how far it reaches."""

    RUN = "run"                # single execution, episodic-only
    SESSION = "session"        # scoped to a framework session
    CONVERSATION = "conversation"
    TASK = "task"
    AGENT = "agent"
    USER = "user"
    REPOSITORY = "repository"
    PROJECT = "project"
    WORKSPACE = "workspace"
    TENANT = "tenant"
