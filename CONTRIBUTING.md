# Contributing to Aftermind

Thanks for your interest. This project is source-available and noncommercial (see LICENSE) — contributions are welcome from individuals, researchers, and noncommercial organizations.

## Ground rules

- By submitting a contribution, you agree it's licensed under the same terms as the project (PolyForm Noncommercial 1.0.0).
- Do not contribute code you don't have the right to license under these terms (no copy-pasted proprietary/commercial-licensed code).
- Be respectful — see CODE_OF_CONDUCT.md.

## Architecture first

Read `AGENTS.md` before touching code — it documents the layering rules (`domain/` → `core/` → `providers/` → `apps/` → `integrations/`/`sdk/`) and the scope discipline (`MemoryScope.stable()`) that the whole system depends on. PRs that violate the layering (e.g. `core/` importing a concrete provider) will be asked to change.

## Workflow

1. Fork and branch off `main`.
2. Make focused changes — one concern per PR.
3. Add/update tests for anything behavioral.
4. Run the full test suite before opening a PR:
   ```bash
   .venv/bin/python -m pytest tests/ -q --ignore=tests/integration/test_full_memory_loop_live.py
   ```
5. Open a PR describing what changed and why. Link any related issue.

## Code style

- Domain models: `@dataclass(frozen=True)`, `MappingProxyType` for dicts, `tuple` for lists.
- No comments explaining *what* code does — only *why*, when non-obvious.
- No speculative abstractions, feature flags, or backwards-compat shims — match existing simplicity.
- New backend integrations go under `providers/<name>/` and implement the relevant `domain/interfaces/*.py` Protocol; don't special-case a backend inside `core/`.

## Verifying against real infrastructure

Where a PR touches a provider (SQLite, Neo4j/Graphiti, OpenKnowledge, an LLM provider, a framework integration like Hermes), prefer testing against the real thing over mocks when it's reasonably available, and document how you verified it in the PR description. Unit tests may use in-memory fakes; don't guess an external API/hook contract — read the actual library source or docs.

## Reporting issues

Open a GitHub issue with: what you expected, what happened, repro steps, and relevant logs/output. For security issues, see SECURITY.md if present, or open a private report if your Git host supports it rather than a public issue.

## Commit messages

Plain, descriptive commit messages. No AI/tool attribution lines.
