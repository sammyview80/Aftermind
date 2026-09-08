# Aftermind

Framework-neutral, persistent memory runtime for AI agents — recall, formation/reconciliation, checkpoints, consolidation, and lifecycle management, exposed over REST and MCP, with adapters for agent frameworks (Hermes, LangGraph, CrewAI, AutoGen).

> **License note:** Aftermind is source-available under the **PolyForm Noncommercial License 1.0.0** (see `LICENSE`). This project and any use of it **is not for commercial use**. Noncommercial use — personal, research, educational, and by charitable/public organizations — is permitted. See `LICENSE` for the exact terms.

## What it does

- **Observe** — turns raw agent experience (conversation turns, tool results) into durable memories via an LLM-driven extraction/reconciliation pipeline (create/update/merge/supersede/ignore).
- **Recall** — plans, retrieves, ranks, and assembles relevant memory context for a new query.
- **Checkpoint** — snapshots goal/progress/next-steps so a new session can pick up where the last one left off.
- **Consolidate** — clusters related memories into durable knowledge documents.
- **Lifecycle** — reinforcement, decay, archival, and forgetting of memories over time.

Storage is pluggable: SQLite, Neo4j/Graphiti (graph), OpenKnowledge (durable knowledge docs), or in-memory fakes for testing.

## Architecture

See `AGENTS.md` for the full layering rules and conventions. Short version:

```
domain/        models + interfaces, no I/O
core/          business logic, depends only on domain/
providers/     concrete backends (sqlite, graphiti/neo4j, openknowledge, llm)
apps/api/      REST + MCP server (composition root)
integrations/  framework adapters (hermes, langgraph, crewai, autogen)
sdk/           client libraries (python, typescript)
```

## Quick start

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
cp .env.example .env   # fill in LLM_API_KEY etc.

.venv/bin/python -m pytest tests/ -q --ignore=tests/integration/test_full_memory_loop_live.py

.venv/bin/python -m uvicorn apps.api.main:app --host 0.0.0.0 --port 8000
```

Or, once installed (`pip install -e .`), use the CLI:

```bash
aftermind serve                 # REST + MCP API with in-process sync worker
aftermind worker                # outbox sync worker as a separate process
aftermind sync status|run|retry # inspect / drain / requeue the durable outbox
aftermind backup DEST           # consistent snapshot of the SQLite database
aftermind check                 # SQLite integrity check
aftermind config                # effective configuration, secrets redacted
```

REST: `/observe`, `/recall`, `/checkpoint`, `/checkpoint/latest`, `/checkpoint/from-text`, `/search`, `/consolidate`, `/maintenance/sweep`, `/maintenance/sync`, `/traces`, `/config`, `/health`, `/health/ready`. MCP: mounted at `/mcp/`.

Docker: `docker compose up -d` starts the API and Neo4j (see `docker-compose.yml`, `Dockerfile`).

## Reliability model

SQLite is the canonical store. Neo4j/Graphiti (relationships) and OpenKnowledge (consolidated documents) are derived views kept in sync through a **transactional outbox**:

```
observe()
  SQLite transaction
  ├─ write memory + lifecycle + decision + checkpoint
  └─ write sync jobs (graph_sync, knowledge_consolidate, ...)
  commit
  flush jobs   eager: try now; on failure the job stays pending with backoff
               background: leave for the worker
sync worker     retries pending jobs (1s..5min backoff), resumes after a crash,
                marks jobs dead after AFTERMIND_SYNC_MAX_ATTEMPTS
```

A Neo4j or OpenKnowledge outage therefore never loses a memory or fails an `observe()`; the response and trace show `neo4j_sync: pending` and the backlog is visible at `/maintenance/sync`. Reads degrade the same way: recall still returns SQLite memories when the graph or document store is down.

Every operation emits one structured trace (`aftermind.trace` logger, and `GET /traces`) with `observe_id`, scope, `candidate_count`, `reconciliation_action`, `sqlite_write`, `neo4j_sync`, `openknowledge_sync`, `checkpoint_created`, `recall_sources`, `llm_calls`, `llm_latency_ms`, latency, and per-stage spans. `/observe` returns the `observe_id` and per-store sync status; `X-Aftermind-Trace-Id` is set on responses.

Configuration is environment-only; see `.env.example` for every knob (`AFTERMIND_SYNC_MODE`, `AFTERMIND_SYNC_WORKER`, `NEO4J_TIMEOUT_SECONDS`, `AFTERMIND_LOG_FORMAT=json`, ...).

## Contributing

Contributions are welcome — see `CONTRIBUTING.md` for workflow, style, and testing expectations, and `CODE_OF_CONDUCT.md` for community standards.

## License

PolyForm Noncommercial License 1.0.0 — see `LICENSE`. Not for commercial use.
