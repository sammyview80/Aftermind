"""All runtime configuration in one place, read from the environment
(populated from .env by python-dotenv when installed). Nothing else in
apps/ should call os.environ directly — add a field here instead, so
`aftermind config` can print the effective configuration and the
.env.example stays the single documented contract."""
import os
from dataclasses import dataclass, fields

from core.sync.dispatcher import BACKGROUND, EAGER
from core.sync.worker import DEFAULT_BATCH_SIZE, DEFAULT_POLL_INTERVAL_SECONDS, DEFAULT_STALE_RUNNING_SECONDS
from domain.models.sync_job import DEFAULT_MAX_ATTEMPTS
from providers.sqlite.client import DEFAULT_DB_PATH

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

_SECRET_FIELDS = frozenset({"llm_api_key", "neo4j_password"})


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Settings:
    # Canonical store
    database_path: str = DEFAULT_DB_PATH

    # LLM (OpenAI-compatible; OpenRouter by default)
    llm_api_key: str = ""
    llm_model: str = ""
    llm_base_url: str = "https://openrouter.ai/api/v1"

    # Graph store — empty password = in-memory fallback
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = ""
    neo4j_timeout_seconds: float = 5.0  # fail fast when Neo4j is unreachable

    # Document store — empty = local markdown directory
    openknowledge_url: str = ""

    # Durable sync / outbox
    sync_mode: str = EAGER  # eager | background
    sync_worker_enabled: bool = True
    sync_poll_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS
    sync_batch_size: int = DEFAULT_BATCH_SIZE
    sync_max_attempts: int = DEFAULT_MAX_ATTEMPTS
    sync_stale_running_seconds: float = DEFAULT_STALE_RUNNING_SECONDS

    # Observability
    log_level: str = "INFO"
    log_format: str = "text"  # text | json
    trace_buffer_size: int = 200

    # Server
    host: str = "0.0.0.0"
    port: int = 8000

    @classmethod
    def from_env(cls) -> "Settings":
        env = os.environ.get
        settings = cls(
            database_path=env("DATABASE_PATH", DEFAULT_DB_PATH),
            llm_api_key=env("LLM_API_KEY", ""),
            llm_model=env("LLM_MODEL", ""),
            llm_base_url=env("LLM_BASE_URL", cls.llm_base_url),
            neo4j_uri=env("NEO4J_URI", cls.neo4j_uri),
            neo4j_user=env("NEO4J_USER", cls.neo4j_user),
            neo4j_password=env("NEO4J_PASSWORD", ""),
            neo4j_timeout_seconds=float(env("NEO4J_TIMEOUT_SECONDS", 5.0)),
            openknowledge_url=env("OPENKNOWLEDGE_URL", ""),
            sync_mode=env("AFTERMIND_SYNC_MODE", EAGER).strip().lower() or EAGER,
            sync_worker_enabled=_env_bool("AFTERMIND_SYNC_WORKER", True),
            sync_poll_seconds=float(env("AFTERMIND_SYNC_POLL_SECONDS", DEFAULT_POLL_INTERVAL_SECONDS)),
            sync_batch_size=int(env("AFTERMIND_SYNC_BATCH_SIZE", DEFAULT_BATCH_SIZE)),
            sync_max_attempts=int(env("AFTERMIND_SYNC_MAX_ATTEMPTS", DEFAULT_MAX_ATTEMPTS)),
            sync_stale_running_seconds=float(
                env("AFTERMIND_SYNC_STALE_RUNNING_SECONDS", DEFAULT_STALE_RUNNING_SECONDS)
            ),
            log_level=env("AFTERMIND_LOG_LEVEL", "INFO").upper(),
            log_format=env("AFTERMIND_LOG_FORMAT", "text").lower(),
            trace_buffer_size=int(env("AFTERMIND_TRACE_BUFFER", 200)),
            host=env("AFTERMIND_HOST", cls.host),
            port=int(env("AFTERMIND_PORT", cls.port)),
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        if self.sync_mode not in (EAGER, BACKGROUND):
            raise ValueError(f"AFTERMIND_SYNC_MODE must be '{EAGER}' or '{BACKGROUND}', got {self.sync_mode!r}")
        if self.log_format not in ("text", "json"):
            raise ValueError(f"AFTERMIND_LOG_FORMAT must be 'text' or 'json', got {self.log_format!r}")
        if self.sync_max_attempts < 1:
            raise ValueError("AFTERMIND_SYNC_MAX_ATTEMPTS must be >= 1")
        if self.sync_poll_seconds <= 0:
            raise ValueError("AFTERMIND_SYNC_POLL_SECONDS must be > 0")

    @property
    def graph_backend(self) -> str:
        return "neo4j" if self.neo4j_password else "inmemory"

    @property
    def document_backend(self) -> str:
        return "openknowledge" if self.openknowledge_url else "local_markdown"

    def redacted(self) -> dict:
        """Effective configuration with secrets masked — safe to log or
        return from a diagnostics endpoint."""
        out = {}
        for f in fields(self):
            value = getattr(self, f.name)
            if f.name in _SECRET_FIELDS:
                value = "***" if value else ""
            out[f.name] = value
        out["graph_backend"] = self.graph_backend
        out["document_backend"] = self.document_backend
        return out
