"""Aftermind Explorer: a small, read-mostly FastAPI app that gives the
whole memory runtime one visual surface — Overview, Memory Ledger,
Knowledge Graph, Knowledge (OpenKnowledge docs), Sessions/Checkpoints,
and Recall Trace.

Deliberately a separate process/app from apps/api (see AGENTS.md's
apps/api/ layer) rather than new endpoints bolted onto it: everything
here is read-only against the same three stores Aftermind already
writes to (SQLite directly, Neo4j directly, OpenKnowledge over its real
HTTP API), plus a thin proxy to apps/api's own /recall and /traces so
the trace view reuses the tracer that's already wired into the real
pipeline instead of re-implementing it. No shared imports from
apps/api/* — this reads the same .env, but stays fully independent so
the two apps can be developed/deployed separately.

Run:
    .venv/bin/python -m apps.explorer.server   # serves http://localhost:8010
"""
import json
import os
import sqlite3
from pathlib import Path
from typing import Optional

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

DATABASE_PATH = os.environ.get("DATABASE_PATH", "./aftermind.db")
AFTERMIND_API_URL = os.environ.get("AFTERMIND_API_URL", "http://localhost:8000").rstrip("/")
NEO4J_URI = os.environ.get("NEO4J_URI", "")
NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "")
OPENKNOWLEDGE_URL = os.environ.get("OPENKNOWLEDGE_URL", "").rstrip("/")

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="Aftermind Explorer")


def _db():
    con = sqlite3.connect(DATABASE_PATH)
    con.row_factory = sqlite3.Row
    return con


def _load_json(text: str, default):
    try:
        return json.loads(text) if text else default
    except (json.JSONDecodeError, TypeError):
        return default


def _memory_row(row: sqlite3.Row, lifecycle: Optional[sqlite3.Row]) -> dict:
    return {
        "memory_id": row["memory_id"],
        "scope_key": row["scope_key"],
        "scope_levels": _load_json(row["scope_levels"], {}),
        "content": row["content"],
        "memory_type": row["memory_type"],
        "confidence": row["confidence"],
        "version": row["version"],
        "superseded_by": row["superseded_by"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "status": lifecycle["status"] if lifecycle else "active",
        "access_count": lifecycle["access_count"] if lifecycle else 0,
        "importance": lifecycle["importance"] if lifecycle else None,
        "decay_score": lifecycle["decay_score"] if lifecycle else None,
        "last_accessed_at": lifecycle["last_accessed_at"] if lifecycle else None,
    }


_HIERARCHY = (
    "tenant_id", "workspace_id", "project_id", "repository_id", "user_id",
    "agent_id", "task_id", "conversation_id", "session_id", "run_id",
)


def _parse_scope_key(key: str) -> dict:
    """MemoryScope.key()'s inverse: ":"-joined, "*" for unset levels, in
    domain/policies/scope_policy.DEFAULT_HIERARCHY order. Traces (unlike
    memories/checkpoints) keep the full non-stable scope, so this is the
    only place session_id/run_id are ever visible."""
    parts = key.split(":") if key else []
    return {name: (parts[i] if i < len(parts) and parts[i] != "*" else None) for i, name in enumerate(_HIERARCHY)}


# ---------------------------------------------------------------- scopes

@app.get("/api/scopes")
def list_scopes():
    """Every distinct scope_key that has ever had a memory OR a
    checkpoint, most recently active first — powers the project picker.
    Union of both tables, not just memories: a project that's only ever
    been checkpointed (no memory formed yet) would otherwise be
    unselectable and its checkpoints unreachable from the UI."""
    with _db() as con:
        memory_rows = con.execute(
            "SELECT scope_key, scope_levels, updated_at AS activity_at, 1 AS is_memory FROM memories"
        ).fetchall()
        checkpoint_rows = con.execute(
            "SELECT scope_key, scope_levels, created_at AS activity_at, 0 AS is_memory FROM checkpoints"
        ).fetchall()

    by_scope: dict[str, dict] = {}
    for r in (*memory_rows, *checkpoint_rows):
        entry = by_scope.setdefault(
            r["scope_key"],
            {
                "scope_key": r["scope_key"],
                "scope_levels": _load_json(r["scope_levels"], {}),
                "last_activity": r["activity_at"],
                "memory_count": 0,
                "checkpoint_count": 0,
            },
        )
        if r["activity_at"] and r["activity_at"] > (entry["last_activity"] or ""):
            entry["last_activity"] = r["activity_at"]
        if r["is_memory"]:
            entry["memory_count"] += 1
        else:
            entry["checkpoint_count"] += 1

    scopes = sorted(by_scope.values(), key=lambda s: s["last_activity"] or "", reverse=True)
    return {"scopes": scopes}


# -------------------------------------------------------------- overview

@app.get("/api/overview")
def overview(scope_key: Optional[str] = None):
    where = "WHERE scope_key = ?" if scope_key else ""
    params = (scope_key,) if scope_key else ()

    with _db() as con:
        total = con.execute(f"SELECT COUNT(*) FROM memories {where}", params).fetchone()[0]
        superseded = con.execute(
            f"SELECT COUNT(*) FROM memories {where}{' AND' if where else 'WHERE'} superseded_by IS NOT NULL", params
        ).fetchone()[0]
        by_status = con.execute(
            f"SELECT l.status, COUNT(*) FROM lifecycle l "
            f"{'WHERE l.scope_key = ?' if scope_key else ''} GROUP BY l.status",
            params,
        ).fetchall()
        checkpoints = con.execute(f"SELECT COUNT(*) FROM checkpoints {where}", params).fetchone()[0]
        latest_checkpoint = con.execute(
            f"SELECT goal, current, next_steps, created_at FROM checkpoints {where} "
            "ORDER BY created_at DESC LIMIT 1",
            params,
        ).fetchone()

    relationships = _graph_count(scope_key)
    documents = _document_count(scope_key)

    return {
        "memories": {"total": total, "live": total - superseded, "superseded": superseded},
        "lifecycle_status": {row[0]: row[1] for row in by_status},
        "relationships": relationships,
        "documents": documents,
        "checkpoints": checkpoints,
        "latest_checkpoint": (
            {
                "goal": latest_checkpoint["goal"],
                "current": latest_checkpoint["current"],
                "next_steps": _load_json(latest_checkpoint["next_steps"], []),
                "created_at": latest_checkpoint["created_at"],
            }
            if latest_checkpoint
            else None
        ),
    }


# ------------------------------------------------------------ memory ledger

@app.get("/api/memories")
def list_memories(
    scope_key: Optional[str] = None,
    status: Optional[str] = None,
    memory_type: Optional[str] = None,
    search: Optional[str] = None,
    page: int = 1,
    page_size: int = 25,
):
    """Filtered + paginated over the full table in SQL (not just the
    fetched page), so `total`/`total_pages` reflect the real filtered
    count regardless of page_size."""
    where_clauses = []
    params: list = []
    if scope_key:
        where_clauses.append("m.scope_key = ?")
        params.append(scope_key)
    if memory_type:
        where_clauses.append("m.memory_type = ?")
        params.append(memory_type)
    if search:
        where_clauses.append("m.content LIKE ?")
        params.append(f"%{search}%")
    where = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

    page = max(page, 1)
    page_size = max(min(page_size, 200), 1)
    offset = (page - 1) * page_size

    with _db() as con:
        lifecycle_by_id = {r["memory_id"]: r for r in con.execute("SELECT * FROM lifecycle").fetchall()}

        if status:
            # Status lives in `lifecycle`, not `memories` — filter in
            # Python against the small per-scope set rather than a SQL
            # join, then paginate the filtered list ourselves.
            all_rows = con.execute(f"SELECT m.* FROM memories m {where} ORDER BY m.updated_at DESC", params).fetchall()
            memories = [_memory_row(r, lifecycle_by_id.get(r["memory_id"])) for r in all_rows]
            memories = [m for m in memories if m["status"] == status]
            total = len(memories)
            memories = memories[offset : offset + page_size]
        else:
            total = con.execute(f"SELECT COUNT(*) FROM memories m {where}", params).fetchone()[0]
            rows = con.execute(
                f"SELECT m.* FROM memories m {where} ORDER BY m.updated_at DESC LIMIT ? OFFSET ?",
                (*params, page_size, offset),
            ).fetchall()
            memories = [_memory_row(r, lifecycle_by_id.get(r["memory_id"])) for r in rows]

    return {
        "memories": memories,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": max((total + page_size - 1) // page_size, 1),
    }


@app.get("/api/memory-types")
def memory_types():
    with _db() as con:
        rows = con.execute("SELECT DISTINCT memory_type FROM memories ORDER BY memory_type").fetchall()
    return {"memory_types": [r[0] for r in rows]}


@app.get("/api/memories/{memory_id}/history")
def memory_history(memory_id: str):
    """Walk the supersession chain both backward (what this replaced)
    and forward (what replaced this), for the ledger's "provenance" drill-down."""
    with _db() as con:
        rows = {r["memory_id"]: r for r in con.execute("SELECT * FROM memories").fetchall()}

    if memory_id not in rows:
        raise HTTPException(status_code=404, detail="memory not found")

    forward = []
    cursor = rows[memory_id]
    while cursor["superseded_by"] and cursor["superseded_by"] in rows:
        cursor = rows[cursor["superseded_by"]]
        forward.append(cursor["memory_id"])

    backward = [r["memory_id"] for r in rows.values() if r["superseded_by"] == memory_id]

    return {"memory_id": memory_id, "supersedes": backward, "superseded_chain": forward}


# --------------------------------------------------------------- knowledge graph

def _neo4j_driver():
    from neo4j import GraphDatabase

    if not NEO4J_URI:
        return None
    return GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD), connection_timeout=3)


def _graph_count(scope_key: Optional[str]) -> dict:
    try:
        driver = _neo4j_driver()
        if driver is None:
            return {"current": 0, "historical": 0, "available": False}
        with driver.session() as session:
            query = "MATCH ()-[r:RELATES_TO]->() " + ("WHERE r.group_id = $g " if scope_key else "") + "RETURN r.expired_at IS NOT NULL AS historical, count(*) AS n"
            records = session.run(query, g=scope_key).data() if scope_key else session.run(query).data()
        driver.close()
        current = sum(r["n"] for r in records if not r["historical"])
        historical = sum(r["n"] for r in records if r["historical"])
        return {"current": current, "historical": historical, "available": True}
    except Exception:
        return {"current": 0, "historical": 0, "available": False}


@app.get("/api/graph")
def graph(scope_key: Optional[str] = None, limit: int = 300):
    """Nodes + edges for the Knowledge Graph view. Edge `historical`
    flags one marked stale by a supersede (see providers/graphiti/store.py
    mark_historical) — kept, not deleted, and shown dimmed in the UI."""
    try:
        driver = _neo4j_driver()
        if driver is None:
            return {"nodes": [], "edges": [], "available": False}
        query = (
            "MATCH (a:Entity)-[r:RELATES_TO]->(b:Entity) "
            + ("WHERE r.group_id = $g " if scope_key else "")
            + "RETURN a.name AS source, r.name AS relation, b.name AS target, "
            "r.expired_at IS NOT NULL AS historical LIMIT $limit"
        )
        with driver.session() as session:
            records = session.run(query, g=scope_key, limit=limit).data()
        driver.close()
    except Exception as exc:
        return {"nodes": [], "edges": [], "available": False, "error": str(exc)}

    node_names = {r["source"] for r in records} | {r["target"] for r in records}
    nodes = [{"id": name, "label": name} for name in sorted(node_names)]
    edges = [
        {"source": r["source"], "relation": r["relation"] or "related_to", "target": r["target"], "historical": bool(r["historical"])}
        for r in records
    ]
    return {"nodes": nodes, "edges": edges, "available": True}


# --------------------------------------------------------------- knowledge docs

@app.get("/api/documents")
def documents(scope_key: Optional[str] = None):
    if not OPENKNOWLEDGE_URL:
        return {"documents": [], "available": False}
    try:
        response = httpx.get(f"{OPENKNOWLEDGE_URL}/api/documents", timeout=5)
        response.raise_for_status()
        raw_docs = response.json() if isinstance(response.json(), list) else response.json().get("documents", [])
    except Exception as exc:
        return {"documents": [], "available": False, "error": str(exc)}

    # OpenKnowledge's real listing shape uses `docName` (see
    # providers/openknowledge/remote_client.py, discovered from the
    # installed `ok` CLI, not guessed) and includes every doc in the
    # server (this local dev instance also indexes unrelated repo
    # files) — only "kind": "document" .md entries are Aftermind pages.
    results = []
    for doc in raw_docs:
        doc_name = doc.get("docName") or doc.get("path") or doc.get("slug", "")
        if doc.get("kind") not in (None, "document") or not doc_name.endswith(".md"):
            continue
        if scope_key and not doc_name.startswith(scope_key.replace("*", "unscoped").replace(":", "_") + "/"):
            continue
        results.append(
            {"path": doc_name, "title": doc.get("title", doc_name), "updated_at": doc.get("updatedAt") or doc.get("updated_at")}
        )
    return {"documents": results, "available": True}


@app.get("/api/documents/content")
def document_content(path: str):
    if not OPENKNOWLEDGE_URL:
        raise HTTPException(status_code=503, detail="OpenKnowledge not configured")
    try:
        response = httpx.get(f"{OPENKNOWLEDGE_URL}/api/document", params={"docName": path}, timeout=5)
        response.raise_for_status()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    raw = response.json()
    content = raw.get("content", "")
    # Strip the embedded <!--aftermind-meta:...--> comment (see
    # providers/openknowledge/remote_client.py's _parse_meta) so the
    # viewer shows the readable markdown, not the lossless JSON blob.
    if content.startswith("<!--aftermind-meta:"):
        end = content.find("-->")
        content = content[end + 3 :].lstrip("\n") if end != -1 else content
    return {"markdown": content}


def _document_count(scope_key: Optional[str]) -> dict:
    result = documents(scope_key)
    return {"total": len(result["documents"]), "available": result["available"]}


# ------------------------------------------------------- sessions/checkpoints

@app.get("/api/checkpoints")
def checkpoints(scope_key: Optional[str] = None, page: int = 1, page_size: int = 20):
    where = "WHERE scope_key = ?" if scope_key else ""
    params = (scope_key,) if scope_key else ()
    page = max(page, 1)
    page_size = max(min(page_size, 200), 1)
    offset = (page - 1) * page_size

    with _db() as con:
        total = con.execute(f"SELECT COUNT(*) FROM checkpoints {where}", params).fetchone()[0]
        # Newest-first for a paginated list (page 1 = most recent), but
        # the timeline view still wants chronological order — the
        # frontend reverses the page it renders as a timeline.
        rows = con.execute(
            f"SELECT * FROM checkpoints {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (*params, page_size, offset),
        ).fetchall()

    return {
        "checkpoints": [
            {
                "checkpoint_id": r["checkpoint_id"],
                "scope_key": r["scope_key"],
                "version": r["version"],
                "goal": r["goal"],
                "completed": _load_json(r["completed"], []),
                "current": r["current"],
                "blockers": _load_json(r["blockers"], []),
                "next_steps": _load_json(r["next_steps"], []),
                "reason": r["reason"],
                "created_at": r["created_at"],
            }
            for r in rows
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": max((total + page_size - 1) // page_size, 1),
    }


# --------------------------------------------------------------- recall trace

@app.post("/api/recall-preview")
def recall_preview(body: dict):
    """Runs a real /recall against the main Aftermind API, then attaches
    the matching /traces entry — the "why did I get this answer" view.
    Proxying (not re-implementing) so this reuses the actual tracer
    wired into core/facade.py, not a second copy of its logic."""
    scope_levels = body.get("scope_levels", {})
    text = body.get("text", "")

    try:
        recall_response = httpx.post(
            f"{AFTERMIND_API_URL}/recall", json={"scope": {"levels": scope_levels}, "text": text}, timeout=15
        )
        recall_response.raise_for_status()
        recall_result = recall_response.json()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Aftermind API unreachable: {exc}")

    trace = None
    try:
        traces_response = httpx.get(f"{AFTERMIND_API_URL}/traces", params={"operation": "recall", "limit": 1}, timeout=5)
        traces_response.raise_for_status()
        traces = traces_response.json().get("traces", [])
        trace = traces[0] if traces else None
    except Exception:
        pass

    return {"recall": recall_result, "trace": trace}


@app.get("/api/traces")
def traces_proxy(operation: Optional[str] = None, session_id: Optional[str] = None, limit: int = 50):
    """The ring buffer only supports `operation` + `limit` server-side
    (see apps/api/rest/observability.py) — session_id is filtered here,
    over-fetching when a session filter is requested since there's no
    way to push it down to the buffer itself."""
    try:
        fetch_limit = max(limit * 5, 200) if session_id else limit
        response = httpx.get(f"{AFTERMIND_API_URL}/traces", params={"operation": operation, "limit": fetch_limit}, timeout=5)
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Aftermind API unreachable: {exc}")

    if session_id:
        traces = [t for t in payload.get("traces", []) if _parse_scope_key(t.get("scope", "")).get("session_id") == session_id]
        payload = {"traces": traces[:limit]}
    return payload


@app.get("/api/sessions")
def sessions(scope_key: Optional[str] = None, limit: int = 500):
    """Distinct sessions seen in recent traces — project + session_id
    pairs, most recently active first. Powers the session filter/
    breakdown views; there is no persisted "sessions" table (sessions
    are execution-scope, stripped from durable memories/checkpoints by
    design — see AGENTS.md's scope-discipline section), so this is
    reconstructed from the trace ring buffer, which is the only place
    that scope level survives."""
    try:
        response = httpx.get(f"{AFTERMIND_API_URL}/traces", params={"limit": limit}, timeout=5)
        response.raise_for_status()
        traces = response.json().get("traces", [])
    except Exception:
        return {"sessions": []}

    seen: dict[tuple, dict] = {}
    for t in traces:
        levels = _parse_scope_key(t.get("scope", ""))
        session_id = levels.get("session_id")
        if not session_id:
            continue
        if scope_key and t.get("scope") != scope_key:
            continue
        key = (levels.get("project_id"), session_id)
        entry = seen.setdefault(
            key,
            {"project_id": levels.get("project_id"), "session_id": session_id, "operations": 0, "last_seen": t.get("started_at")},
        )
        entry["operations"] += 1
        if t.get("started_at", "") > entry["last_seen"]:
            entry["last_seen"] = t.get("started_at")

    return {"sessions": sorted(seen.values(), key=lambda s: s["last_seen"] or "", reverse=True)}


@app.get("/api/traces/{trace_id}")
def trace_proxy(trace_id: str):
    try:
        response = httpx.get(f"{AFTERMIND_API_URL}/traces/{trace_id}", timeout=5)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail="trace not found")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Aftermind API unreachable: {exc}")


@app.get("/api/health")
def health():
    return {"status": "ok", "database": os.path.exists(DATABASE_PATH), "aftermind_api": AFTERMIND_API_URL}


app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("EXPLORER_PORT", 8010)))
