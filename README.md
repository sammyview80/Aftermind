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

REST: `/observe`, `/recall`, `/checkpoint`, `/checkpoint/latest`, `/checkpoint/from-text`, `/search`, `/consolidate`, `/health`. MCP: mounted at `/mcp/`.

## Contributing

Contributions are welcome — see `CONTRIBUTING.md` for workflow, style, and testing expectations, and `CODE_OF_CONDUCT.md` for community standards.

## License

PolyForm Noncommercial License 1.0.0 — see `LICENSE`. Not for commercial use.
