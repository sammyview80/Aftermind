# AGENTS.md

Guide for AI agents (and humans) working on Aftermind — a framework-neutral, persistent memory runtime for AI agents.

## Architecture (strict layering, depend downward only)

```
domain/        dataclasses + Protocol interfaces. No I/O, no framework deps.
core/          business logic. Depends only on domain/ interfaces, never on providers/.
providers/     concrete backends implementing domain/ Protocols (sqlite, graphiti/neo4j,
               openknowledge, llm/openrouter, inmemory fakes).
apps/api/      composition root: FastAPI REST + MCP server. Wires providers into core/facade.py.
integrations/  framework adapters (hermes, langgraph, crewai, autogen).
sdk/           client libraries (python, typescript).
```

Rules:
- `domain/` has zero imports from `core/`/`providers/`/`apps/`.
- `core/` only imports `domain/` interfaces (Protocols), never a concrete provider.
- New backend = new folder under `providers/` implementing the relevant `domain/interfaces/*.py` Protocol. Don't add backend-specific branches into `core/`.
- Domain models are `@dataclass(frozen=True)`; dict fields use `MappingProxyType`, list fields use `tuple`, enforced in `__post_init__`. Keep new models consistent.

## Scope discipline (important, easy to get wrong)

`domain/models/scope.py::MemoryScope` has a hierarchy: tenant_id, workspace_id, project_id, repository_id, user_id, agent_id, task_id, conversation_id, session_id, run_id.

Anything meant to persist **across sessions** (memories, checkpoints) MUST be stored/queried using `scope.stable()`, which strips execution-identity levels (conversation_id, session_id, run_id, parent_run_id). Using the full scope for durable storage is the classic bug here — it silently makes nothing persist across sessions. Check this first if recall/checkpoint "doesn't remember."

## Environment setup

```bash
python3 -m venv .venv          # system Python is externally-managed (Homebrew); use project venv
.venv/bin/pip install -e ".[dev]"   # or requirements files if present
cp .env.example .env           # fill in real values, never commit .env
```

`.env` keys: `LLM_API_KEY`, `LLM_MODEL`, `LLM_BASE_URL` (OpenRouter-compatible), `DATABASE_PATH`, `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`, `NEO4J_TIMEOUT_SECONDS`, `OPENKNOWLEDGE_URL`, plus the `AFTERMIND_*` reliability/logging knobs documented in `.env.example`. All of them are read in exactly one place: `apps/api/settings.py::Settings.from_env()` — never `os.environ` elsewhere in `apps/`.

## Reliability rules (SQLite canonical, outbox for the rest)

- `core/facade.py::observe()` commits memory + lifecycle + decision + checkpoint + `sync_jobs` rows in one `UnitOfWork` transaction (`SqliteClient.transaction()`), then flushes the jobs through `core/sync/dispatcher.py`.
- Anything that writes to Neo4j or OpenKnowledge from the observe path MUST go through a `SyncJob` kind (`domain/enums/sync_job_kind.py`) with a handler in the facade — never a direct call, or an outage becomes a failed observe. Handlers reload the memory by id (payloads carry ids, not content) and must be idempotent (retries re-run them).
- Graph/document *reads* in recall degrade (trace field `graph_search=failed` / `openknowledge_search=failed`), they never raise out of `recall()`.
- Every public facade operation runs inside `tracer.begin(...)`; record new per-store outcomes with the existing `ok|pending|failed|skipped` vocabulary (`core/observability/trace.py`) so `/observe` responses and `/traces` stay uniform.
- Crash recovery: `SyncWorker.recover()` requeues jobs left `running`; `tests/integration/test_crash_recovery.py` is the gate for "write → kill → restart → sync resumes". Extend it when adding a job kind.
- Neo4j clients are built with fail-fast timeouts (`providers/graphiti/client.py::driver_config`); don't construct a bare `GraphDatabase.driver(...)` elsewhere.

## Running tests

```bash
.venv/bin/python -m pytest tests/ -q --ignore=tests/integration/test_full_memory_loop_live.py
```

The excluded test hits a real LLM and is a known pre-existing flake against live model output — not part of the standard gate. Run the full suite (currently 397 tests) before every commit.

## Running the server

```bash
.venv/bin/python -m uvicorn apps.api.main:app --host 0.0.0.0 --port 8000
```

Or `aftermind serve` / `aftermind worker` / `aftermind sync status` after `pip install -e .` (see `apps/cli.py`).

MCP is mounted at `/mcp/` (trailing slash matters — bare `/mcp` 307-redirects). REST endpoints: `/observe`, `/recall`, `/checkpoint`, `/checkpoint/latest`, `/checkpoint/from-text`, `/search`, `/consolidate`, `/maintenance/sweep`, `/maintenance/sync` (+ `/run`, `/retry`), `/traces`, `/traces/{id}`, `/config`, `/health` (liveness), `/health/ready` (readiness + sync backlog).

## Real infra used for verification (prefer real over fakes when available)

- SQLite: local file (`DATABASE_PATH`).
- Neo4j/Graphiti: Docker container `aftermind-neo4j` (bolt://localhost:7687).
- OpenKnowledge: a running OpenKnowledge server (`OPENKNOWLEDGE_URL`).
- LLM: OpenRouter via `providers/llm/openrouter.py`.
- Hermes: real `hermes` CLI, `hermes -z "<prompt>"` for one-shot non-interactive live checks.

Policy: verify against real infrastructure whenever it's available; use fakes/in-memory stores only where real infra isn't available or isn't the point of the test (unit tests). Never guess an external API or hook contract — read the installed package source or its real docs (e.g. OpenKnowledge's REST routes were found by reading the installed `@inkeep/open-knowledge` npm package, not guessed; Hermes hook names/params were taken from `~/.hermes/hermes-agent/website/docs`, and where those docs disagreed with each other, code was written defensively rather than assuming one was right).

## Hermes plugin (integrations/hermes/hermes_plugin/)

Install by symlinking:
```bash
ln -s /path/to/agent-memory/integrations/hermes/hermes_plugin ~/.hermes/plugins/aftermind
```
and adding `"aftermind"` to `plugins.enabled` in `~/.hermes/config.yaml`. Test live with `hermes -z "<prompt>"`.

Known non-bugs seen during live testing, don't re-litigate these:
- A `hermes -z` call that appears to hang can just be slow real-LLM latency stacking (observe fires multiple background LLM calls per turn) plus Hermes' own agentic tool use in that turn.
- Hermes has its own native, unscoped session-recall tool; it can make answers look identical across different project scopes even when Aftermind's own scope isolation is correct. Verify scope isolation by inspecting the DB directly (distinct `memory_id`s per scope), not by trusting Hermes' spoken answer.

Deferred, not a bug: `user_correction` and `confirmed_decision` event types aren't auto-detected from Hermes activity (no dedicated hooks exist for them).

## Git conventions (enforced, don't deviate)

- Never commit unless explicitly asked ("commit it", "commit changes", etc.).
- Run the full test suite before every commit.
- No AI/Claude attribution in commit messages or PRs — no `Co-Authored-By: Claude ...` line.
- Push only when explicitly asked, even right after a commit.
