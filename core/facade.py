from contextlib import nullcontext
from typing import Iterable, Optional

from core.checkpoints.manager import CheckpointManager
from core.checkpoints.summarizer import CheckpointSummary, LLMCheckpointSummarizer
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
from core.formation.admission import gate as admission_gate
from core.formation.admission_llm import LLMAdmission, with_default_scores
from core.formation.candidate_extractor import CandidateExtractor, strip_agent_framing
from core.formation.evaluator import MemoryEvaluator
from core.lifecycle.manager import LifecycleManager
from core.observability import trace
from core.preferences.manager import PreferenceManager
from core.preferences.reconciler import LLMPreferenceReconciler
from core.observability.llm import TracedLLMProvider
from core.recall.context_builder import ContextBuilder
from core.recall.planner import RecallPlanner
from core.recall.ranker import Ranker
from core.recall.retriever import Retriever
from core.reconciliation.evidence_retriever import EvidenceRetriever
from core.reconciliation.reconciler import Reconciler
from core.reconciliation.validator import Validator
from core.sync.dispatcher import DEFAULT_EAGER_TIMEOUT_SECONDS, EAGER, SyncDispatcher
from domain.enums.memory_status import MemoryStatus
from domain.enums.sync_job_kind import SyncJobKind
from domain.interfaces.checkpoint_store import CheckpointStore
from domain.interfaces.decision_store import DecisionStore
from domain.interfaces.embedder import Embedder
from domain.interfaces.document_store import DocumentStore
from domain.interfaces.episode_store import EpisodeStore
from domain.interfaces.graph_store import GraphStore
from domain.interfaces.knowledge_store import KnowledgeStore
from domain.interfaces.lifecycle_store import LifecycleStore
from domain.interfaces.llm_provider import LLMProvider
from domain.interfaces.preference_evidence_store import PreferenceEvidenceStore
from domain.interfaces.preference_store import PreferenceStore
from domain.interfaces.sync_job_store import SyncJobStore
from domain.interfaces.unit_of_work import UnitOfWork
from domain.interfaces.vector_store import VectorStore
from domain.models.candidate import Candidate
from domain.models.checkpoint import Checkpoint
from domain.models.consolidation_result import ConsolidationResult
from domain.models.experience import Experience
from domain.models.memory import Memory
from domain.models.recall_query import RecallQuery
from domain.models.recall_result import RecallResult
from domain.models.scope import MemoryScope
from domain.models.sync_job import DEFAULT_MAX_ATTEMPTS, SyncJob

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

_EXCLUDED_FROM_RECALL = frozenset({MemoryStatus.ARCHIVED, MemoryStatus.EXPIRED, MemoryStatus.FORGOTTEN})


def _scope_key(scope: Optional[MemoryScope]) -> Optional[str]:
    return scope.key() if scope is not None else None


def _dedupe(items: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(i.strip() for i in items if i and i.strip()))


def _merge_checkpoint_summary(summary: CheckpointSummary, previous: Optional[Checkpoint]) -> CheckpointSummary:
    if previous is None:
        return summary
    completed = _dedupe((*previous.completed, *summary.completed))
    # Steps the new summary lists as completed are no longer "next".
    carried_next = tuple(step for step in previous.next_steps if step not in completed)
    next_steps = _dedupe(summary.next_steps) or carried_next
    return CheckpointSummary(
        goal=summary.goal.strip() or previous.goal,
        completed=completed,
        current=summary.current.strip() or previous.current,
        blockers=_dedupe(summary.blockers),
        next_steps=next_steps,
    )


class AftermindService:
    """Composition root: wires formation, reconciliation, recall,
    checkpoints, and lifecycle behind four public operations —
    observe, recall, checkpoint, search — the same four surface both
    the REST API and the MCP tools call into. Nothing outside this
    class should need to know the pipeline's internal stages.

    Reliability contract (see core/sync, core/observability):
      - The knowledge store (SQLite) is canonical. observe() commits the
        memory, its lifecycle record, decision, checkpoint and sync-job
        rows in one UnitOfWork transaction when one is wired.
      - Graph (Neo4j) and document (OpenKnowledge) propagation go
        through the SyncDispatcher: a failure there leaves a durable,
        retryable job and a `pending` trace field — never a failed
        observe() or a lost memory.
      - Every public operation runs inside an OperationTrace.
    """

    def __init__(
        self,
        knowledge_store: KnowledgeStore,
        graph_store: GraphStore,
        checkpoint_store: CheckpointStore,
        lifecycle_store: LifecycleStore,
        llm_provider: LLMProvider,
        preference_store: Optional[PreferenceStore] = None,
        preference_evidence_store: Optional[PreferenceEvidenceStore] = None,
        embedder: Optional[Embedder] = None,
        vector_store: Optional[VectorStore] = None,
        episode_store: Optional[EpisodeStore] = None,
        decision_store: Optional[DecisionStore] = None,
        document_store: Optional[DocumentStore] = None,
        sync_job_store: Optional[SyncJobStore] = None,
        unit_of_work: Optional[UnitOfWork] = None,
        sync_mode: str = EAGER,
        sync_max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        sync_eager_timeout: Optional[float] = DEFAULT_EAGER_TIMEOUT_SECONDS,
        admission_mode: str = "rules",
        memory_min_score: float = 0.5,
        max_candidate_chars: int = 600,
        tracer: trace.Tracer = trace.default_tracer,
    ) -> None:
        self.knowledge_store = knowledge_store
        self.graph_store = graph_store
        self._embedder = embedder
        self._vector_store = vector_store if embedder is not None else None
        self._episode_store = episode_store
        self._decision_store = decision_store
        self._document_store = document_store
        self._uow = unit_of_work
        self.tracer = tracer

        llm_provider = TracedLLMProvider(llm_provider)

        if admission_mode not in ("rules", "llm"):
            raise ValueError(f"admission_mode must be 'rules' or 'llm', got {admission_mode!r}")
        self.admission_mode = admission_mode
        self._max_candidate_chars = max_candidate_chars
        self._extractor = CandidateExtractor()
        self._evaluator = MemoryEvaluator(threshold=memory_min_score)
        self._llm_admission = LLMAdmission(
            llm_provider, system_prompt=load_prompt("admission"), min_score=memory_min_score
        )
        self._evidence_retriever = EvidenceRetriever(knowledge_store)
        self._reconciler = Reconciler(llm_provider)
        self._validator = Validator()
        self._triple_extractor = LLMTripleExtractor(llm_provider, system_prompt=load_prompt("triple_extractor"))

        self._recall_planner = RecallPlanner()
        self._recall_retriever = Retriever(knowledge_store, graph_store, self._embedder, self._vector_store)
        self._ranker = Ranker()
        self._context_builder = ContextBuilder()

        self._checkpoints = CheckpointManager(checkpoint_store)
        self._lifecycle = LifecycleManager(lifecycle_store)
        self._preferences = (
            PreferenceManager(
                preference_store,
                evidence_store=preference_evidence_store,
                reconciler=LLMPreferenceReconciler(llm_provider, system_prompt=load_prompt("preference_reconciler")),
            )
            if preference_store is not None
            else None
        )
        self._checkpoint_summarizer = LLMCheckpointSummarizer(llm_provider, system_prompt=load_prompt("checkpoint"))

        self._consolidator = LLMConsolidator(llm_provider, system_prompt=load_prompt("consolidator"))
        self._consolidation_validator = ConsolidationValidator()

        self.sync = SyncDispatcher(
            handlers={
                SyncJobKind.GRAPH_SYNC: self._handle_graph_sync,
                SyncJobKind.GRAPH_MARK_STALE: self._handle_graph_mark_stale,
                SyncJobKind.KNOWLEDGE_CONSOLIDATE: self._handle_knowledge_consolidate,
                SyncJobKind.KNOWLEDGE_RECONSOLIDATE: self._handle_knowledge_reconsolidate,
            },
            job_store=sync_job_store,
            mode=sync_mode,
            max_attempts=sync_max_attempts,
            eager_timeout=sync_eager_timeout,
        )

    def _transaction(self):
        return self._uow.transaction() if self._uow is not None else nullcontext()

    # ------------------------------------------------------------------ observe

    def observe(self, experience: Experience) -> Optional[Memory]:
        """Learn from one experience: extract -> evaluate -> retrieve
        evidence -> reconcile -> validate -> apply. Returns the
        resulting memory, or None if nothing was worth remembering or
        the reconciler decided to ignore it."""
        with self.tracer.begin("observe", scope=_scope_key(experience.scope)) as t:
            t.record(experience_id=experience.experience_id, sqlite_write=trace.SKIPPED)

            if self._episode_store is not None:
                with trace.span("episode_store.save"):
                    self._episode_store.save(experience)

            if self._preferences is not None:
                with trace.span("preferences.observe"):
                    self._observe_preference_signals(experience)

            candidates = self._admit(experience, t)
            t.record(candidate_count=len(candidates))

            created: list[Memory] = []
            for candidate in candidates:
                memory = self._commit_candidate(candidate, experience, t)
                if memory is not None:
                    created.append(memory)

            # Milestone events (task completed, handoff, ...) checkpoint even
            # when nothing in the text was memory-worthy.
            with trace.span("checkpoint"):
                checkpoint = self._checkpoints.checkpoint_experience(experience, memory_ids=[m.memory_id for m in created])
            t.record(checkpoint_created=checkpoint is not None)

            if not candidates:
                return None
            t.record(memory_ids=[m.memory_id for m in created])
            if self._document_store is None:
                t.record(openknowledge_sync=trace.SKIPPED)
            if not created:
                t.record(neo4j_sync=trace.SKIPPED)
                return None
            return created[0]

    def _observe_preference_signals(self, experience: Experience) -> None:
        """Behavior/preference learning is a side-channel to fact
        formation, not a fact itself — it runs against the user's own
        turn (`input`), independent of whether anything in it was
        admitted as memory. Heuristic hits apply immediately; everything
        else joins an evidence buffer the LLM reconciler periodically
        reads for subtler patterns (see `PreferenceManager.observe_text`)."""
        self._preferences.observe_text(experience.scope, experience.input or "")

    # ------------------------------------------------------------ admission

    def _admit(self, experience: Experience, t) -> list[Candidate]:
        """What, if anything, in this experience may become memory.

        1. Deterministic gate on the raw text (core/formation/admission.py):
           questions, directives, greetings, narration, tool output, code,
           markup and secrets never get further. Rejections are recorded as
           `admission=rejected:<reason>` on the trace.
        2. `llm` mode: one model call extracts atomic, third-person
           statements with usefulness/durability; each is gated again and
           held to the score bar. `rules` mode: the (framing-stripped) text
           is the single candidate, scored by the rule-based evaluator.
        Text the gate admits but flags as needing extraction (too long,
        error reports) becomes memory only through the LLM path.
        """
        text = strip_agent_framing((experience.output or experience.input or "").strip())
        event_types = [e.event_type for e in experience.events]
        decision = admission_gate(text, event_types, max_chars=self._max_candidate_chars)
        if not decision.admitted:
            t.record(admission=f"rejected:{decision.reason}")
            return []

        if self.admission_mode == "llm":
            with trace.span("admission.llm"):
                candidates = self._llm_admission.extract(experience)
            t.record(admission="llm", admission_proposals=len(candidates))
            return candidates

        if decision.needs_extraction:
            t.record(admission="rejected:needs_llm_extraction")
            return []

        candidates = self._extractor.extract(experience)
        admitted: list[Candidate] = []
        for candidate in candidates:
            scored = self._evaluator.evaluate(candidate)
            if self._evaluator.is_worth_remembering(scored):
                admitted.append(with_default_scores(scored))
        t.record(admission="rules" if admitted else "rejected:score")
        return admitted

    def _commit_candidate(self, candidate: Candidate, experience: Experience, t) -> Optional[Memory]:
        """Reconcile one admitted candidate against existing memory and
        commit it (plus lifecycle, decision and sync jobs) in one
        transaction; then flush the secondary-store jobs."""
        with trace.span("evidence.retrieve"):
            evidence = self._evidence_retriever.retrieve(candidate)
        t.record(evidence_count=len(evidence))
        with trace.span("reconcile"):
            decision = self._reconciler.reconcile(candidate, evidence)
        decision = self._validator.validate(decision, candidate, evidence)
        t.record(reconciliation_action=decision.action.value)

        is_milestone = any(is_milestone_event(e.event_type, DEFAULT_MILESTONE_TRIGGERS) for e in experience.events)
        jobs: list[SyncJob] = []

        # Everything below writes to the canonical store; one transaction
        # (when a UnitOfWork is wired) so a crash can't leave a memory
        # without its lifecycle row or its sync jobs — or vice versa.
        with trace.span("sqlite.transaction"), self._transaction():
            if self._decision_store is not None:
                self._decision_store.save(decision)

            memory = self._reconciler.apply(decision, candidate, self.knowledge_store)

            if memory is not None:
                t.record(sqlite_write=trace.OK, memory_id=memory.memory_id)
                self._lifecycle.get_or_create(memory)
                # If applying this decision superseded any evidence memory,
                # archive that memory's lifecycle record (content untouched),
                # and queue graph/document follow-ups for it.
                for evidence_memory in evidence:
                    refreshed = self.knowledge_store.get(evidence_memory.memory_id)
                    if refreshed is not None and refreshed.superseded_by:
                        self._lifecycle.archive_superseded(refreshed)
                        t.append("superseded_memory_ids", refreshed.memory_id)
                        jobs.append(
                            self.sync.enqueue(
                                SyncJobKind.GRAPH_MARK_STALE, {"memory_id": refreshed.memory_id}, memory.scope
                            )
                        )
                        if self._document_store is not None:
                            jobs.append(
                                self.sync.enqueue(
                                    SyncJobKind.KNOWLEDGE_RECONSOLIDATE,
                                    {"memory_id": refreshed.memory_id},
                                    memory.scope,
                                )
                            )
                jobs.append(self.sync.enqueue(SyncJobKind.GRAPH_SYNC, {"memory_id": memory.memory_id}, memory.scope))
                if self._document_store is not None:
                    jobs.append(
                        self.sync.enqueue(
                            SyncJobKind.KNOWLEDGE_CONSOLIDATE,
                            {"memory_id": memory.memory_id, "is_milestone": is_milestone},
                            memory.scope,
                        )
                    )

        if memory is None:
            return None

        # Committed. Secondary stores are now best-effort + durable retry.
        self.sync.flush(jobs)
        # Embedding runs *after* the transaction closes, same reasoning as
        # graph/document sync: a slow or first-download-ever model load
        # must never hold the SQLite write lock — it did, until this was
        # moved out of the `with self._transaction()` block above, and
        # blocked every other writer (including the background sync
        # worker) for as long as the model took to load.
        self._index_embedding(memory, t)
        return memory

    def _index_embedding(self, memory: Memory, t) -> None:
        """Best-effort semantic indexing — local (no retry queue needed
        the way a network-dependent secondary store would need one),
        but a broken/missing embedding model must never fail observe()
        over something recall can just as well degrade without."""
        if self._embedder is None or self._vector_store is None:
            return
        with trace.span("embedding.index", reraise=False) as span:
            embedding = self._embedder.embed(memory.content)
            self._vector_store.upsert(memory.memory_id, memory.scope, embedding, model=type(self._embedder).__name__)
        if span is not None and span.status == trace.FAILED:
            t.record(embedding_index=trace.FAILED)

    # --------------------------------------------------------- sync handlers

    def _handle_graph_sync(self, job: SyncJob) -> None:
        memory = self.knowledge_store.get(job.payload["memory_id"])
        if memory is None:
            return  # deleted/forgotten since; nothing to propagate
        sync_to_graph(memory, self.graph_store, llm_extractor=self._triple_extractor)

    def _handle_graph_mark_stale(self, job: SyncJob) -> None:
        memory = self.knowledge_store.get(job.payload["memory_id"])
        if memory is None:
            return
        mark_stale_in_graph(memory, self.graph_store, llm_extractor=self._triple_extractor)

    def _handle_knowledge_consolidate(self, job: SyncJob) -> None:
        memory = self.knowledge_store.get(job.payload["memory_id"])
        if memory is None:
            return
        self._auto_consolidate(memory, is_milestone=bool(job.payload.get("is_milestone", False)))

    def _handle_knowledge_reconsolidate(self, job: SyncJob) -> None:
        memory = self.knowledge_store.get(job.payload["memory_id"])
        if memory is None:
            return
        self._reconsolidate_stale_page(memory, job.scope)

    # ---------------------------------------------------------- consolidation

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

    def _auto_consolidate(self, memory: Memory, is_milestone: bool) -> None:
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
        trace.record(consolidation_plans=len(relevant_plans))

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

    # ------------------------------------------------------------------- recall

    def recall(self, query: RecallQuery) -> RecallResult:
        """Hybrid recall: fuse SQLite (current + historical memories),
        Neo4j/Graphiti (relationships), OpenKnowledge (consolidated
        knowledge), and the latest checkpoint into one ranked, compact
        context — not four raw blobs. Retrieved memories are reinforced
        (lifecycle access)."""
        with self.tracer.begin("recall", scope=_scope_key(query.scope)) as t:
            t.record(query_id=query.query_id, recall_sources=[])
            stable_scope = query.scope.stable() if query.scope else None

            with trace.span("checkpoint.latest"):
                checkpoint = self._checkpoints.latest(query.scope)

            plan = self._recall_planner.plan(query, checkpoint)
            # The domain router (core/recall/domain_router.py) decides whether
            # this query is actually asking to continue prior work — an
            # "our company's expense policy" question shouldn't drag the
            # checkpoint into context just because one happens to exist.
            checkpoint = checkpoint if plan.fetch_checkpoint else None
            if checkpoint is not None:
                t.append("recall_sources", "checkpoint")
            with trace.span("retrieve"):
                evidence = self._recall_retriever.retrieve(plan)
            if evidence.memories:
                t.append("recall_sources", "sqlite")
            if evidence.historical_memories:
                t.append("recall_sources", "sqlite_history")
            if evidence.related_entities or evidence.relationships:
                t.append("recall_sources", "graph")

            statuses = {
                memory.memory_id: self._lifecycle.status_of(memory.memory_id, scope=memory.scope)
                for memory in evidence.memories
            }
            # Archived/expired/forgotten memories are excluded from *normal*
            # recall entirely — same treatment as superseded ones — not just
            # deprioritized by score. history() (via evidence.historical_memories)
            # is the deliberate path for surfacing them when asked for.
            recallable = [m for m in evidence.memories if statuses[m.memory_id] not in _EXCLUDED_FROM_RECALL]
            ranked = self._ranker.rank(
                plan.search_terms,
                recallable,
                limit=query.limit,
                query_scope=stable_scope,
                statuses=statuses,
            )

            with trace.span("lifecycle.record_access"):
                for memory in ranked:
                    self._lifecycle.record_access(memory.memory_id, scope=memory.scope)

            knowledge_excerpts: tuple[str, ...] = ()
            if self._document_store is not None and plan.include_knowledge and query.text:
                # A down OpenKnowledge degrades recall (no excerpts) rather
                # than failing it — SQLite memories are still returned.
                with trace.span("document_store.search", reraise=False) as span:
                    documents = self._document_store.search(query.text, scope=stable_scope, limit=2)
                    knowledge_excerpts = tuple(
                        f"### {section.heading}\n{section.body}"
                        for document in documents
                        for section in document.sections
                    )
                if span is not None and span.status == trace.FAILED:
                    t.record(openknowledge_search=trace.FAILED)
                elif knowledge_excerpts:
                    t.append("recall_sources", "openknowledge")

            preferences = (
                self._preferences.profile(query.scope)
                if self._preferences is not None and plan.include_preferences
                else ()
            )
            if preferences:
                t.append("recall_sources", "preferences")

            context = self._context_builder.build(
                checkpoint,
                ranked,
                evidence.related_entities,
                relationships=evidence.relationships,
                historical_memories=evidence.historical_memories,
                knowledge_excerpts=knowledge_excerpts,
                preferences=preferences,
            )
            t.record(
                retrieved_count=len(evidence.memories),
                returned_count=len(ranked),
                context_chars=len(context),
            )

            return RecallResult(
                query_id=query.query_id,
                checkpoint=checkpoint,
                memories=tuple(ranked),
                related_entities=evidence.related_entities,
                context=context,
            )

    # -------------------------------------------------------------- checkpoint

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
        with self.tracer.begin("checkpoint", scope=_scope_key(scope), reason=reason) as t:
            checkpoint = self._checkpoints.create(
                scope=scope,
                goal=goal,
                current=current,
                completed=completed,
                blockers=blockers,
                next_steps=next_steps,
                memory_ids=memory_ids,
                reason=reason,
            )
            t.record(checkpoint_created=True, checkpoint_id=checkpoint.checkpoint_id, sqlite_write=trace.OK)
            return checkpoint

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

        with self.tracer.begin("checkpoint_from_text", scope=_scope_key(scope), reason=reason) as t:
            previous = self._checkpoints.latest(scope)
            experience = Experience(scope=scope, input=text, output=text)
            with trace.span("summarize"):
                summary = self._checkpoint_summarizer.summarize(
                    experience,
                    previous_goal=previous.goal if previous else "",
                    previous_completed=previous.completed if previous else (),
                    previous_next_steps=previous.next_steps if previous else (),
                )

            # Merge, don't replace: a trivial session must not erase the
            # hand-off state a substantive earlier session recorded.
            # Completed work accumulates; next steps are the new list when
            # the summarizer produced one, else carried forward; a blank
            # goal falls back to the previous goal.
            merged = _merge_checkpoint_summary(summary, previous)
            t.record(merged_from_previous=previous is not None)

            checkpoint = self._checkpoints.create(
                scope=scope,
                goal=merged.goal,
                current=merged.current,
                completed=merged.completed,
                blockers=merged.blockers,
                next_steps=merged.next_steps,
                memory_ids=memory_ids,
                reason=reason,
            )
            t.record(checkpoint_created=True, checkpoint_id=checkpoint.checkpoint_id, sqlite_write=trace.OK)
            return checkpoint

    def latest_checkpoint(self, scope: Optional[MemoryScope] = None) -> Optional[Checkpoint]:
        return self._checkpoints.latest(scope)

    # ------------------------------------------------------------------- others

    def search(self, query: str, scope: Optional[MemoryScope] = None, limit: int = 5) -> list[Memory]:
        """Direct memory search, without the full recall pipeline
        (no checkpoint, no ranking, no context compression)."""
        with self.tracer.begin("search", scope=_scope_key(scope)) as t:
            results = self.knowledge_store.search(query, scope=scope.stable() if scope else None, limit=limit)
            t.record(returned_count=len(results))
            return results

    def run_lifecycle_maintenance(self, scope: Optional[MemoryScope] = None):
        """Memory hygiene pass: decay every lifecycle record in scope and
        archive the ones that came out fully stale and were never
        recalled — not immediate deletion. Meant to be run periodically
        (cron/scheduler), not on every observe()/recall() call."""
        with self.tracer.begin("lifecycle_maintenance", scope=_scope_key(scope)) as t:
            results = self._lifecycle.run_hygiene_sweep(scope=scope.stable() if scope else None)
            t.record(swept=len(results), archived=sum(1 for r in results if r.status == MemoryStatus.ARCHIVED))
            return results

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

        with self.tracer.begin("consolidate", scope=_scope_key(scope), trigger=trigger.value) as t:
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
            t.record(consolidation_plans=len(plans), accepted=sum(1 for r in results if r.accepted))
            return results
