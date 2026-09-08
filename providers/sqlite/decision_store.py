from domain.models.memory_decision import MemoryDecision
from providers.sqlite.client import SqliteClient
from providers.sqlite.serialize import dump_json


class SqliteDecisionStore:
    """DecisionStore backed by SQLite — the reconciler's audit trail."""

    def __init__(self, client: SqliteClient) -> None:
        self._client = client

    def save(self, decision: MemoryDecision) -> MemoryDecision:
        with self._client.connect() as conn:
            conn.execute(
                """
                INSERT INTO memory_decisions (
                    decision_id, candidate_id, action, target_memory_id, evidence_memory_ids,
                    confidence, reasoning, metadata, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    decision.decision_id,
                    decision.candidate_id,
                    decision.action.value,
                    decision.target_memory_id,
                    dump_json(list(decision.evidence_memory_ids)),
                    decision.confidence,
                    decision.reasoning,
                    dump_json(dict(decision.metadata)),
                    decision.created_at.isoformat(),
                ),
            )
        return decision
