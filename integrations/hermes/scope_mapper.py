from typing import Optional

from domain.models.external_identity import ExternalIdentity
from domain.models.scope import MemoryScope

"""Maps Hermes' native identity/context onto Aftermind's MemoryScope.

Assumed Hermes context shape (adjust field names here if Hermes'
actual schema differs — this is the single seam):

    {
        "tenant_id": "...",       # optional, multi-tenant deployments
        "workspace_id": "...",    # optional
        "project_id": "...",      # optional
        "repository_id": "...",   # optional
        "profile": "coder",       # Hermes' agent profile name
        "session_id": "...",
        "task_id": "...",         # optional
        "conversation_id": "...", # optional
        "run_id": "...",          # optional
    }

`profile` is Hermes-native, not a stable cross-framework id — it's
resolved to Aftermind's logical agent_id via ExternalIdentity, so the
same agent_id can be shared with Claude Code/Codex/LangGraph adapters
(see domain/models/external_identity.py) rather than baking "hermes"
into MemoryScope itself.
"""

_SCOPE_FIELDS = ("tenant_id", "workspace_id", "project_id", "repository_id", "task_id", "conversation_id", "run_id")


def map_hermes_scope(
    hermes_context: dict, identities: Optional[dict[str, ExternalIdentity]] = None
) -> MemoryScope:
    """Build a MemoryScope from Hermes' context. `identities` maps a
    Hermes profile name -> ExternalIdentity (agent_id); an unmapped
    profile falls back to using the profile name directly as agent_id
    rather than dropping agent scope entirely."""
    levels = {field: hermes_context[field] for field in _SCOPE_FIELDS if hermes_context.get(field)}

    profile = hermes_context.get("profile")
    if profile:
        identity = (identities or {}).get(profile)
        levels["agent_id"] = identity.agent_id if identity else profile

    session_id = hermes_context.get("session_id")
    if session_id:
        levels["session_id"] = session_id

    return MemoryScope.of(**levels)
