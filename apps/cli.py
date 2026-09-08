"""`aftermind` command-line entry point.

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
