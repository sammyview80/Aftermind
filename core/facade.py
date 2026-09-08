from typing import Iterable, Optional

from core.checkpoints.manager import CheckpointManager
from core.checkpoints.summarizer import LLMCheckpointSummarizer
from core.consolidation.consolidator import LLMConsolidator
from core.consolidation.planner import ConsolidationPlanner
from core.consolidation.triggers import (
    AUTO_CONSOLIDATION_MEMORY_THRESHOLD,
    DEFAULT_MEMORY_COUNT_THRESHOLD,
    DEFAULT_MILESTONE_TRIGGERS,
    ConsolidationTrigger,
    is_milestone_event,
)
from core.consolidation.validator import ConsolidationValidator
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
from domain.enums.memory_status import MemoryStatus
from domain.interfaces.checkpoint_store import CheckpointStore
from domain.interfaces.decision_store import DecisionStore
from domain.interfaces.document_store import DocumentStore
from domain.interfaces.episode_store import EpisodeStore
from domain.interfaces.graph_store import GraphStore
from domain.interfaces.knowledge_store import KnowledgeStore
from domain.interfaces.lifecycle_store import LifecycleStore
from domain.interfaces.llm_provider import LLMProvider
from domain.models.checkpoint import Checkpoint
from domain.models.consolidation_result import ConsolidationResult
from domain.models.experience import Experience
from domain.models.memory import Memory
from domain.models.recall_query import RecallQuery
from domain.models.recall_result import RecallResult
from domain.models.scope import MemoryScope

# sync_to_graph extracts (source, relation, target) triples from a
# Memory and writes them via whatever GraphStore is wired in — pure
# logic against the GraphStore Protocol, no dependency on graphiti-
# core/Neo4j specifically, despite living under providers/graphiti/
# (that's the module's original home, not a layering statement). A
# cheap regex handles simple atomic sentences; compound/merged content
# goes through LLMTripleExtractor instead of stretching the regex to
# cover shapes it can't safely parse (see providers/graphiti/validation.py).
from providers.graphiti.triple_extractor import LLMTripleExtractor, mark_stale_in_graph, sync_to_graph
from providers.llm.base import load_prompt


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
        episode_store: Optional[EpisodeStore] = None,
        decision_store: Optional[DecisionStore] = None,
        document_store: Optional[DocumentStore] = None,
    ) -> None:
        self.knowledge_store = knowledge_store
        self.graph_store = graph_store
        self._episode_store = episode_store
        self._decision_store = decision_store
        self._document_store = document_store

        self._extractor = CandidateExtractor()
        self._evaluator = MemoryEvaluator()
        self._evidence_retriever = EvidenceRetriever(knowledge_store)
        self._reconciler = Reconciler(llm_provider)
        self._validator = Validator()
        self._triple_extractor = LLMTripleExtractor(llm_provider, system_prompt=load_prompt("triple_extractor"))

        self._recall_planner = RecallPlanner()
        self._recall_retriever = Retriever(knowledge_store, graph_store)
        self._ranker = Ranker()
        self._context_builder = ContextBuilder()

        self._checkpoints = CheckpointManager(checkpoint_store)
        self._lifecycle = LifecycleManager(lifecycle_store)
        self._checkpoint_summarizer = LLMCheckpointSummarizer(llm_provider, system_prompt=load_prompt("checkpoint"))

        self._consolidator = LLMConsolidator(llm_provider, system_prompt=load_prompt("consolidator"))
        self._consolidation_validator = ConsolidationValidator()

    def observe(self, experience: Experience) -> Optional[Memory]:
        """Learn from one experience: extract -> evaluate -> retrieve
        evidence -> reconcile -> validate -> apply. Returns the
        resulting memory, or None if nothing was worth remembering or
        the reconciler decided to ignore it."""
        if self._episode_store is not None:
            self._episode_store.save(experience)

        candidates = self._extractor.extract(experience)
        if not candidates:
            return None

        candidate = self._evaluator.evaluate(candidates[0])
        if not self._evaluator.is_worth_remembering(candidate):
            return None

        evidence = self._evidence_retriever.retrieve(candidate)
        decision = self._reconciler.reconcile(candidate, evidence)
        decision = self._validator.validate(decision, candidate, evidence)

        if self._decision_store is not None:
            self._decision_store.save(decision)

        memory = self._reconciler.apply(decision, candidate, self.knowledge_store)

        if memory is not None:
            self._lifecycle.get_or_create(memory)
            # If applying this decision superseded any evidence memory,
            # archive that memory's lifecycle record (content untouched),
            # and treat any OpenKnowledge page built from it as stale.
            for evidence_memory in evidence:
                refreshed = self.knowledge_store.get(evidence_memory.memory_id)
                if refreshed is not None and refreshed.superseded_by:
                    self._lifecycle.archive_superseded(refreshed)
                    self._reconsolidate_stale_page(refreshed, memory.scope)
                    mark_stale_in_graph(refreshed, self.graph_store, llm_extractor=self._triple_extractor)
            # StoredMemory -> entity/relationship extraction -> GraphStore.
            sync_to_graph(memory, self.graph_store, llm_extractor=self._triple_extractor)

        self._checkpoints.checkpoint_experience(experience, memory_ids=[memory.memory_id] if memory else [])

        if memory is not None:
            self._auto_consolidate(memory, experience)

        return memory

    def _document_slug(self, scope: Optional[MemoryScope]) -> str:
        project = (scope.get("project_id") if scope else None) or "default"
        return f"projects/{project}/knowledge"

    def _document_title(self, scope: Optional[MemoryScope]) -> str:
        project = (scope.get("project_id") if scope else None) or "default"
        return f"{project} Knowledge"

    def _run_consolidation_plan(self, plan, slug: str, title: str) -> Optional[ConsolidationResult]:
        candidate = self._consolidator.consolidate(plan)
        result = self._consolidation_validator.validate(candidate)
        return self._consolidator.apply(candidate, result, self._document_store, slug=slug, title=title)

    def _auto_consolidate(self, memory: Memory, experience: Experience) -> None:
        """Unsupervised knowledge promotion: after observe() commits a
        memory, check whether a cluster it belongs to is now worth
        writing/updating in OpenKnowledge. Deliberately conservative —
        this is not run on every memory, only when one of the milestone
        spec's conditions holds:
          - 5+ related durable memories now cluster on one topic, or
          - the triggering event is a confirmed decision / completed
            task / agent handoff (checkpoint-worthy milestones).
        Never fires on plain chat/tool-call noise, since those never
        pass MemoryEvaluator.is_worth_remembering() to reach here as a
        `memory` in the first place.
        """
        if self._document_store is None:
            return

        scope = memory.scope.stable() if memory.scope else None
        is_milestone = any(is_milestone_event(e.event_type, DEFAULT_MILESTONE_TRIGGERS) for e in experience.events)

        # A confirmed decision / completed task / handoff is itself a
        # meaningful-enough signal that it doesn't need the full 5-memory
        # bar the plain topic-threshold path requires — but it still
        # needs more than a couple of memories to preserve real
        # provenance, so it isn't fired by trivial one-off milestones.
        min_group_size = DEFAULT_MEMORY_COUNT_THRESHOLD if is_milestone else AUTO_CONSOLIDATION_MEMORY_THRESHOLD
        live_memories = self.knowledge_store.list_all(scope=scope)
        planner = ConsolidationPlanner(min_group_size=min_group_size)
        trigger = ConsolidationTrigger.MILESTONE if is_milestone else ConsolidationTrigger.TOPIC_THRESHOLD
        plans = planner.plan(live_memories, trigger, scope=scope)

        if is_milestone:
            # A confirmed decision / completed task is a natural point to
            # promote whatever topics are currently ready, not just the
            # one this particular memory happens to belong to.
            relevant_plans = plans
        else:
            relevant_plans = [p for p in plans if any(m.memory_id == memory.memory_id for m in p.memories)]

        slug = self._document_slug(scope)
        title = self._document_title(scope)
        for plan in relevant_plans:
            self._run_consolidation_plan(plan, slug, title)

    def _reconsolidate_stale_page(self, superseded_memory: Memory, scope: Optional[MemoryScope]) -> None:
        """A memory that fed into an OpenKnowledge section just got
        superseded — if that section still exists, re-derive it from
        current live memories and overwrite it in place, rather than
        leaving stale content or minting architecture-2.md. No-op if no
        document/section was ever built from this memory's topic."""
        if self._document_store is None:
            return

        stable_scope = scope.stable() if scope else None
        slug = self._document_slug(stable_scope)
        document = self._document_store.get(slug, scope=stable_scope)
        if document is None or superseded_memory.memory_id not in document.source_memory_ids:
            return

        existing_headings = {section.heading for section in document.sections}
        if not existing_headings:
            return

        live_memories = self.knowledge_store.list_all(scope=stable_scope)
        planner = ConsolidationPlanner(min_group_size=2)
        plans = planner.plan(live_memories, ConsolidationTrigger.STALE_PAGE, scope=stable_scope)

        for plan in plans:
            if plan.topic in existing_headings:
                self._run_consolidation_plan(plan, slug, document.title)

    def recall(self, query: RecallQuery) -> RecallResult:
        """Hybrid recall: fuse SQLite (current + historical memories),
        Neo4j/Graphiti (relationships), OpenKnowledge (consolidated
        knowledge), and the latest checkpoint into one ranked, compact
        context — not four raw blobs. Retrieved memories are reinforced
        (lifecycle access)."""
        stable_scope = query.scope.stable() if query.scope else None
        checkpoint = self._checkpoints.latest(query.scope)
        plan = self._recall_planner.plan(query, checkpoint)
        evidence = self._recall_retriever.retrieve(plan)

        statuses = {
            memory.memory_id: self._lifecycle.status_of(memory.memory_id, scope=memory.scope)
            for memory in evidence.memories
        }
        # Archived/expired/forgotten memories are excluded from *normal*
        # recall entirely — same treatment as superseded ones — not just
        # deprioritized by score. history() (via evidence.historical_memories)
        # is the deliberate path for surfacing them when asked for.
        _EXCLUDED_FROM_RECALL = frozenset({MemoryStatus.ARCHIVED, MemoryStatus.EXPIRED, MemoryStatus.FORGOTTEN})
        recallable = [m for m in evidence.memories if statuses[m.memory_id] not in _EXCLUDED_FROM_RECALL]
        ranked = self._ranker.rank(
            plan.search_terms,
            recallable,
            limit=query.limit,
            query_scope=stable_scope,
            statuses=statuses,
        )

        for memory in ranked:
            self._lifecycle.record_access(memory.memory_id, scope=memory.scope)

        knowledge_excerpts: tuple[str, ...] = ()
        if self._document_store is not None and query.text:
            documents = self._document_store.search(query.text, scope=stable_scope, limit=2)
            knowledge_excerpts = tuple(
                f"### {section.heading}\n{section.body}"
                for document in documents
                for section in document.sections
            )

        context = self._context_builder.build(
            checkpoint,
            ranked,
            evidence.related_entities,
            relationships=evidence.relationships,
            historical_memories=evidence.historical_memories,
            knowledge_excerpts=knowledge_excerpts,
        )

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

    def checkpoint_from_text(
        self,
        scope: Optional[MemoryScope] = None,
        text: str = "",
        memory_ids: Iterable[str] = (),
        reason: str = "session_end",
    ) -> Optional[Checkpoint]:
        """Automatic checkpoint from freeform conversation text (e.g. a
        Hermes session ending) — LLMCheckpointSummarizer structures it
        into goal/completed/current/blockers/next_steps first, using the
        latest checkpoint's goal as continuity context, so a session
        that only reports progress on an existing goal doesn't lose it.
        Returns None for empty/whitespace-only text (nothing to summarize)."""
        if not text or not text.strip():
            return None

        previous = self._checkpoints.latest(scope)
        experience = Experience(scope=scope, input=text, output=text)
        summary = self._checkpoint_summarizer.summarize(experience, previous_goal=previous.goal if previous else "")

        return self._checkpoints.create(
            scope=scope,
            goal=summary.goal,
            current=summary.current,
            completed=summary.completed,
            blockers=summary.blockers,
            next_steps=summary.next_steps,
            memory_ids=memory_ids,
            reason=reason,
        )

    def latest_checkpoint(self, scope: Optional[MemoryScope] = None) -> Optional[Checkpoint]:
        return self._checkpoints.latest(scope)

    def search(self, query: str, scope: Optional[MemoryScope] = None, limit: int = 5) -> list[Memory]:
        """Direct memory search, without the full recall pipeline
        (no checkpoint, no ranking, no context compression)."""
        return self.knowledge_store.search(query, scope=scope.stable() if scope else None, limit=limit)

    def run_lifecycle_maintenance(self, scope: Optional[MemoryScope] = None):
        """Memory hygiene pass: decay every lifecycle record in scope and
        archive the ones that came out fully stale and were never
        recalled — not immediate deletion. Meant to be run periodically
        (cron/scheduler), not on every observe()/recall() call."""
        return self._lifecycle.run_hygiene_sweep(scope=scope.stable() if scope else None)

    def consolidate(
        self,
        scope: Optional[MemoryScope] = None,
        slug: str = "consolidated-knowledge",
        title: str = "Consolidated Knowledge",
        min_group_size: int = DEFAULT_MEMORY_COUNT_THRESHOLD,
        trigger: ConsolidationTrigger = ConsolidationTrigger.MANUAL,
    ) -> list[ConsolidationResult]:
        """Pull every live memory in scope -> cluster related ones ->
        synthesize each cluster into one durable statement -> validate
        -> write into OpenKnowledge. Source memories are never deleted
        or rewritten — only linked to via source_memory_ids. Raises if
        no DocumentStore (OpenKnowledge) was configured, since there's
        nowhere to write the result."""
        if self._document_store is None:
            raise ValueError("consolidate() requires a DocumentStore (OpenKnowledge) to be configured")

        stable_scope = scope.stable() if scope else None
        memories = self.knowledge_store.list_all(scope=stable_scope)

        planner = ConsolidationPlanner(min_group_size=min_group_size)
        plans = planner.plan(memories, trigger, scope=stable_scope)

        results = []
        for plan in plans:
            candidate = self._consolidator.consolidate(plan)
            result = self._consolidation_validator.validate(candidate)
            result = self._consolidator.apply(candidate, result, self._document_store, slug=slug, title=title)
            results.append(result)
        return results
