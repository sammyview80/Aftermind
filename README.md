# Aftermind

Persistent, framework-neutral memory for AI coding agents. Aftermind sits beside Claude Code, Codex and Hermes, watches what they do, and hands them back the right context next time: what you decided, what changed, where you left off.

> **License note:** Aftermind is source-available under the **PolyForm Noncommercial License 1.0.0** (see `LICENSE`). Not for commercial use. Personal, research, educational and charitable/public-organization use is permitted.

## Why Aftermind

Every agent runtime ships some memory: a transcript summary, a `MEMORY.md`, a per-tool notes file. They all share the same failure modes. Aftermind exists to fix those specifically.

| Problem with built-in agent memory | What Aftermind does instead |
|---|---|
| Memory is per tool. Claude Code doesn't know what Codex learned this morning. | One store, shared scope. A fact learned under Hermes is recalled by Claude Code in the same repo. Scope is derived from the git root, not from the tool. |
| Memory is a flat file the model appends to. Contradictions pile up. | An LLM **reconciles** every candidate against existing memories: create, update, merge, supersede or ignore. Superseded facts stay queryable as history, never silently overwritten. |
| Questions, chit-chat and tool noise get stored as "facts". | An explicit **admission policy** (`docs/memory-policy.md`): a deterministic gate rejects questions, directives, greetings, narration, tool output, code, markup and secrets on every adapter; an LLM stage then extracts atomic third-person facts and scores usefulness before anything is stored. `aftermind memory audit` shows what the policy would reject in what you already have. |
| "Where did I leave off" is lost at context compaction or session end. | **Checkpoints** (goal / completed / current / blockers / next) are written on session end and pre-compaction, merged into the previous one so a trivial session can't erase real progress. |
| Related facts are recalled one at a time. | Hybrid recall fuses SQLite memories, a Neo4j relationship graph, consolidated OpenKnowledge documents and the latest checkpoint into one ranked, compact context block. |
| Memory never forgets, so it drifts and bloats. | Lifecycle management: reinforcement on access, decay on disuse, archival of stale never-used memories. Never deletion. |
| Secondary stores fail and memory silently disappears. | SQLite is canonical. Graph and document writes go through a **transactional outbox** with retry; an outage leaves a `pending` job, never a lost memory. Every operation is traced. |

## Quick start (one command)

Requirements: Python 3.11+, Docker (for Neo4j; optional), Node 24+ with `npm i -g @inkeep/open-knowledge` (for OpenKnowledge; optional). Without Docker the graph falls back to in-memory; without `ok` documents go to a local markdown directory. Both fallbacks are printed, never silent.

```bash
git clone https://github.com/sammyview80/Aftermind.git && cd Aftermind
./scripts/setup.sh                # venv, install, .env, Neo4j, OpenKnowledge, SQLite, API (background)
```

On first run it asks which LLM to use for reconciliation, and offers what is already on your machine instead of asking for a new key:

```
Found credentials on this machine:
  → 1. Codex CLI login (ChatGPT: you@example.com)      ~/.codex/auth.json
    2. Claude Code login (Claude subscription)         macOS Keychain
    3. OpenRouter API key                              ~/.hermes/.env OPENROUTER_API_KEY
    4. Enter a new API key (any OpenAI-compatible endpoint)
    5. Skip for now (recall works, observe() will not learn)
```

Pick one, pick a model (the Codex option shows your account's live catalog), and it runs a one-line test call before saving `LLM_PROVIDER` / `LLM_MODEL` to `.env`. Re-run any time with `aftermind init`, or non-interactively: `aftermind init --provider codex_oauth --model gpt-5.5`, or `aftermind init -y` to take the first detected login. OAuth tokens are read from the other tool's files and refreshed into `~/.aftermind/credentials.json`; Aftermind never writes into `~/.codex` or `~/.claude`.

Recall works without any LLM; learning (`observe`) needs one.

```bash
.venv/bin/aftermind status        # what is running, /health/ready
.venv/bin/aftermind down          # stop API, OpenKnowledge and the Neo4j container
```

`aftermind up` is idempotent: it reuses the venv, the `aftermind-neo4j` container (and syncs `.env` to the container's real password), the OpenKnowledge project under `.aftermind/openknowledge/`, and your existing `.env`.

## Connect an agent

One command per runtime. Each registers Aftermind's MCP server and installs lifecycle hooks (recall before the model reasons, observe after tool calls, checkpoint on session end / pre-compaction). All edits are idempotent and back up the file they touch.

```bash
.venv/bin/aftermind connect claude-code   # ~/.claude/settings.json hooks + `claude mcp add` (user scope)
.venv/bin/aftermind connect codex         # ~/.codex/hooks.json hooks + `codex mcp add`
.venv/bin/aftermind connect hermes        # ~/.hermes/plugins/aftermind symlink + config.yaml
.venv/bin/aftermind connect all
```

Restart the agent afterwards. From then on:

- **Claude Code** and **Codex**: every prompt gets an `[Aftermind memory]` block injected (checkpoint, current facts, history, relationships, company knowledge). Your prompts and the agent's replies/tool results are observed asynchronously; the session is checkpointed on end and before compaction. The `aftermind` MCP server also exposes `memory_recall`, `memory_observe`, `memory_checkpoint`, `memory_search`, `memory_consolidate` for explicit use.
- **Hermes**: the plugin does the same through Hermes' hook API (`pre_llm_call`, `post_llm_call`, `post_tool_call`, session end/finalize/reset).

All three write into the same scope for the same repository, so knowledge moves between tools. Override scope with `AFTERMIND_SCOPE_TENANT`, `AFTERMIND_SCOPE_PROJECT`, `AFTERMIND_SCOPE_REPOSITORY`, `AFTERMIND_SCOPE_AGENT` in the hook environment if you want isolation.

Or `./scripts/setup.sh --connect all` to do everything in one go.

## Using it directly

```bash
curl -s localhost:8000/observe -H 'content-type: application/json' \
  -d '{"scope":{"levels":{"project_id":"billing"}},"output":"We decided the billing worker uses RabbitMQ."}'
# -> {"created":true, "observe_id":"…", "reconciliation_action":"create",
#     "sync":{"sqlite_write":"ok","neo4j_sync":"ok","openknowledge_sync":"ok"}}

curl -s localhost:8000/recall -H 'content-type: application/json' \
  -d '{"scope":{"levels":{"project_id":"billing"}},"text":"what does billing use for messaging?"}'
# -> {"context":"## Current facts\n- We decided the billing worker uses RabbitMQ. …", "recall_sources":["sqlite","graph"], …}
```

REST: `/observe`, `/recall`, `/search`, `/checkpoint`, `/checkpoint/latest`, `/checkpoint/from-text`, `/consolidate`, `/maintenance/sweep`, `/maintenance/sync`, `/traces`, `/config`, `/health`, `/health/ready`. MCP at `/mcp/`. Python SDK in `sdk/python`.

## Operating it

```bash
aftermind init             # choose/switch the LLM (reuse Codex, Claude Code, OpenRouter logins)
aftermind serve            # API + in-process sync worker (what `up` runs)
aftermind worker           # outbox sync worker as its own process
aftermind sync status      # graph/document sync backlog; `sync run`, `sync retry [ID]`
aftermind backup DEST      # consistent SQLite snapshot
aftermind check            # SQLite integrity
aftermind config           # effective configuration, secrets redacted
```

Every operation emits one structured trace (`aftermind.trace` logger; `GET /traces`, `GET /traces/{id}`) with `observe_id`, scope, `candidate_count`, `reconciliation_action`, `sqlite_write`, `neo4j_sync`, `openknowledge_sync`, `checkpoint_created`, `recall_sources`, `llm_calls`, `llm_latency_ms`, latency and per-stage spans. Set `AFTERMIND_LOG_FORMAT=json` for log shippers.

Docker: `docker compose up -d` runs the API and Neo4j as containers (`docker-compose.yml`, `Dockerfile`).

## Reliability model

```
observe()
  extract -> evaluate -> reconcile (LLM)            no locks held
  SQLite transaction
  ├─ memory + lifecycle + decision + checkpoint
  └─ sync jobs (graph_sync, knowledge_consolidate, …)
  commit
  flush jobs   eager: try now; failure -> job pending with backoff
               background: leave for the worker
sync worker    retries (1s..5min), resumes after crash, dead after N attempts
```

Reads degrade the same way: recall still returns SQLite memories when Neo4j or OpenKnowledge is down, and says so in the trace. Neo4j calls carry fail-fast timeouts so an outage costs seconds, not minutes.

## Architecture

```
domain/        models + Protocol interfaces, no I/O
core/          business logic (formation, reconciliation, recall, checkpoints,
               consolidation, lifecycle, sync outbox, observability)
providers/     sqlite (canonical), graphiti/neo4j, openknowledge, llm, inmemory
apps/api/      FastAPI REST + MCP; apps/cli.py; apps/setup (up/down/connect)
integrations/  claude_code, codex, hermes adapters
sdk/           client libraries
```

See `AGENTS.md` for layering rules, scope discipline and the reliability rules contributors must keep.

## Development

```bash
./scripts/setup.sh --no-server
.venv/bin/python -m pytest tests/ -q --ignore=tests/integration/test_full_memory_loop_live.py
```

## Contributing

See `CONTRIBUTING.md` and `CODE_OF_CONDUCT.md`.

## License

PolyForm Noncommercial License 1.0.0. See `LICENSE`.
