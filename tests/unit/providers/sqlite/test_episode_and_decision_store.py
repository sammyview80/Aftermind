from domain.enums.event_type import EventType
from domain.enums.reconciliation_action import ReconciliationAction
from domain.models.event import Event
from domain.models.experience import Experience
from domain.models.memory_decision import MemoryDecision
from domain.models.scope import MemoryScope
from providers.sqlite.client import SqliteClient
from providers.sqlite.decision_store import SqliteDecisionStore
from providers.sqlite.episode_store import SqliteEpisodeStore


def test_episode_store_round_trips_events(tmp_path):
    store = SqliteEpisodeStore(SqliteClient(str(tmp_path / "test.db")))
    scope = MemoryScope.of(tenant_id="t1")
    experience = Experience(
        scope=scope,
        events=[Event(event_type=EventType.AGENT_MESSAGE, payload={"text": "hello"})],
        output="hello",
    )

    store.save(experience)
    fetched = store.get(experience.experience_id)

    assert fetched.output == "hello"
    assert fetched.events[0].event_type == EventType.AGENT_MESSAGE
    assert fetched.events[0].payload["text"] == "hello"


def test_episode_store_get_missing_returns_none(tmp_path):
    store = SqliteEpisodeStore(SqliteClient(str(tmp_path / "test.db")))
    assert store.get("nonexistent") is None


def test_decision_store_saves_without_error(tmp_path):
    store = SqliteDecisionStore(SqliteClient(str(tmp_path / "test.db")))
    decision = MemoryDecision(candidate_id="c1", action=ReconciliationAction.CREATE, confidence=0.9)

    saved = store.save(decision)

    assert saved is decision  # save() is a pass-through, just persists
