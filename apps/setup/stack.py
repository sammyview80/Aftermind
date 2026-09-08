"""`aftermind up`: bring up everything Aftermind needs on one machine.

    .env            created from .env.example, secrets generated, kept in sync
    Neo4j           docker container `aftermind-neo4j` (started or created)
    OpenKnowledge   `ok start` on OPENKNOWLEDGE_URL's port (if `ok` is installed)
    SQLite          schema created / integrity-checked at DATABASE_PATH
    API             uvicorn on AFTERMIND_PORT (foreground, or --detach)

Every step is idempotent and degrades explicitly: no Docker means the
graph store falls back to in-memory, no `ok` means documents go to a
local markdown directory — both are printed, never silent. State for
detached processes lives in `.aftermind/` next to the repo.
"""
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urlparse

NEO4J_CONTAINER = "aftermind-neo4j"
NEO4J_IMAGE = "neo4j:5"
NEO4J_VOLUME = "aftermind_neo4j_data"
DEFAULT_OPENKNOWLEDGE_URL = "http://127.0.0.1:65425"
STATE_DIR = ".aftermind"

Log = Callable[[str], None]


def _default_log(message: str) -> None:
    print(message, file=sys.stderr)


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


# ----------------------------------------------------------------- .env


def read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def write_env_values(path: Path, updates: dict[str, str]) -> None:
    """Set keys in a .env file in place (preserving comments/order);
    append any key not present yet."""
    lines = path.read_text().splitlines() if path.exists() else []
    seen: set[str] = set()
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key = stripped.partition("=")[0].strip()
        if key in updates:
            lines[i] = f"{key}={updates[key]}"
            seen.add(key)
    for key, value in updates.items():
        if key not in seen:
            lines.append(f"{key}={value}")
    path.write_text("\n".join(lines) + "\n")


def ensure_env(root: Path, log: Log = _default_log, have_ok: Optional[bool] = None) -> dict[str, str]:
    """Create .env from .env.example if missing and fill in what a local
    stack needs: a Neo4j password, the local Neo4j URI, and an
    OpenKnowledge URL when the `ok` CLI is available. Never touches an
    LLM key — that has to come from the user."""
    env_path = root / ".env"
    if not env_path.exists():
        example = root / ".env.example"
        if example.exists():
            shutil.copy(example, env_path)
            log(f"created {env_path.name} from .env.example")
        else:
            env_path.write_text("")
    values = read_env_file(env_path)
    updates: dict[str, str] = {}

    if not values.get("DATABASE_PATH"):
        updates["DATABASE_PATH"] = "./aftermind.db"
    if not values.get("NEO4J_URI"):
        updates["NEO4J_URI"] = "bolt://localhost:7687"
    if not values.get("NEO4J_USER"):
        updates["NEO4J_USER"] = "neo4j"
    if not values.get("NEO4J_PASSWORD"):
        updates["NEO4J_PASSWORD"] = secrets.token_urlsafe(12)
        log("generated NEO4J_PASSWORD")
    if have_ok is None:
        have_ok = shutil.which("ok") is not None
    if not values.get("OPENKNOWLEDGE_URL") and have_ok:
        updates["OPENKNOWLEDGE_URL"] = DEFAULT_OPENKNOWLEDGE_URL

    if updates:
        write_env_values(env_path, updates)
        values.update(updates)

    if not values.get("LLM_API_KEY") or not values.get("LLM_MODEL"):
        log("WARNING: LLM_API_KEY / LLM_MODEL are empty in .env — recall works, observe() needs them.")
    return values


# ---------------------------------------------------------------- ports


def port_open(host: str, port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def wait_for_port(host: str, port: int, timeout: float, log: Log, what: str) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if port_open(host, port):
            return True
        time.sleep(0.5)
    log(f"WARNING: {what} did not open {host}:{port} within {timeout:.0f}s")
    return False


def _host_port(url: str, default_port: int) -> tuple[str, int]:
    parsed = urlparse(url)
    return parsed.hostname or "127.0.0.1", parsed.port or default_port


# ---------------------------------------------------------------- docker


def docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        return subprocess.run(["docker", "info"], capture_output=True, timeout=10).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _docker(*args: str, check: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", *args], capture_output=True, text=True, check=check)


def container_state(name: str) -> Optional[str]:
    """'running' / 'exited' / ... or None when no such container."""
    result = _docker("inspect", "--format", "{{.State.Status}}", name)
    return result.stdout.strip() if result.returncode == 0 else None


def container_neo4j_password(name: str) -> Optional[str]:
    """The NEO4J_AUTH password an existing container was created with —
    the container, not .env, is the source of truth for a volume that
    already holds an auth record."""
    result = _docker("inspect", "--format", "{{json .Config.Env}}", name)
    if result.returncode != 0:
        return None
    for entry in json.loads(result.stdout or "[]"):
        if entry.startswith("NEO4J_AUTH=") and "/" in entry:
            return entry.split("=", 1)[1].split("/", 1)[1]
    return None


def ensure_neo4j(env: dict[str, str], env_path: Path, log: Log = _default_log) -> bool:
    """Start (or create) the Neo4j container and make sure .env's
    password matches the one the container actually uses. Returns True
    when bolt is reachable."""
    host, port = _host_port(env.get("NEO4J_URI", "bolt://localhost:7687"), 7687)

    if not docker_available():
        if port_open(host, port):
            log(f"Neo4j already reachable at {host}:{port} (not managed by Docker here)")
            return True
        log("WARNING: Docker not available — graph store will fall back to in-memory (not durable).")
        write_env_values(env_path, {"NEO4J_PASSWORD": ""})
        env["NEO4J_PASSWORD"] = ""
        return False

    state = container_state(NEO4J_CONTAINER)
    if state is None:
        log(f"creating Neo4j container {NEO4J_CONTAINER} ({NEO4J_IMAGE})")
        _docker(
            "run",
            "-d",
            "--name",
            NEO4J_CONTAINER,
            "--restart",
            "unless-stopped",
            "-p",
            f"{port}:7687",
            "-p",
            "7474:7474",
            "-e",
            f"NEO4J_AUTH=neo4j/{env['NEO4J_PASSWORD']}",
            "-v",
            f"{NEO4J_VOLUME}:/data",
            NEO4J_IMAGE,
            check=True,
        )
    else:
        existing_password = container_neo4j_password(NEO4J_CONTAINER)
        if existing_password and existing_password != env.get("NEO4J_PASSWORD"):
            log("syncing NEO4J_PASSWORD in .env to the existing container's password")
            write_env_values(env_path, {"NEO4J_PASSWORD": existing_password})
            env["NEO4J_PASSWORD"] = existing_password
        if state != "running":
            log(f"starting Neo4j container {NEO4J_CONTAINER}")
            _docker("start", NEO4J_CONTAINER, check=True)
        else:
            log(f"Neo4j container {NEO4J_CONTAINER} already running")

    return wait_for_port(host, port, timeout=90, log=log, what="Neo4j")


def stop_neo4j(log: Log = _default_log) -> None:
    if docker_available() and container_state(NEO4J_CONTAINER) == "running":
        _docker("stop", NEO4J_CONTAINER)
        log(f"stopped {NEO4J_CONTAINER}")


# ---------------------------------------------------------- openknowledge


def state_dir(root: Path) -> Path:
    path = root / STATE_DIR
    path.mkdir(exist_ok=True)
    return path


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _read_pid(path: Path) -> Optional[int]:
    try:
        return int(path.read_text().strip())
    except (OSError, ValueError):
        return None


def _spawn_detached(command: list[str], cwd: Path, log_path: Path, pid_path: Path) -> int:
    log_file = open(log_path, "ab")  # noqa: SIM115 - handed to the child
    process = subprocess.Popen(
        command,
        cwd=str(cwd),
        stdout=log_file,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
    )
    pid_path.write_text(str(process.pid))
    return process.pid


def ensure_openknowledge(root: Path, env: dict[str, str], env_path: Path, log: Log = _default_log) -> bool:
    """Start an OpenKnowledge server on the configured URL when the `ok`
    CLI is available and nothing is listening yet. Documents live in
    `.aftermind/openknowledge/` (a normal OK project directory)."""
    url = env.get("OPENKNOWLEDGE_URL", "")
    if not url:
        log("OPENKNOWLEDGE_URL empty — documents go to ./openknowledge_store (local markdown).")
        return False
    host, port = _host_port(url, 65425)
    if port_open(host, port):
        log(f"OpenKnowledge already reachable at {url}")
        return True

    ok = shutil.which("ok")
    if ok is None:
        log("WARNING: `ok` CLI not found (npm i -g @inkeep/open-knowledge) — falling back to local markdown.")
        write_env_values(env_path, {"OPENKNOWLEDGE_URL": ""})
        env["OPENKNOWLEDGE_URL"] = ""
        return False

    state = state_dir(root)
    project = state / "openknowledge"
    project.mkdir(exist_ok=True)
    log(f"starting OpenKnowledge: ok start --port {port} (project {project})")
    _spawn_detached(
        [ok, "start", "--port", str(port), "--host", host],
        cwd=project,
        log_path=state / "openknowledge.log",
        pid_path=state / "openknowledge.pid",
    )
    return wait_for_port(host, port, timeout=60, log=log, what="OpenKnowledge")


def stop_openknowledge(root: Path, log: Log = _default_log) -> None:
    pid_path = state_dir(root) / "openknowledge.pid"
    pid = _read_pid(pid_path)
    if pid and _pid_alive(pid):
        os.killpg(pid, 15)
        log("stopped OpenKnowledge")
    pid_path.unlink(missing_ok=True)


# ---------------------------------------------------------------- sqlite


def ensure_database(env: dict[str, str], log: Log = _default_log) -> bool:
    from providers.sqlite.client import SqliteClient

    path = env.get("DATABASE_PATH", "./aftermind.db")
    client = SqliteClient(path)
    ok = client.integrity_check()
    log(f"SQLite {path}: {'ok' if ok else 'INTEGRITY CHECK FAILED'}")
    return ok


# ---------------------------------------------------------------- server


def server_url(env: dict[str, str]) -> str:
    return f"http://127.0.0.1:{env.get('AFTERMIND_PORT', '8000')}"


def server_running(env: dict[str, str]) -> bool:
    return port_open("127.0.0.1", int(env.get("AFTERMIND_PORT", "8000")))


def start_server_detached(root: Path, env: dict[str, str], log: Log = _default_log) -> bool:
    if server_running(env):
        log(f"Aftermind API already listening at {server_url(env)}")
        return True
    state = state_dir(root)
    port = env.get("AFTERMIND_PORT", "8000")
    pid = _spawn_detached(
        [sys.executable, "-m", "uvicorn", "apps.api.main:app", "--host", env.get("AFTERMIND_HOST", "0.0.0.0"), "--port", port],
        cwd=root,
        log_path=state / "server.log",
        pid_path=state / "server.pid",
    )
    log(f"started Aftermind API (pid {pid}), log: {state / 'server.log'}")
    return wait_for_port("127.0.0.1", int(port), timeout=30, log=log, what="Aftermind API")


def stop_server(root: Path, log: Log = _default_log) -> None:
    pid_path = state_dir(root) / "server.pid"
    pid = _read_pid(pid_path)
    if pid and _pid_alive(pid):
        os.killpg(pid, 15)
        log("stopped Aftermind API")
    pid_path.unlink(missing_ok=True)


# ------------------------------------------------------------------- up


@dataclass
class StackReport:
    env: dict[str, str] = field(default_factory=dict)
    neo4j: bool = False
    openknowledge: bool = False
    sqlite: bool = False
    server: Optional[bool] = None

    def summary(self) -> str:
        rows = [
            ("SQLite", "ok" if self.sqlite else "FAILED", self.env.get("DATABASE_PATH", "")),
            ("Neo4j", "ok" if self.neo4j else "in-memory fallback", self.env.get("NEO4J_URI", "")),
            (
                "OpenKnowledge",
                "ok" if self.openknowledge else "local markdown fallback",
                self.env.get("OPENKNOWLEDGE_URL", ""),
            ),
        ]
        if self.server is not None:
            rows.append(("API", "ok" if self.server else "FAILED", server_url(self.env)))
        width = max(len(r[0]) for r in rows)
        return "\n".join(f"  {name:<{width}}  {status:<24} {detail}" for name, status, detail in rows)


def up(root: Optional[Path] = None, serve: str = "foreground", log: Log = _default_log) -> StackReport:
    """Bring the whole stack up. `serve` is "foreground" (run uvicorn in
    this process after the dependencies are ready), "detach" (background
    with pid file), or "none" (dependencies only)."""
    root = root or repo_root()
    report = StackReport()
    env_path = root / ".env"

    log("== Aftermind up ==")
    report.env = ensure_env(root, log=log)
    report.neo4j = ensure_neo4j(report.env, env_path, log=log)
    report.openknowledge = ensure_openknowledge(root, report.env, env_path, log=log)
    report.sqlite = ensure_database(report.env, log=log)

    # The API reads .env through Settings; make the synced values visible
    # to this process too (foreground serve / detached child inherit os.environ).
    for key in ("NEO4J_PASSWORD", "NEO4J_URI", "NEO4J_USER", "OPENKNOWLEDGE_URL", "DATABASE_PATH"):
        if key in report.env:
            os.environ[key] = report.env[key]

    if serve == "detach":
        report.server = start_server_detached(root, report.env, log=log)
    log(report.summary())
    return report


def down(root: Optional[Path] = None, stop_graph: bool = True, log: Log = _default_log) -> None:
    root = root or repo_root()
    stop_server(root, log=log)
    stop_openknowledge(root, log=log)
    if stop_graph:
        stop_neo4j(log=log)


def status(root: Optional[Path] = None) -> dict:
    root = root or repo_root()
    env = read_env_file(root / ".env")
    neo_host, neo_port = _host_port(env.get("NEO4J_URI", "bolt://localhost:7687"), 7687)
    ok_url = env.get("OPENKNOWLEDGE_URL", "")
    ok_state = None
    if ok_url:
        ok_state = port_open(*_host_port(ok_url, 65425))
    api_state = server_running(env)
    ready = None
    if api_state:
        try:
            import urllib.request

            with urllib.request.urlopen(f"{server_url(env)}/health/ready", timeout=3) as response:
                ready = json.loads(response.read())
        except Exception as exc:  # noqa: BLE001
            ready = {"error": f"{type(exc).__name__}: {exc}"}
    return {
        "neo4j": {"container": container_state(NEO4J_CONTAINER) if shutil.which("docker") else None, "bolt_open": port_open(neo_host, neo_port)},
        "openknowledge": {"url": ok_url or None, "open": ok_state},
        "api": {"url": server_url(env), "listening": api_state, "ready": ready},
    }
