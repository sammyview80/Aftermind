import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional

DEFAULT_BASE_URL = "http://127.0.0.1:65425"
_META_PREFIX = "<!--aftermind-meta:"
_META_SUFFIX = "-->"


def _doc_name(slug: str, scope_key: str) -> str:
    safe_scope = scope_key.replace("*", "unscoped").replace(":", "_")
    return f"{safe_scope}/{slug}.md"


def _embed_meta(data: dict, markdown: str) -> str:
    """OpenKnowledge stores plain markdown, no separate metadata
    channel — embed the lossless document data (version,
    source_memory_ids, sections, timestamps) as an HTML comment so it's
    invisible when the doc is viewed/edited as markdown, but round-trips
    exactly on read."""
    return f"{_META_PREFIX}{json.dumps(data)}{_META_SUFFIX}\n\n{markdown}"


def _parse_meta(content: str) -> Optional[dict]:
    if not content.startswith(_META_PREFIX):
        return None
    end = content.index(_META_SUFFIX)
    return json.loads(content[len(_META_PREFIX) : end])


class RemoteOpenKnowledgeClient:
    """HTTP client for a real running OpenKnowledge server (`ok start` /
    OK Desktop) — same read/write/search shape as LocalMarkdownClient,
    so OpenKnowledgeStore and mapper.py work unmodified against either
    backend. Talks to the real REST API (/api/document, /api/agent-write-md,
    /api/search) discovered from the installed `ok` CLI, not guessed —
    OpenKnowledge has no OpenAPI spec exposed at runtime.
    """

    def __init__(self, base_url: str = DEFAULT_BASE_URL, timeout: float = 10.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _get(self, path: str, params: dict) -> Optional[dict]:
        query = urllib.parse.urlencode(params)
        request = urllib.request.Request(f"{self.base_url}{path}?{query}")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            raise

    def _post(self, path: str, body: dict) -> dict:
        data = json.dumps(body).encode()
        request = urllib.request.Request(
            f"{self.base_url}{path}", data=data, headers={"Content-Type": "application/json"}, method="POST"
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return json.loads(response.read())

    def read(self, slug: str, scope_key: str = "*") -> Optional[dict]:
        result = self._get("/api/document", {"docName": _doc_name(slug, scope_key)})
        if result is None:
            return None
        return _parse_meta(result["content"])

    def write(self, slug: str, scope_key: str, data: dict, markdown: str) -> None:
        self._post(
            "/api/agent-write-md",
            {"docName": _doc_name(slug, scope_key), "markdown": _embed_meta(data, markdown)},
        )

    def search(self, query: str, scope_key: str = "*", limit: int = 5) -> list[dict]:
        """List-then-filter against /api/documents + /api/document,
        rather than /api/search: the server's own full-text index only
        reliably matched title/path in testing (body-only terms
        returned nothing, seemingly an indexing-lag issue), which would
        make a just-written document briefly unsearchable. This is
        slower at scale but correct regardless of indexing timing —
        acceptable for Aftermind's own memory-document corpus size."""
        prefix = f"{scope_key.replace('*', 'unscoped').replace(':', '_')}/"
        query_words = {w.lower() for w in query.split() if w}

        listing = self._get("/api/documents", {}) or {"documents": []}
        matches = []
        for entry in listing.get("documents", []):
            doc_name = entry.get("docName") or ""
            if entry.get("kind") != "document" or not doc_name.startswith(prefix) or not doc_name.endswith(".md"):
                continue
            slug = doc_name[len(prefix) : -len(".md")]
            document = self.read(slug, scope_key)
            if document is None:
                continue
            haystack = (
                document.get("title", "") + " " + " ".join(s["body"] for s in document.get("sections", []))
            ).lower()
            if not query_words or any(word in haystack for word in query_words):
                matches.append(document)
        return matches[:limit]
