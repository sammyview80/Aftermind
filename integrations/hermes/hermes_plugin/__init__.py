"""Hermes plugin: recall Aftermind memory before each turn, observe
activity after each turn/tool call, checkpoint on session end/reset/
finalize.

Install: drop (or symlink) this directory at ~/.hermes/plugins/aftermind/,
then add "aftermind" to plugins.enabled in ~/.hermes/config.yaml.

Milestone 1: pre_llm_call -> recall -> inject context.
Milestone 2: post_llm_call/post_tool_call -> observe.
Milestone 3: on_session_end/finalize/reset -> checkpoint_from_text, plus
deterministic scope derived from the git repo root instead of a fixed
env-var project name, so Aftermind's own repo and some other repo never
share a scope just because both are opened under the same Hermes profile.

Config (env vars, all optional — explicit values always win over
derived ones):
    AFTERMIND_URL              REST base URL (default http://localhost:8000)
    AFTERMIND_SCOPE_TENANT     scope tenant_id (default "hermes")
    AFTERMIND_SCOPE_AGENT      scope agent_id (default "hermes")
    AFTERMIND_SCOPE_PROJECT    overrides the derived project_id
    AFTERMIND_SCOPE_REPOSITORY overrides the derived repository_id
    AFTERMIND_RECALL_TIMEOUT   seconds (default 3)
    AFTERMIND_RECALL_LIMIT     max memories per recall (default 5)
    AFTERMIND_OBSERVE_TIMEOUT  seconds (default 10 — reconciliation
                                calls an LLM, slower than recall)
    AFTERMIND_CHECKPOINT_TIMEOUT seconds (default 15 — checkpoint
                                summarization also calls an LLM)
    AFTERMIND_TOOL_RESULT_MAX_CHARS truncation for tool result text
                                (default 500)
"""
import os
import subprocess
import threading

import httpx

DEFAULT_URL = "http://localhost:8000"
DEFAULT_RECALL_TIMEOUT = 3.0
DEFAULT_RECALL_LIMIT = 5
DEFAULT_OBSERVE_TIMEOUT = 10.0
DEFAULT_CHECKPOINT_TIMEOUT = 15.0
DEFAULT_TOOL_RESULT_MAX_CHARS = 500

# A single process (one Hermes CLI invocation) has one active conversation
# at a time — no need for a session_id-keyed dict. Guarded by a lock since
# observe_turn (main thread) and the flush hooks can run concurrently with
# the daemon threads observe_async spawns.
_last_turn_lock = threading.Lock()
_last_turn: dict = {"session_id": None, "text": None}


def _git_root(cwd: str) -> str | None:
    """The repo root for `cwd`, or None outside a git repo. subprocess,
    not a git library, to avoid adding a dependency to a Hermes plugin."""
    try:
        result = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=2,
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _derive_scope(session_id: str | None = None) -> dict:
    """Deterministic scope from the git repo root Hermes is running in —
    not a fixed env-var project name — so opening Aftermind's repo vs.
    some other repo under the same Hermes profile never shares a scope.
    Explicit env-var overrides always win, for cases with no git repo or
    where the derived name isn't what's wanted.

    `tenant_id` defaults to "default" (not "hermes") and `agent_id` is
    left unset by default (not "hermes") — MemoryScope keys on every
    level it's given, so framework-named defaults here would silently
    wall Hermes's memories off from any other framework adapter (e.g.
    Claude Code's) even for the same project. Durable project/repo
    memory is meant to be shared across whichever agent/framework wrote
    it; agent_id is for isolating individual agents *within* one
    framework, an opt-in via AFTERMIND_SCOPE_AGENT. See
    integrations/claude_code/scope_mapper.py, which follows the same
    rule for the same reason, and the cross-framework acceptance test
    (Hermes writes, Claude Code recalls)."""
    cwd = os.getcwd()
    project_root = _git_root(cwd) or cwd

    scope = {
        "tenant_id": os.environ.get("AFTERMIND_SCOPE_TENANT", "default"),
        "project_id": os.environ.get("AFTERMIND_SCOPE_PROJECT")
        or os.path.basename(project_root.rstrip("/"))
        or "default",
        "repository_id": os.environ.get("AFTERMIND_SCOPE_REPOSITORY") or project_root,
    }
    agent_id = os.environ.get("AFTERMIND_SCOPE_AGENT")
    if agent_id:
        scope["agent_id"] = agent_id
    if session_id:
        scope["session_id"] = session_id
    return scope


def _base_url() -> str:
    return os.environ.get("AFTERMIND_URL", DEFAULT_URL).rstrip("/")


def recall(session_id: str, user_message: str, is_first_turn: bool, **kwargs) -> dict | str | None:
    """pre_llm_call callback: fetch Aftermind's recall context for this
    turn's message and inject it. Best-effort — any failure (Aftermind
    down, network issue, bad response) returns None rather than blocking
    or breaking the user's turn, same contract as Hermes' own documented
    memory-recall example.
    """
    if not user_message or not user_message.strip():
        return None

    timeout = float(os.environ.get("AFTERMIND_RECALL_TIMEOUT", DEFAULT_RECALL_TIMEOUT))
    limit = int(os.environ.get("AFTERMIND_RECALL_LIMIT", DEFAULT_RECALL_LIMIT))

    try:
        response = httpx.post(
            f"{_base_url()}/recall",
            json={"scope": {"levels": _derive_scope(session_id)}, "text": user_message, "limit": limit},
            timeout=timeout,
        )
        response.raise_for_status()
        context = response.json().get("context", "")
    except Exception:
        return None

    if not context.strip():
        return None

    return {"context": f"[Aftermind memory]\n{context}"}


def observe(text: str, event_type: str, session_id: str | None = None) -> None:
    """POST one piece of activity to Aftermind's /observe. Synchronous —
    callers that don't want to block a turn should run this in a thread
    (see observe_async). Swallows all errors: an unreachable Aftermind
    server must never break a Hermes turn."""
    if not text or not text.strip():
        return

    timeout = float(os.environ.get("AFTERMIND_OBSERVE_TIMEOUT", DEFAULT_OBSERVE_TIMEOUT))
    try:
        httpx.post(
            f"{_base_url()}/observe",
            json={"scope": {"levels": _derive_scope(session_id)}, "output": text, "event_type": event_type},
            timeout=timeout,
        )
    except Exception:
        pass


def observe_async(text: str, event_type: str, session_id: str | None = None) -> None:
    """Fire-and-forget observe() in a daemon thread. Reconciliation calls
    an LLM and can take a few seconds — never let that add latency to a
    Hermes turn, matching the non-blocking contract Hermes documents for
    its own memory-provider sync_turn()."""
    threading.Thread(target=observe, args=(text, event_type, session_id), daemon=True).start()


def observe_turn(session_id: str, user_message: str, assistant_response: str, **kwargs) -> None:
    """post_llm_call callback: capture the user's message and the
    assistant's response as two separate observations — a trivial
    exchange on either side is filtered out downstream by Aftermind's
    own candidate extractor, not guessed at here. Also remembers this
    turn's text so a session-end/finalize/reset hook can checkpoint it."""
    observe_async(user_message, "user_message", session_id)
    observe_async(assistant_response, "agent_message", session_id)

    with _last_turn_lock:
        _last_turn["session_id"] = session_id
        _last_turn["text"] = f"User: {user_message}\nAssistant: {assistant_response}"


def observe_tool_result(**kwargs) -> None:
    """post_tool_call callback. Hermes' own docs disagree on whether the
    arguments dict is passed as `params` (plugins.md's minimal example)
    or `args` (the hooks.md catalog table) — read everything from
    **kwargs instead of declaring named parameters, so a naming mismatch
    can't turn into a silently-skipped TypeError (per Hermes' own rule:
    callback exceptions are logged and skipped, not raised).
    Truncated to avoid flooding Aftermind with large tool output."""
    tool_name = kwargs.get("tool_name", "unknown_tool")
    status = kwargs.get("status")
    result = kwargs.get("result")
    session_id = kwargs.get("session_id")

    max_chars = int(os.environ.get("AFTERMIND_TOOL_RESULT_MAX_CHARS", DEFAULT_TOOL_RESULT_MAX_CHARS))
    text = str(result)[:max_chars]

    event_type = "tool_failed" if status == "error" else "tool_completed"
    observe_async(f"Tool {tool_name} result: {text}", event_type, session_id)


def _checkpoint_from_pending(reason: str, session_id: str | None = None) -> None:
    """POST whatever the last observed turn was to /checkpoint/from-text,
    then clear it — so a session_end immediately followed by finalize/
    reset for the same teardown doesn't double-checkpoint identical
    content. A no-op if nothing has been observed yet (e.g. a session
    that ended before any turn completed)."""
    with _last_turn_lock:
        text = _last_turn["text"]
        pending_session_id = _last_turn["session_id"]
        _last_turn["text"] = None

    if not text:
        return

    timeout = float(os.environ.get("AFTERMIND_CHECKPOINT_TIMEOUT", DEFAULT_CHECKPOINT_TIMEOUT))

    def _post():
        try:
            httpx.post(
                f"{_base_url()}/checkpoint/from-text",
                json={
                    "scope": {"levels": _derive_scope(session_id or pending_session_id)},
                    "text": text,
                    "reason": reason,
                },
                timeout=timeout,
            )
        except Exception:
            pass

    threading.Thread(target=_post, daemon=True).start()


def on_session_end(session_id: str | None = None, **kwargs) -> None:
    _checkpoint_from_pending("session_end", session_id)


def on_session_finalize(session_id: str | None = None, **kwargs) -> None:
    _checkpoint_from_pending("session_finalize", session_id)


def on_session_reset(session_id: str | None = None, **kwargs) -> None:
    _checkpoint_from_pending("session_reset", session_id)


def register(ctx) -> None:
    ctx.register_hook("pre_llm_call", recall)
    ctx.register_hook("post_llm_call", observe_turn)
    ctx.register_hook("post_tool_call", observe_tool_result)
    ctx.register_hook("on_session_end", on_session_end)
    ctx.register_hook("on_session_finalize", on_session_finalize)
    ctx.register_hook("on_session_reset", on_session_reset)
