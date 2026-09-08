from enum import Enum


class ScopeLevel(str, Enum):
    """Standard scope level names. Not exhaustive — MemoryScope stays an
    open string-keyed map, so callers may use custom level names beyond
    this enum without any code change here."""

    TENANT = "tenant_id"
    WORKSPACE = "workspace_id"
    PROJECT = "project_id"
    REPOSITORY = "repository_id"
    USER = "user_id"
    AGENT = "agent_id"
    TASK = "task_id"
    CONVERSATION = "conversation_id"
    SESSION = "session_id"
    RUN = "run_id"
    PARENT_RUN = "parent_run_id"
