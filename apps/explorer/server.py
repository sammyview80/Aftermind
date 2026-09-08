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


# ---------------------------------------------------------------- scopes

@app.get("/api/scopes")
def list_scopes():
    """Every distinct scope_key that has ever had a memory, most
    recently active first — powers the scope picker in the UI."""
    with _db() as con:
        rows = con.execute(
            "SELECT scope_key, scope_levels, MAX(updated_at) AS last_activity, COUNT(*) AS memory_count "
            "FROM memories GROUP BY scope_key ORDER BY last_activity DESC"
        ).fetchall()
    return {
        "scopes": [
            {
                "scope_key": r["scope_key"],
                "scope_levels": _load_json(r["scope_levels"], {}),
                "last_activity": r["last_activity"],
                "memory_count": r["memory_count"],
            }
            for r in rows
        ]
    }


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
def list_memories(scope_key: Optional[str] = None, status: Optional[str] = None, limit: int = 200):
    where_clauses = []
    params: list = []
    if scope_key:
        where_clauses.append("m.scope_key = ?")
        params.append(scope_key)
    where = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

    with _db() as con:
        rows = con.execute(
            f"SELECT m.* FROM memories m {where} ORDER BY m.updated_at DESC LIMIT ?", (*params, limit)
        ).fetchall()
        lifecycle_by_id = {
            r["memory_id"]: r
            for r in con.execute("SELECT * FROM lifecycle").fetchall()
        }

    memories = [_memory_row(row, lifecycle_by_id.get(row["memory_id"])) for row in rows]
    if status:
        memories = [m for m in memories if m["status"] == status]
    return {"memories": memories}


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
def checkpoints(scope_key: Optional[str] = None, limit: int = 100):
    where = "WHERE scope_key = ?" if scope_key else ""
    params = (scope_key,) if scope_key else ()
    with _db() as con:
        rows = con.execute(
            f"SELECT * FROM checkpoints {where} ORDER BY created_at ASC LIMIT ?", (*params, limit)
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
        ]
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
def traces_proxy(operation: Optional[str] = None, limit: int = 50):
    try:
        response = httpx.get(f"{AFTERMIND_API_URL}/traces", params={"operation": operation, "limit": limit}, timeout=5)
        response.raise_for_status()
        return response.json()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Aftermind API unreachable: {exc}")


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
