import json
import re
from pathlib import Path
from typing import Optional

DEFAULT_BASE_DIR = Path("./openknowledge_store")
_UNSAFE_SLUG_CHARS = re.compile(r"[^a-z0-9_-]")


def _safe_slug(slug: str) -> str:
    cleaned = _UNSAFE_SLUG_CHARS.sub("-", slug.strip().lower())
    return cleaned.strip("-") or "untitled"


class LocalMarkdownClient:
    """Filesystem-backed OpenKnowledge client: one JSON file (lossless
    round-trip) plus a sibling .md file (the actual human-readable
    artifact) per document, under `base_dir/<scope>/<slug>`.

    This is a real, working default — not a test fake — since durable
    human-readable knowledge is exactly what markdown files on disk are.
    A hosted/API-backed OpenKnowledge client can implement the same
    read/write/search shape later without touching store.py or mapper.py.
    """

    def __init__(self, base_dir: Path = DEFAULT_BASE_DIR) -> None:
        self.base_dir = Path(base_dir)

    def _dir_for(self, scope_key: str) -> Path:
        directory = self.base_dir / _safe_slug(scope_key)
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def read(self, slug: str, scope_key: str = "*") -> Optional[dict]:
        path = self._dir_for(scope_key) / f"{_safe_slug(slug)}.json"
        if not path.exists():
            return None
        return json.loads(path.read_text())

    def write(self, slug: str, scope_key: str, data: dict, markdown: str) -> None:
        directory = self._dir_for(scope_key)
        safe = _safe_slug(slug)
        (directory / f"{safe}.json").write_text(json.dumps(data, indent=2))
        (directory / f"{safe}.md").write_text(markdown)

    def search(self, query: str, scope_key: str = "*", limit: int = 5) -> list[dict]:
        query_words = {w.lower() for w in query.split() if w}
        matches = []
        for path in self._dir_for(scope_key).glob("*.json"):
            data = json.loads(path.read_text())
            haystack = (data.get("title", "") + " " + " ".join(s["body"] for s in data.get("sections", []))).lower()
            if not query_words or any(word in haystack for word in query_words):
                matches.append(data)
        return matches[:limit]
