"""In-process default backends for KnowledgeStore/GraphStore/
CheckpointStore/LifecycleStore.

These are real, working implementations — not test doubles — for
running Aftermind standalone without Postgres/Neo4j/OpenKnowledge
provisioned yet. State doesn't survive a process restart. Swap in the
Postgres/Graphiti-backed equivalents behind the same Protocols for
production persistence.
"""
import threading
from dataclasses import replace
from datetime import datetime
from typing import Optional

from domain.enums.sync_job_status import SyncJobStatus
from domain.models.checkpoint import Checkpoint
from domain.models.memory import Memory
from domain.models.memory_lifecycle import MemoryLifecycle
from domain.models.scope import MemoryScope
from domain.models.sync_job import SyncJob


def _scope_key(scope: Optional[MemoryScope]) -> str:
    return scope.key() if scope is not None else "*"


class InMemoryKnowledgeStore:
    def __init__(self) -> None:
        self._memories: dict[str, Memory] = {}

    def search(self, query: str, scope: Optional[MemoryScope] = None, limit: int = 5) -> list[Memory]:
        query_words = _words(query)

        def overlap(memory: Memory) -> float:
            memory_words = _words(memory.content)
            if not query_words or not memory_words:
                return 0.0
            return len(query_words & memory_words) / len(query_words | memory_words)

        scope_key = _scope_key(scope)
        candidates = [
            m for m in self._memories.values() if m.superseded_by is None and _scope_key(m.scope) == scope_key
        ]
        ranked = sorted((m for m in candidates if overlap(m) > 0), key=overlap, reverse=True)
        return ranked[:limit]

    def history(self, query: str, scope: Optional[MemoryScope] = None, limit: int = 5) -> list[Memory]:
        query_words = _words(query)

        def overlap(memory: Memory) -> float:
            memory_words = _words(memory.content)
            if not query_words or not memory_words:
                return 0.0
            return len(query_words & memory_words) / len(query_words | memory_words)

        scope_key = _scope_key(scope)
        candidates = [
            m for m in self._memories.values() if m.superseded_by is not None and _scope_key(m.scope) == scope_key
        ]
        ranked = sorted((m for m in candidates if overlap(m) > 0), key=overlap, reverse=True)
        return ranked[:limit]

    def get(self, memory_id: str) -> Optional[Memory]:
        return self._memories.get(memory_id)

    def save(self, memory: Memory) -> Memory:
        self._memories[memory.memory_id] = memory
        return memory

    def list_all(self, scope: Optional[MemoryScope] = None, limit: int = 1000) -> list[Memory]:
        scope_key = _scope_key(scope)
        return [
            m for m in self._memories.values() if m.superseded_by is None and _scope_key(m.scope) == scope_key
        ][:limit]


class InMemoryGraphStore:
    def __init__(self) -> None:
        # (source, relation, target, scope_key, historical)
        self._edges: list[tuple[str, str, str, str, bool]] = []
        self._entities: set[tuple[str, str]] = set()

    def upsert_entity(self, name: str, scope: Optional[MemoryScope] = None) -> None:
        self._entities.add((name, _scope_key(scope)))

    def upsert_relationship(
        self, source: str, relation: str, target: str, scope: Optional[MemoryScope] = None
    ) -> None:
        # Idempotent: a retried sync job re-writes the same triples, and
        # that must not duplicate edges (GraphitiStore dedupes the same way
        # via graphiti-core's exact-duplicate resolution).
        edge = (source, relation, target, _scope_key(scope), False)
        if edge not in self._edges:
            self._edges.append(edge)

    def find_related(self, entity: str, scope: Optional[MemoryScope] = None, limit: int = 5) -> list[str]:
        scope_key = _scope_key(scope)
        entity_lower = entity.lower()
        return [
            t for s, _, t, sk, historical in self._edges if s.lower() == entity_lower and sk == scope_key and not historical
        ][:limit]

    def find_relationships(
        self, entity: str, scope: Optional[MemoryScope] = None, limit: int = 5
    ) -> list[tuple[str, str, str]]:
        # Case-insensitive to match GraphitiStore's real behavior — entity
        # seeds from recall planning are lowercased keywords, while
        # entity names are stored with whatever casing they were
        # extracted with.
        scope_key = _scope_key(scope)
        entity_lower = entity.lower()
        return [
            (s, r, t)
            for s, r, t, sk, historical in self._edges
            if s.lower() == entity_lower and sk == scope_key and not historical
        ][:limit]

    def mark_historical(
        self, source: str, relation: str, target: str, scope: Optional[MemoryScope] = None
    ) -> None:
        scope_key = _scope_key(scope)
        source_lower, target_lower = source.lower(), target.lower()
        for i, (s, r, t, sk, historical) in enumerate(self._edges):
            if s.lower() == source_lower and t.lower() == target_lower and r == relation and sk == scope_key:
                self._edges[i] = (s, r, t, sk, True)

    def find_historical_relationships(
        self, entity: str, scope: Optional[MemoryScope] = None, limit: int = 5
    ) -> list[tuple[str, str, str]]:
        scope_key = _scope_key(scope)
        entity_lower = entity.lower()
        return [
            (s, r, t)
            for s, r, t, sk, historical in self._edges
            if s.lower() == entity_lower and sk == scope_key and historical
        ][:limit]


class InMemoryCheckpointStore:
    def __init__(self) -> None:
        self._checkpoints: list[Checkpoint] = []

    def save(self, checkpoint: Checkpoint) -> Checkpoint:
        self._checkpoints.append(checkpoint)
        return checkpoint

    def latest(self, scope: Optional[MemoryScope] = None) -> Optional[Checkpoint]:
        matching = [c for c in self._checkpoints if c.scope == scope]
        return matching[-1] if matching else None


class InMemoryLifecycleStore:
    def __init__(self) -> None:
        self._records: dict[str, MemoryLifecycle] = {}

    def get(self, memory_id: str, scope: Optional[MemoryScope] = None) -> Optional[MemoryLifecycle]:
        return self._records.get(memory_id)

    def save(self, lifecycle: MemoryLifecycle) -> MemoryLifecycle:
        self._records[lifecycle.memory_id] = lifecycle
        return lifecycle

    def list_all(self, scope: Optional[MemoryScope] = None) -> list[MemoryLifecycle]:
        if scope is None:
            return list(self._records.values())
        scope_key = _scope_key(scope)
        return [r for r in self._records.values() if _scope_key(r.scope) == scope_key]


class InMemorySyncJobStore:
    """SyncJobStore without durability — for tests and for running the
    outbox/worker machinery in-process without SQLite. Thread-safe, since
    a background worker and request threads share it."""

    def __init__(self) -> None:
        self._jobs: dict[str, SyncJob] = {}
        self._lock = threading.Lock()

    def enqueue(self, job: SyncJob) -> SyncJob:
        return self.save(job)

    def save(self, job: SyncJob) -> SyncJob:
        with self._lock:
            self._jobs[job.job_id] = job
        return job

    def get(self, job_id: str) -> Optional[SyncJob]:
        with self._lock:
            return self._jobs.get(job_id)

    def claim_due(self, now: datetime, limit: int = 10) -> list[SyncJob]:
        with self._lock:
            due = sorted(
                (j for j in self._jobs.values() if j.status == SyncJobStatus.PENDING and j.next_attempt_at <= now),
                key=lambda j: (j.next_attempt_at, j.created_at),
            )[:limit]
            claimed = [replace(j, status=SyncJobStatus.RUNNING, updated_at=now) for j in due]
            for job in claimed:
                self._jobs[job.job_id] = job
        return claimed

    def list_jobs(self, status: Optional[SyncJobStatus] = None, limit: int = 100) -> list[SyncJob]:
        with self._lock:
            jobs = [j for j in self._jobs.values() if status is None or j.status == status]
        return sorted(jobs, key=lambda j: j.created_at, reverse=True)[:limit]

    def counts(self) -> dict[str, int]:
        counts = {status.value: 0 for status in SyncJobStatus}
        with self._lock:
            for job in self._jobs.values():
                counts[job.status.value] += 1
        return counts

    def recover_running(self, older_than: datetime) -> int:
        reset = 0
        with self._lock:
            for job_id, job in list(self._jobs.items()):
                if job.status == SyncJobStatus.RUNNING and job.updated_at <= older_than:
                    self._jobs[job_id] = replace(job, status=SyncJobStatus.PENDING, updated_at=older_than)
                    reset += 1
        return reset


def _words(text: str) -> set[str]:
    return {w.strip(".,!?").lower() for w in text.split() if w.strip(".,!?")}
