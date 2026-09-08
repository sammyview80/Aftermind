"""Deterministic MemoryScope derivation for Claude Code hooks — same
technique as integrations/hermes/hermes_plugin's _derive_scope: the git
repo root's basename, not a fixed env var, so opening Aftermind's own
repo vs. some other repo in Claude Code never shares a scope. Kept
independent of the Hermes plugin (no shared base module) so each
framework adapter stays self-contained and can evolve on its own.
"""
import os
import subprocess

DEFAULT_TENANT = "default"


def _git_root(cwd: str) -> str | None:
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


def derive_scope(cwd: str | None = None, session_id: str | None = None) -> dict:
    """Deterministic scope from the git repo root Claude Code is running
    in. Explicit env-var overrides win.

    `agent_id` is deliberately left unset by default (not "claude_code")
    — MemoryScope keys on every level it's given, so a per-framework
    agent_id would silently wall Claude Code's memories off from
    Hermes's (and vice versa) even inside the same project. Durable
    project/repo-level memory is meant to be framework-agnostic;
    agent_id is for isolating individual agents *within* a framework —
    an opt-in via AFTERMIND_SCOPE_AGENT, not a per-adapter default.
    integrations/hermes/hermes_plugin's _derive_scope follows the same
    rule for the same reason — see the milestone's cross-framework
    acceptance test (Hermes writes, Claude Code recalls)."""
    cwd = cwd or os.getcwd()
    project_root = _git_root(cwd) or cwd

    scope = {
        "tenant_id": os.environ.get("AFTERMIND_SCOPE_TENANT", DEFAULT_TENANT),
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
