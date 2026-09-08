"""`aftermind connect <agent>`: wire Aftermind into an agent runtime.

    claude-code   register the HTTP MCP server (user scope) + merge the six
                  hooks into ~/.claude/settings.json
    codex         register the HTTP MCP server + merge hooks into
                  ~/.codex/hooks.json (Codex uses the same hook contract:
                  JSON on stdin, hookSpecificOutput.additionalContext on stdout)
    hermes        symlink the plugin into ~/.hermes/plugins/aftermind and
                  enable it (plus the MCP server) in ~/.hermes/config.yaml

Every edit is idempotent (re-running replaces our entries, never
duplicates them) and backs the file up first.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable, Optional

MCP_NAME = "aftermind"
DEFAULT_API_URL = "http://127.0.0.1:8000"
Log = Callable[[str], None]

# Hook events per runtime, with timeouts in the unit each runtime uses:
# Claude Code milliseconds, Codex seconds (and Codex caps SessionEnd at 3s,
# so the Codex adapter checkpoints in a detached child process).
CLAUDE_CODE_HOOKS = {
    "UserPromptSubmit": 5000,
    "SessionStart": 5000,
    "PostToolUse": 10000,
    "PostToolUseFailure": 10000,
    "SessionEnd": 15000,
    "PreCompact": 15000,
}
CODEX_HOOKS = {
    "UserPromptSubmit": 8,
    "SessionStart": 8,
    "PostToolUse": 10,
    "Stop": 10,
    "SessionEnd": 3,
    "PreCompact": 20,
}


def _log(message: str) -> None:
    print(message, file=sys.stderr)


def _backup(path: Path) -> Optional[Path]:
    if not path.exists():
        return None
    backup = path.with_name(f"{path.name}.bak-{time.strftime('%Y%m%d%H%M%S')}")
    shutil.copy(path, backup)
    return backup


def hook_command(repo_root: Path, module: str, python: Optional[str] = None) -> str:
    """The shell command a hook runs. It cd's into the repo so the
    integrations package imports regardless of the project the agent is
    in, and uses the repo's venv interpreter."""
    python = python or (".venv/bin/python" if (repo_root / ".venv/bin/python").exists() else sys.executable)
    return f"cd {repo_root} && {python} -m {module}"


def _is_ours(entry: dict, module: str) -> bool:
    return any(module in str(h.get("command", "")) for h in entry.get("hooks", []))


def merge_hooks(settings: dict, events: dict[str, int], command: str, module: str, matcher: Optional[str]) -> dict:
    """Replace our hook entries for each event (matched by the module
    name in the command) and leave everyone else's untouched."""
    hooks = settings.setdefault("hooks", {})
    for event, timeout in events.items():
        existing = [e for e in hooks.get(event, []) if not _is_ours(e, module)]
        entry: dict = {"hooks": [{"type": "command", "command": command, "timeout": timeout}]}
        if matcher is not None:
            entry["matcher"] = matcher
        hooks[event] = [*existing, entry]
    return settings


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    text = path.read_text().strip()
    return json.loads(text) if text else {}


def _run(command: list[str], log: Log) -> bool:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as exc:
        log(f"  failed to run {' '.join(command[:2])}: {exc}")
        return False
    if result.returncode != 0:
        log(f"  {' '.join(command[:3])} exited {result.returncode}: {(result.stderr or result.stdout).strip()[:300]}")
        return False
    return True


# ------------------------------------------------------------ claude code


def connect_claude_code(
    repo_root: Path,
    api_url: str = DEFAULT_API_URL,
    settings_path: Optional[Path] = None,
    register_mcp: bool = True,
    log: Log = _log,
) -> Path:
    settings_path = settings_path or Path.home() / ".claude" / "settings.json"
    mcp_url = f"{api_url.rstrip('/')}/mcp/"

    if register_mcp:
        if shutil.which("claude") is None:
            log("  `claude` CLI not found — register the MCP server manually: "
                f"claude mcp add --transport http -s user {MCP_NAME} {mcp_url}")
        else:
            subprocess.run(["claude", "mcp", "remove", "-s", "user", MCP_NAME], capture_output=True, text=True)
            if _run(["claude", "mcp", "add", "--transport", "http", "-s", "user", MCP_NAME, mcp_url], log):
                log(f"  MCP: registered {MCP_NAME} -> {mcp_url} (user scope)")

    settings = _load_json(settings_path)
    backup = _backup(settings_path)
    merge_hooks(
        settings,
        CLAUDE_CODE_HOOKS,
        hook_command(repo_root, "integrations.claude_code"),
        "integrations.claude_code",
        matcher=".*",
    )
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(settings, indent=2) + "\n")
    log(f"  hooks: {len(CLAUDE_CODE_HOOKS)} events merged into {settings_path}" + (f" (backup {backup.name})" if backup else ""))
    return settings_path


# ------------------------------------------------------------------ codex


def connect_codex(
    repo_root: Path,
    api_url: str = DEFAULT_API_URL,
    hooks_path: Optional[Path] = None,
    register_mcp: bool = True,
    log: Log = _log,
) -> Path:
    hooks_path = hooks_path or Path.home() / ".codex" / "hooks.json"
    mcp_url = f"{api_url.rstrip('/')}/mcp/"

    if register_mcp:
        if shutil.which("codex") is None:
            log(f"  `codex` CLI not found — register manually: codex mcp add {MCP_NAME} --url {mcp_url}")
        else:
            subprocess.run(["codex", "mcp", "remove", MCP_NAME], capture_output=True, text=True)
            if _run(["codex", "mcp", "add", MCP_NAME, "--url", mcp_url], log):
                log(f"  MCP: registered {MCP_NAME} -> {mcp_url}")

    settings = _load_json(hooks_path)
    backup = _backup(hooks_path)
    merge_hooks(
        settings,
        CODEX_HOOKS,
        hook_command(repo_root, "integrations.codex"),
        "integrations.codex",
        matcher=None,  # Codex hook entries carry no matcher for these events
    )
    hooks_path.parent.mkdir(parents=True, exist_ok=True)
    hooks_path.write_text(json.dumps(settings, indent=2) + "\n")
    log(f"  hooks: {len(CODEX_HOOKS)} events merged into {hooks_path}" + (f" (backup {backup.name})" if backup else ""))
    return hooks_path


# ----------------------------------------------------------------- hermes


def _ensure_yaml_list_item(text: str, parent: str, child: str, item: str) -> str:
    """Add `- item` under `parent:\\n  child:` if missing. Text-level,
    indentation-aware, so PyYAML isn't a dependency and the user's
    comments/ordering survive."""
    pattern = re.compile(rf"^{re.escape(parent)}:\s*\n((?:[ \t]+.*\n?)*)", re.MULTILINE)
    match = pattern.search(text)
    if match is None:
        return text.rstrip("\n") + f"\n{parent}:\n  {child}:\n    - {item}\n"
    block = match.group(0)
    child_match = re.search(rf"^([ \t]+){re.escape(child)}:\s*\n((?:\1[ \t]+.*\n?)*)", block, re.MULTILINE)
    if child_match is None:
        new_block = block.rstrip("\n") + f"\n  {child}:\n    - {item}\n"
        return text.replace(block, new_block, 1)
    indent = child_match.group(1)
    items_block = child_match.group(0)
    if re.search(rf"^{indent}[ \t]+-\s*{re.escape(item)}\s*$", items_block, re.MULTILINE):
        return text
    new_items = items_block.rstrip("\n") + f"\n{indent}  - {item}\n"
    return text.replace(items_block, new_items, 1)


def _ensure_yaml_mapping(text: str, parent: str, key: str, body_lines: list[str]) -> str:
    """Ensure `parent:` contains `key:` with the given body (replacing an
    existing `key:` block under that parent)."""
    parent_pattern = re.compile(rf"^{re.escape(parent)}:\s*\n((?:[ \t]+.*\n?)*)", re.MULTILINE)
    match = parent_pattern.search(text)
    rendered = f"  {key}:\n" + "".join(f"    {line}\n" for line in body_lines)
    if match is None:
        return text.rstrip("\n") + f"\n{parent}:\n{rendered}"
    block = match.group(0)
    key_pattern = re.compile(rf"^  {re.escape(key)}:\s*\n((?:    .*\n?)*)", re.MULTILINE)
    if key_pattern.search(block):
        new_block = key_pattern.sub(rendered, block, count=1)
    else:
        new_block = block.rstrip("\n") + "\n" + rendered
    return text.replace(block, new_block, 1)


def connect_hermes(
    repo_root: Path,
    api_url: str = DEFAULT_API_URL,
    hermes_home: Optional[Path] = None,
    log: Log = _log,
) -> Path:
    hermes_home = hermes_home or Path.home() / ".hermes"
    plugins_dir = hermes_home / "plugins"
    plugins_dir.mkdir(parents=True, exist_ok=True)
    link = plugins_dir / MCP_NAME
    target = repo_root / "integrations" / "hermes" / "hermes_plugin"
    if link.is_symlink() or link.exists():
        if link.is_symlink() and os.path.realpath(link) == os.path.realpath(target):
            log(f"  plugin: {link} already linked")
        else:
            log(f"  plugin: {link} exists and is not our symlink — leaving it; link it manually to {target}")
    else:
        link.symlink_to(target, target_is_directory=True)
        log(f"  plugin: linked {link} -> {target}")

    config_path = hermes_home / "config.yaml"
    text = config_path.read_text() if config_path.exists() else ""
    backup = _backup(config_path)
    text = _ensure_yaml_list_item(text, "plugins", "enabled", MCP_NAME)
    text = _ensure_yaml_mapping(text, "mcp_servers", MCP_NAME, [f"url: {api_url.rstrip('/')}/mcp/", "enabled: true"])
    config_path.write_text(text)
    log(f"  config: plugin enabled + MCP server set in {config_path}" + (f" (backup {backup.name})" if backup else ""))
    return config_path


CONNECTORS = {
    "claude-code": connect_claude_code,
    "codex": connect_codex,
    "hermes": connect_hermes,
}
