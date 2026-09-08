from typing import Iterable, Optional

from core.checkpoints.manager import CheckpointManager
from core.formation.candidate_extractor import CandidateExtractor
from core.formation.evaluator import MemoryEvaluator
from core.lifecycle.manager import LifecycleManager
from core.recall.context_builder import ContextBuilder
from core.recall.planner import RecallPlanner
from core.recall.ranker import Ranker
from core.recall.retriever import Retriever
from core.reconciliation.evidence_retriever import EvidenceRetriever
from core.reconciliation.reconciler import Reconciler
from core.reconciliation.validator import Validator
from domain.interfaces.checkpoint_store import CheckpointStore
from domain.interfaces.graph_store import GraphStore
from domain.interfaces.knowledge_store import KnowledgeStore
from domain.interfaces.lifecycle_store import LifecycleStore
from domain.interfaces.llm_provider import LLMProvider
from domain.models.checkpoint import Checkpoint
from domain.models.experience import Experience
from domain.models.memory import Memory
from domain.models.recall_query import RecallQuery
from domain.models.recall_result import RecallResult
from domain.models.scope import MemoryScope


class AftermindService:
    """Composition root: wires formation, reconciliation, recall,
    checkpoints, and lifecycle behind four public operations —
    observe, recall, checkpoint, search — the same four surface both
    the REST API and the MCP tools call into. Nothing outside this
    class should need to know the pipeline's internal stages.
    """

    def __init__(
        self,
        knowledge_store: KnowledgeStore,
        graph_store: GraphStore,
        checkpoint_store: CheckpointStore,
        lifecycle_store: LifecycleStore,
        llm_provider: LLMProvider,
    ) -> None:
        self.knowledge_store = knowledge_store
        self.graph_store = graph_store

        self._extractor = CandidateExtractor()
        self._evaluator = MemoryEvaluator()
        self._evidence_retriever = EvidenceRetriever(knowledge_store)
        self._reconciler = Reconciler(llm_provider)
        self._validator = Validator()

        self._recall_planner = RecallPlanner()
        self._recall_retriever = Retriever(knowledge_store, graph_store)
        self._ranker = Ranker()
        self._context_builder = ContextBuilder()

        self._checkpoints = CheckpointManager(checkpoint_store)
        self._lifecycle = LifecycleManager(lifecycle_store)

    def observe(self, experience: Experience) -> Optional[Memory]:
        """Learn from one experience: extract -> evaluate -> retrieve
        evidence -> reconcile -> validate -> apply. Returns the
        resulting memory, or None if nothing was worth remembering or
        the reconciler decided to ignore it."""
        candidates = self._extractor.extract(experience)
        if not candidates:
            return None

        candidate = self._evaluator.evaluate(candidates[0])
        if not self._evaluator.is_worth_remembering(candidate):
            return None

        evidence = self._evidence_retriever.retrieve(candidate)
        decision = self._reconciler.reconcile(candidate, evidence)
        decision = self._validator.validate(decision, candidate, evidence)
        memory = self._reconciler.apply(decision, candidate, self.knowledge_store)

        if memory is not None:
            self._lifecycle.get_or_create(memory)
            # If applying this decision superseded any evidence memory,
            # archive that memory's lifecycle record (content untouched).
            for evidence_memory in evidence:
                refreshed = self.knowledge_store.get(evidence_memory.memory_id)
                if refreshed is not None and refreshed.superseded_by:
                    self._lifecycle.archive_superseded(refreshed)

        self._checkpoints.checkpoint_experience(experience, memory_ids=[memory.memory_id] if memory else [])
        return memory

    def recall(self, query: RecallQuery) -> RecallResult:
        """Reconstruct context for `query`: latest checkpoint + ranked
        relevant memories + related entities, compressed into one block
        of text. Retrieved memories are reinforced (lifecycle access)."""
        checkpoint = self._checkpoints.latest(query.scope)
        plan = self._recall_planner.plan(query, checkpoint)
        evidence = self._recall_retriever.retrieve(plan)
        ranked = self._ranker.rank(plan.search_terms, list(evidence.memories), limit=query.limit)

        for memory in ranked:
            self._lifecycle.record_access(memory.memory_id, scope=memory.scope)

        context = self._context_builder.build(checkpoint, ranked, evidence.related_entities)

        return RecallResult(
            query_id=query.query_id,
            checkpoint=checkpoint,
            memories=tuple(ranked),
            related_entities=evidence.related_entities,
            context=context,
        )

    def checkpoint(
        self,
        scope: Optional[MemoryScope] = None,
        goal: str = "",
        current: str = "",
        completed: Iterable[str] = (),
        blockers: Iterable[str] = (),
        next_steps: Iterable[str] = (),
        memory_ids: Iterable[str] = (),
        reason: str = "manual",
    ) -> Checkpoint:
        """Explicitly record a checkpoint (as opposed to one derived
        automatically from an experience via observe())."""
        return self._checkpoints.create(
            scope=scope,
            goal=goal,
            current=current,
            completed=completed,
            blockers=blockers,
            next_steps=next_steps,
            memory_ids=memory_ids,
            reason=reason,
        )

    def latest_checkpoint(self, scope: Optional[MemoryScope] = None) -> Optional[Checkpoint]:
        return self._checkpoints.latest(scope)

    def search(self, query: str, scope: Optional[MemoryScope] = None, limit: int = 5) -> list[Memory]:
        """Direct memory search, without the full recall pipeline
        (no checkpoint, no ranking, no context compression)."""
        return self.knowledge_store.search(query, scope=scope.stable() if scope else None, limit=limit)
