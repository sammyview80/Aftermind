# Memory policy: what Aftermind stores, and what it never does

Aftermind keeps two very different records:

| Record | What goes in | Retention |
|---|---|---|
| **experiences** (raw log) | Every observation the adapters send: user prompts, assistant replies, tool results. Verbatim, scoped, timestamped. | Kept. This is history, not memory. Nothing is recalled from it directly. |
| **memories** (long-term) | Only statements that pass the admission policy below, after reconciliation against what is already known. | Lifecycle-managed: reinforced on use, decayed on disuse, archived when stale, superseded when contradicted. Never silently deleted. |

Checkpoints ("where did I leave off") are a third record, written on session end and pre-compaction, and are the right home for *tasks* and *progress*. Tasks are not memories.

## The admission pipeline

```
observation
  │
  ├─ 1. deterministic gate  (core/formation/admission.py, no LLM, every adapter)
  │      reject → stays in experiences, trace says admission=rejected:<reason>
  │
  ├─ 2. LLM admission       (AFTERMIND_ADMISSION_MODE=auto|llm, providers/llm/prompts/admission.md)
  │      one call: extract atomic third-person statements, score usefulness/durability,
  │      each proposal is gated again and held to AFTERMIND_MEMORY_MIN_SCORE
  │      (rules mode: gate-admitted text is the single candidate, rule-scored)
  │
  └─ 3. reconciliation      (LLM) create / update / merge / supersede / ignore
         against existing memories in the same scope
```

## Store

| Class | Example | Why |
|---|---|---|
| Decisions and rationale | "Billing uses RabbitMQ, chosen over Redis for durability." | The single most valuable thing a next session needs. |
| Project / system facts | "tetsaman is a Python todo-list CLI app owned by saman." | Stable, cross-session. |
| Requirements and constraints | "The API must stay Python 3.11 compatible." | Shapes future work. |
| Preferences and conventions | "The client prefers dark layouts." / "Commits use Conventional Commits." | Repeatedly relevant. |
| Corrections | "The CLI is `tsk`, not `tetsaman`." | Prevents the same mistake twice. Superseding the old fact keeps history. |
| Discoveries and root causes | "Neo4j reads stalled because graphiti rebuilt indexes on every write." | Hard-won, reusable. |
| Ownership and naming | "Saman owns the Aftermind repository." | Cheap to store, often needed. |
| Verified state of work | "Automatic checkpointing is committed (7c0865e) and verified live." | Bridges sessions; still a fact, not a task. |

## Never store

| Class | Example | Gate reason |
|---|---|---|
| Questions | "what database does Aftermind use" | `question` |
| Directives to the agent | "also commit and push", "restart the server", "test again and tell me" | `directive` |
| Greetings, thanks, filler | "hi", "say ok", "Hi Saman, how can I help you today?" | `greeting`, `filler` |
| Agent narration | "Let me check the repo.", "Done.", "Confirmed against the actual repo" | `narration` |
| Tool traffic | any `tool_started`/`tool_completed` event; "Tool read_file result: {…}" | `tool_output` |
| Code, logs, stack traces, diffs, listings | `def observe(...)`, `Traceback (most recent call last)` | `code_or_log` |
| Markup and machine payloads | `<task-notification>…`, `<cross-session-message …>`, JSON | `markup` |
| Bare URLs / paths | "/Volumes/SK/personal/aftermind" | `url_or_path_only` |
| **Secrets** | keys, tokens, JWTs, passwords, credentials in URLs | `secret` — also redacted before any LLM sees the text |
| Over-long or mixed text | a 2 KB assistant message; "…we chose RabbitMQ. Can you check the dashboard?" | admitted for LLM *extraction* only; never stored verbatim (`AFTERMIND_MAX_CANDIDATE_CHARS`). In `rules` mode (no LLM) such text is dropped as `rejected:needs_llm_extraction`. |
| Error output | `tool_failed` text | LLM may extract a root cause; raw error is never the memory |

Transient status ("build at 40%"), speculation, and duplicates are rejected by the LLM stage and the reconciler (`ignore`).

## Statement shape

A stored memory is one atomic, self-contained, third-person statement. The LLM stage rewrites toward that shape; the extractor also strips speaker framing ("Codex here:", "As Hermes,") so that a fact recalled into another agent's context reads as state, not as another agent's voice.

## Adapter-side filters

Hook adapters (Claude Code, Codex, Hermes) drop system payloads and slash commands before calling `observe`, cap prompt and tool text at 500 chars, and skip SessionEnd checkpoints for sessions with fewer than two real exchanges. These are convenience filters; the core gate is the authority and applies to REST and MCP callers too.

## Observability and tuning

Every `observe` trace and the `/observe` response carry `admission` (`llm`, `rules`, or `rejected:<reason>`), `candidate_count`, `reconciliation_action`, and `memory_ids`. To see what the current policy would do to what is already stored:

```bash
aftermind memory audit            # dry run: which stored memories the gate rejects today, by reason
aftermind memory audit --purge    # delete those rows (memories, lifecycle, sync jobs) after a DB backup
```

Knobs: `AFTERMIND_ADMISSION_MODE`, `AFTERMIND_MEMORY_MIN_SCORE`, `AFTERMIND_MAX_CANDIDATE_CHARS`. Golden keep/reject cases live in `tests/unit/core/formation/test_admission.py`; add a case there whenever a new class of junk shows up in `aftermind memory audit`.
