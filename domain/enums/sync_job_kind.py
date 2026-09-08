from enum import Enum


class SyncJobKind(str, Enum):
    """What a durable sync job propagates from the canonical SQLite
    memory store to a secondary store. SQLite is the source of truth;
    every kind here re-derives its work from the memory row it names,
    so a job can be retried after a crash without carrying state of
    its own."""

    GRAPH_SYNC = "graph_sync"  # memory -> triples -> GraphStore (Neo4j/Graphiti)
    GRAPH_MARK_STALE = "graph_mark_stale"  # superseded memory -> mark its edges historical
    KNOWLEDGE_CONSOLIDATE = "knowledge_consolidate"  # memory -> maybe promote cluster to OpenKnowledge
    KNOWLEDGE_RECONSOLIDATE = "knowledge_reconsolidate"  # superseded memory -> refresh stale page section
