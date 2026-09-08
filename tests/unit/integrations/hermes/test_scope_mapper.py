from domain.models.external_identity import ExternalIdentity
from integrations.hermes.scope_mapper import map_hermes_scope


def test_maps_flat_scope_fields():
    scope = map_hermes_scope({"tenant_id": "t1", "project_id": "aftermind", "session_id": "s1"})
    assert scope.get("tenant_id") == "t1"
    assert scope.get("project_id") == "aftermind"
    assert scope.get("session_id") == "s1"


def test_unmapped_profile_used_directly_as_agent_id():
    scope = map_hermes_scope({"profile": "coder"})
    assert scope.get("agent_id") == "coder"


def test_mapped_profile_resolves_to_stable_agent_id():
    identity = ExternalIdentity(provider="hermes", kind="profile", external_id="coder", agent_id="agent_coder_123")
    scope = map_hermes_scope({"profile": "coder"}, identities={"coder": identity})
    assert scope.get("agent_id") == "agent_coder_123"


def test_missing_fields_are_simply_absent():
    scope = map_hermes_scope({})
    assert scope.levels == {}
