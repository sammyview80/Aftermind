"""`aftermind` command-line entry point.

    aftermind init             pick the LLM: reuse Codex / Claude Code / OpenRouter logins, or a new key
    aftermind up               one command: .env, Neo4j (docker), OpenKnowledge, SQLite, API
    aftermind down             stop what `up` started
    aftermind status           what is running / reachable
    aftermind connect X        wire an agent: claude-code | codex | hermes | all
    aftermind serve            run the REST+MCP API (with in-process sync worker)
    aftermind worker           run only the outbox sync worker (separate process)
    aftermind sync status      show outbox backlog
    aftermind sync run         drain due jobs once
    aftermind sync retry [ID]  requeue dead jobs (all, or one)
    aftermind backup DEST      consistent snapshot of the SQLite database
    aftermind check            integrity check of the SQLite database
    aftermind config           print effective configuration (secrets redacted)
"""
import argparse
import json
import signal
import sys
import threading


def _cmd_init(args: argparse.Namespace) -> int:
    from apps.setup import llm_setup, stack

    root = stack.repo_root()
    stack.ensure_env(root)
    ok = llm_setup.run(
        root,
        provider=args.provider,
        model=args.model,
        assume_yes=args.yes,
        skip_verify=args.no_verify,
    )
    return 0 if ok else 1


def _cmd_up(args: argparse.Namespace) -> int:
    from apps.setup import llm_setup, stack
    from providers.llm.factory import llm_configured

    serve = "foreground" if args.foreground else args.serve
    report = stack.up(serve=serve)
    if not args.no_init and not llm_configured(report.env) and sys.stdin.isatty():
        # First run: offer the machine's existing logins before anything
        # else, so observe() can learn without a paste-a-key step.
        llm_setup.run(stack.repo_root())
    if serve == "foreground":
        if not report.sqlite:
            return 1
        return _cmd_serve(argparse.Namespace(host=None, port=None))
    return 0 if report.sqlite and report.server is not False else 1


def _cmd_down(args: argparse.Namespace) -> int:
    from apps.setup import stack

    stack.down(stop_graph=not args.keep_neo4j)
    return 0


def _cmd_status(args: argparse.Namespace) -> int:
    from apps.setup import stack

    print(json.dumps(stack.status(), indent=2))
    return 0


def _cmd_connect(args: argparse.Namespace) -> int:
    from apps.setup import connectors, stack

    targets = list(connectors.CONNECTORS) if args.agent == "all" else [args.agent]
    root = stack.repo_root()
    for target in targets:
        print(f"== connect {target}", file=sys.stderr)
        connectors.CONNECTORS[target](root, api_url=args.url)
    print("Restart the agent(s) so they pick up the new hooks/MCP config.", file=sys.stderr)
    return 0


def _cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from apps.api.deps import get_settings

    settings = get_settings()
    uvicorn.run(
        "apps.api.main:app",
        host=args.host or settings.host,
        port=args.port or settings.port,
        log_level=settings.log_level.lower(),
    )
    return 0


def _cmd_worker(args: argparse.Namespace) -> int:
    from apps.api.deps import get_settings, get_sync_worker

    get_settings()
    worker = get_sync_worker()
    stop = threading.Event()

    def _handle(signum, frame):  # noqa: ARG001
        stop.set()

    signal.signal(signal.SIGINT, _handle)
    signal.signal(signal.SIGTERM, _handle)
    worker.start()
    print("aftermind sync worker running (Ctrl-C to stop)", file=sys.stderr)
    while not stop.is_set():
        stop.wait(0.5)
    worker.stop()
    return 0


def _cmd_sync(args: argparse.Namespace) -> int:
    from apps.api.deps import get_service, get_settings, get_sync_worker

    get_settings()
    service = get_service()
    worker = get_sync_worker()
    store = worker._job_store

    if args.sync_command == "status":
        out = {"mode": service.sync.mode, "counts": store.counts()}
        if args.verbose:
            out["jobs"] = [
                {
                    "job_id": j.job_id,
                    "kind": j.kind.value,
                    "status": j.status.value,
                    "attempts": j.attempts,
                    "next_attempt_at": j.next_attempt_at.isoformat(),
                    "last_error": j.last_error,
                    "payload": dict(j.payload),
                }
                for j in store.list_jobs(limit=args.limit)
            ]
        print(json.dumps(out, indent=2))
        return 0
    if args.sync_command == "run":
        worker.recover()
        print(json.dumps(worker.drain(), indent=2))
        return 0
    if args.sync_command == "retry":
        print(json.dumps({"requeued": worker.retry_dead(args.job_id)}))
        return 0
    return 2


def _cmd_backup(args: argparse.Namespace) -> int:
    from apps.api.deps import get_settings, get_sqlite_client

    get_settings()
    path = get_sqlite_client().backup(args.destination)
    print(path)
    return 0


def _cmd_check(args: argparse.Namespace) -> int:
    from apps.api.deps import get_settings, get_sqlite_client

    settings = get_settings()
    ok = get_sqlite_client().integrity_check()
    print(json.dumps({"database_path": settings.database_path, "integrity": "ok" if ok else "corrupt"}))
    return 0 if ok else 1


def _cmd_config(args: argparse.Namespace) -> int:
    from apps.api.deps import get_settings

    print(json.dumps(get_settings().redacted(), indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aftermind", description="Aftermind memory runtime")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="choose the LLM: reuse existing Codex/Claude Code/OpenRouter credentials or add a key")
    init.add_argument("--provider", choices=["openai_compatible", "codex_oauth", "claude_code_oauth"], default=None)
    init.add_argument("--model", default=None)
    init.add_argument("-y", "--yes", action="store_true", help="non-interactive: take the first detected credential")
    init.add_argument("--no-verify", action="store_true", help="skip the test completion")
    init.set_defaults(func=_cmd_init)

    up = sub.add_parser("up", help="bring up .env, Neo4j, OpenKnowledge, SQLite and the API")
    up.add_argument("--serve", choices=["detach", "none"], default="detach", help="API: background (default) or skip")
    up.add_argument("--foreground", action="store_true", help="run the API in this terminal")
    up.add_argument("--no-init", action="store_true", help="don't run the interactive LLM setup when none is configured")
    up.set_defaults(func=_cmd_up)

    down = sub.add_parser("down", help="stop the API, OpenKnowledge and the Neo4j container")
    down.add_argument("--keep-neo4j", action="store_true")
    down.set_defaults(func=_cmd_down)

    status_cmd = sub.add_parser("status", help="show what is running")
    status_cmd.set_defaults(func=_cmd_status)

    connect = sub.add_parser("connect", help="wire an agent runtime to this Aftermind")
    connect.add_argument("agent", choices=["claude-code", "codex", "hermes", "all"])
    connect.add_argument("--url", default="http://127.0.0.1:8000", help="Aftermind API base URL")
    connect.set_defaults(func=_cmd_connect)

    serve = sub.add_parser("serve", help="run the REST + MCP API")
    serve.add_argument("--host", default=None)
    serve.add_argument("--port", type=int, default=None)
    serve.set_defaults(func=_cmd_serve)

    worker = sub.add_parser("worker", help="run the outbox sync worker only")
    worker.set_defaults(func=_cmd_worker)

    sync = sub.add_parser("sync", help="inspect/drive the durable sync outbox")
    sync_sub = sync.add_subparsers(dest="sync_command", required=True)
    status = sync_sub.add_parser("status")
    status.add_argument("-v", "--verbose", action="store_true")
    status.add_argument("--limit", type=int, default=50)
    sync_sub.add_parser("run")
    retry = sync_sub.add_parser("retry")
    retry.add_argument("job_id", nargs="?", default=None)
    sync.set_defaults(func=_cmd_sync)

    backup = sub.add_parser("backup", help="snapshot the SQLite database")
    backup.add_argument("destination")
    backup.set_defaults(func=_cmd_backup)

    check = sub.add_parser("check", help="SQLite integrity check")
    check.set_defaults(func=_cmd_check)

    config = sub.add_parser("config", help="print effective configuration")
    config.set_defaults(func=_cmd_config)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
