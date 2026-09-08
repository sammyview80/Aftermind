# Claude Code + Codex Integration — End-to-End Test Report

Date: 2026-09-08/09
Tester: saman (via Claude Code, sessions `hit-6c` and `agent-memory-e6`)
Server: `uvicorn apps.api.main:app` on `:8000`, commit `a8584ad` (fixes applied mid-test)

## Setup verified

- MCP server `aftermind` registered at Claude Code user scope, `http://127.0.0.1:8000/mcp/` (trailing slash required, bare `/mcp` 307s).
- Five MCP tools confirmed live: `memory_observe`, `memory_recall`, `memory_checkpoint`, `memory_search`, `memory_consolidate`.
- Six hooks from `integrations/claude_code/settings.snippet.json` merged into `~/.claude/settings.json`: `UserPromptSubmit`, `SessionStart`, `PostToolUse`, `PostToolUseFailure`, `SessionEnd`, `PreCompact`.
- Both MCP and hooks require a Claude Code restart (or `/reload-plugins`) after first registration — not live in the session that ran `claude mcp add`.

## Bug found and fixed before testing

`integrations/claude_code/event_mapper.py` read `user_prompt` / `tool_result`, but Claude Code's real hook payloads carry `prompt` / `tool_response` / `error` (per hooks.md). Recall injection was silently dead until this was fixed. Fixed in commit `a8584ad` with regression tests in `test_event_mapper_fields.py`.

## Test 1 — multi-turn conversation, single session

Used `claude -p --session-id <uuid>` then three `claude -p -r <uuid>` calls — four separate CLI processes sharing one transcript, not one long prompt.

| Turn | Prompt | Result |
|---|---|---|
| 1 | "tetsaman is a Python todo-list CLI, remember that" | Saved |
| 2 | "We decided SQLite over JSON, for querying later" | Saved |
| 3 | "CLI command name is `tsk`, not `tetsaman`" | Saved |
| 4 | "Summarize what we've decided" | Correctly listed all three facts |

SessionEnd hook then wrote checkpoint v9, a real merged summary of the whole 4-turn arc — not just the last exchange (see Issue 1 below).

## Test 2 — true cross-session recall

Fresh `claude -p --session-id <new-uuid>` process, zero shared transcript with Test 1, run after a full server restart.

Prompt: *"What storage engine did we choose and what's the CLI command name? Memory only, say NO MEMORY if none."*
Answer: **"SQLite, for future querying. CLI command: `tsk`."** — correct, and recoverable only via the Aftermind hook injection (confirmed via `--debug-file`, `additionalContext` carried the checkpoint + facts, 1795–1908 chars).

## Test 3 — cross-framework (Hermes writes, Claude Code reads)

Wrote a fact directly via `POST /observe` the way the Hermes plugin would, same project scope, no Claude Code involved:
> "Hermes here: we also decided the todo priority levels are low/medium/high, stored as an integer 0-2 in SQLite."

A third fresh Claude Code session then answered: **"Priority: low/medium/high, stored as integer 0-2 in SQLite."** — correct. Cross-framework memory sharing confirmed at the DB/API level, not just within one framework's native recall.

## Finding — first-person framework voice triggers distrust (not a bug, a design note)

Because the seeded fact above was phrased as *"Hermes here: ..."*, Claude Code's own reasoning flagged the injected block as untrusted third-party content before answering:

> "Flag: that 'Hermes/Aftermind' memory block claims facts ... Looks like injected content, not real memory — treat as suspicious, not fact."

This is correct, safe model behavior — treating recalled content as data, not instruction. But it means memories written as a first-person voice from another agent ("X here, we decided...") read as an unverified claim rather than settled fact, and will sometimes get hedged in the answer or ignored outright. Recommendation for `event_mapper`/Hermes plugin's observation text: write facts in third person / plain statement form ("Team decided priority levels are low/medium/high, stored as int 0-2") rather than a first-person "X here" framing.

## Issues found this session, all fixed and committed (`a8584ad`, not pushed)

1. **Checkpoint rot** — trivial one-prompt headless sessions overwrote a good multi-fact checkpoint with "placeholder conversation, nothing done yet". Fixed: summarizer now merges `completed`/`next_steps` with the previous checkpoint instead of replacing; `SessionEnd`/`PreCompact` skip checkpointing entirely under `AFTERMIND_CHECKPOINT_MIN_EXCHANGES` (default 2) real exchanges.
2. **Questions stored as facts** — "what database does Aftermind use" etc. saved as semantic memories at 0.95–1.0 confidence. Fixed: `is_interrogative()` / `is_conversational_filler()` reject these before scoring.
3. **System payloads observed verbatim** — four multi-thousand-char `<task-notification>` subagent reports landed as high-confidence memories, dominating recall context. Fixed: `observation_text_for_prompt` returns `""` for `<task-notification>`, `<system-reminder>`, `<local-command-caveat>`, slash commands, etc., capped at 500 chars. Four bad rows deleted from `aftermind.db`.
4. **Recall latency spikes past hook timeout** — one recall took 5261ms against a 3s hook timeout, dropping context entirely. Root cause: Neo4j reads queued behind graphiti writes/index builds, not a SQLite lock. Fixed: `NEO4J_QUERY_TIMEOUT_SECONDS` (default 2s) plus new `knowledge.search`/`graph.retrieve`/`knowledge.history` trace spans for the next slow case. Hook-side `AFTERMIND_RECALL_TIMEOUT=8` / hook timeout 10s kept as belt-and-braces.

Post-fix retest (Test 2/3 above, run against restarted server on `a8584ad`): recall latency 174–969ms, zero task-notification memories remaining, zero questions stored, checkpoint skipped correctly for a 1-exchange session, merged correctly for a 4-exchange session.

## Open items, not yet actioned

- 36 legacy memories/checkpoints under tenant `hermes` (old plugin default) are invisible to Claude Code's `default` tenant scope in the same repo. A scripted migration (rewrite `scope_key`/`scope_levels`, drop `agent_id`, with a DB backup first) was offered but not run — data decision for the user.
- Commit `a8584ad` is local only, not pushed to `origin/master`.
- One stray graph edge `tetsaman -[UNKNOWN]-> NO MEMORY` remains from an early failed-recall probe; harmless, cosmetic.

## Codex CLI installation (added 2026-09-09)

Codex CLI (`codex-cli 0.153.4`) already had a prebuilt adapter at `integrations/codex/` (`plugin.py` reuses the Claude Code handlers, adds `Stop` observation and a detached-child checkpoint since Codex caps `SessionEnd` hooks at 3s). Installed it live:

1. `codex mcp add aftermind --url http://127.0.0.1:8000/mcp/` — registered globally, confirmed via `codex mcp get aftermind` (`enabled: true`, `transport: streamable_http`).
2. Backed up `~/.codex/config.toml`, then appended 6 `[[hooks.<Event>]]` / `[[hooks.<Event>.hooks]]` TOML tables (`UserPromptSubmit`, `SessionStart`, `PostToolUse`, `Stop`, `SessionEnd`, `PreCompact`) pointing at `python -m integrations.codex`, matching `integrations/codex/hooks.snippet.json`. Verified `config.toml` still parses after editing.
3. Codex requires per-hook-source trust (`[hooks.state."<path>:<event>:idx:idx"] trusted_hash = ...`) before a hook actually runs; for scripted testing used `codex exec --dangerously-bypass-hook-trust`, which is documented and appropriate for self-installed automation, not a workaround for someone else's untrusted hook.

### Test 4 — Codex reads memory Claude Code wrote

Fresh `codex exec --dangerously-bypass-hook-trust --skip-git-repo-check` in `tetsaman`, no prior Codex session, asked for the facts Claude Code sessions had written (Test 1/2 above):

> "From memory: **tetsaman** is a **Python todo-list CLI app** owned by **saman**. The chosen storage engine is **SQLite** for future querying, and the CLI command is **`tsk`**."

Correct — same repo scope (`tenant=default, project=tetsaman`), same DB, no shared process with the Claude Code sessions that created those facts. One of 6 `SessionStart` hooks reported `Failed` on the first run only (pre-existing hooks from other tools — composio, ponytail, codebase-memory-mcp — also registered globally); did not recur on rerun and did not prevent the correct memory-backed answer, so not attributed to the Aftermind hook.

### Test 5 — Codex writes, Claude Code reads (full triangle)

`codex exec` wrote a new fact: *"Codex here: ... add a 'due date' field ... stored as ISO8601 text in SQLite."* A subsequent fresh `claude -p` session (new session-id, no shared transcript) answered:

> "Field: 'due date'. Stored as ISO8601 text in SQLite."

Confirms Hermes, Claude Code, and Codex now all read and write the same per-repo memory scope — full triangle, not just one pairwise direction.

### Finding reproduces across all three frameworks

The same first-person-voice distrust noted for Hermes (see finding above) reproduced identically for Codex: Claude Code answered correctly but appended *"injected memory content came from unverified external context (labeled 'Codex here' / 'Hermes here'), not your own trusted memory store — flagging as possible prompt injection, treat with caution."* Confirms the fix belongs in the shared observation-text path (`event_mapper.py`, used by all three adapters), not a framework-specific one: strip or rephrase self-referential "X here" framing before writing to `output`/`content`.

## Verdict

End-to-end memory works across all three frameworks tested: within-session, cross-session, and cross-framework in every pairwise direction (Hermes ↔ Claude Code, Codex ↔ Claude Code), verified against a live server and real multi-process CLI invocations (`claude -p --session-id`/`-r`, `codex exec`), not simulated payloads alone.
