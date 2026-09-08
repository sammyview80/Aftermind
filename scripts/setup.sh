#!/usr/bin/env bash
# One-command local setup for Aftermind.
#
#   ./scripts/setup.sh                 # venv + install + Neo4j + OpenKnowledge + SQLite + API (detached)
#   ./scripts/setup.sh --connect all   # ...and wire Claude Code, Codex and Hermes
#   ./scripts/setup.sh --foreground    # run the API in this terminal instead
#
# Idempotent: re-running reuses the venv, the Neo4j container and .env.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PYTHON="${PYTHON:-python3}"
CONNECT=""
SERVE="detach"
while [ $# -gt 0 ]; do
  case "$1" in
    --connect) CONNECT="$2"; shift 2 ;;
    --foreground) SERVE="foreground"; shift ;;
    --no-server) SERVE="none"; shift ;;
    -h|--help) sed -n '2,8p' "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

if [ ! -x .venv/bin/python ]; then
  echo "== creating virtualenv (.venv)"
  "$PYTHON" -m venv .venv
fi
echo "== installing aftermind[graph,mcp]"
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -e ".[graph,mcp,dev]"

if [ "$SERVE" = "foreground" ]; then
  exec .venv/bin/aftermind up --foreground
fi

.venv/bin/aftermind up --serve "$SERVE"

if [ -n "$CONNECT" ]; then
  .venv/bin/aftermind connect "$CONNECT"
fi

echo
echo "Aftermind is up. Next:"
echo "  .venv/bin/aftermind status"
echo "  .venv/bin/aftermind connect claude-code|codex|hermes|all"
echo "  edit .env and set LLM_API_KEY / LLM_MODEL if observe() should learn"
