const state = { scope: "", scopes: [], view: "overview" };
const main = document.getElementById("main");

async function api(path, opts) {
  const res = await fetch(path, opts);
  if (!res.ok) throw new Error(`${path} -> ${res.status}`);
  return res.json();
}

function fmtTime(iso) {
  if (!iso) return "—";
  try { return new Date(iso).toLocaleString(); } catch { return iso; }
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function statusBadge(status) {
  return `<span class="badge ${esc(status)}">${esc(status)}</span>`;
}

function qs(params) {
  const clean = Object.fromEntries(Object.entries(params).filter(([, v]) => v !== "" && v != null));
  return new URLSearchParams(clean).toString();
}

// ---------------------------------------------------------------- scopes

async function loadScopes() {
  const data = await api("/api/scopes");
  state.scopes = data.scopes;
  const select = document.getElementById("scope-select");
  select.innerHTML = '<option value="">All scopes</option>' + data.scopes
    .map((s) => `<option value="${esc(s.scope_key)}">${esc(labelForScope(s))}</option>`)
    .join("");
  select.value = state.scope;
}

function labelForScope(s) {
  const levels = s.scope_levels || {};
  const parts = [levels.project_id, levels.repository_id ? null : null].filter(Boolean);
  const name = levels.project_id || s.scope_key;
  return `${name} · ${s.memory_count} memories`;
}

// --------------------------------------------------------------- overview

async function renderOverview() {
  main.innerHTML = `<div class="spinner">Loading overview…</div>`;
  const data = await api(`/api/overview?${qs({ scope_key: state.scope })}`);
  const status = data.lifecycle_status || {};

  main.innerHTML = `
    <h1>Overview</h1>
    <div class="subtitle">Brain health at a glance${state.scope ? " — scope: " + esc(state.scope) : ""}</div>

    <div class="grid grid-4">
      <div class="card">
        <div class="label">Memories</div>
        <div class="value">${data.memories.total}</div>
        <div class="sub">${data.memories.live} live · ${data.memories.superseded} superseded</div>
      </div>
      <div class="card">
        <div class="label">Relationships</div>
        <div class="value">${data.relationships.available ? data.relationships.current : "—"}</div>
        <div class="sub">${data.relationships.available ? data.relationships.historical + " historical" : "Neo4j unavailable"}</div>
      </div>
      <div class="card">
        <div class="label">Knowledge Docs</div>
        <div class="value">${data.documents.available ? data.documents.total : "—"}</div>
        <div class="sub">${data.documents.available ? "OpenKnowledge" : "OpenKnowledge unavailable"}</div>
      </div>
      <div class="card">
        <div class="label">Checkpoints</div>
        <div class="value">${data.checkpoints}</div>
        <div class="sub">${data.latest_checkpoint ? "v" + (data.checkpoints) + " latest" : "none yet"}</div>
      </div>
    </div>

    <div class="section">
      <div class="section-title">Lifecycle status breakdown</div>
      <div class="grid grid-4">
        ${["active", "decayed", "archived", "expired"].map((s) => `
          <div class="card">
            <div class="label">${s}</div>
            <div class="value small">${status[s] || 0}</div>
          </div>
        `).join("")}
      </div>
    </div>

    ${data.latest_checkpoint ? `
    <div class="section">
      <div class="section-title">Where things stand</div>
      <div class="card">
        <div class="value small">${esc(data.latest_checkpoint.goal || "(no goal recorded)")}</div>
        <div class="sub" style="margin-top:8px;">${esc(data.latest_checkpoint.current || "")}</div>
        ${data.latest_checkpoint.next_steps.length ? `<div class="sub" style="margin-top:8px;">Next: ${data.latest_checkpoint.next_steps.map(esc).join("; ")}</div>` : ""}
        <div class="mono" style="margin-top:10px;">${fmtTime(data.latest_checkpoint.created_at)}</div>
      </div>
    </div>` : ""}
  `;
}

// ----------------------------------------------------------------- ledger

async function renderLedger() {
  main.innerHTML = `<div class="spinner">Loading memory ledger…</div>`;
  const data = await api(`/api/memories?${qs({ scope_key: state.scope, limit: 300 })}`);

  main.innerHTML = `
    <h1>Memory Ledger</h1>
    <div class="subtitle">Every atomic memory in SQLite — status, type, confidence, provenance</div>
    <div class="filters">
      <input id="ledger-search" placeholder="Filter by content…" />
      <select id="ledger-status">
        <option value="">All statuses</option>
        <option value="active">active</option>
        <option value="decayed">decayed</option>
        <option value="archived">archived</option>
        <option value="expired">expired</option>
      </select>
    </div>
    <table>
      <thead><tr><th>Content</th><th>Type</th><th>Status</th><th>Conf.</th><th>Accessed</th><th>Updated</th><th></th></tr></thead>
      <tbody id="ledger-rows"></tbody>
    </table>
  `;

  const rows = data.memories;
  const renderRows = () => {
    const search = document.getElementById("ledger-search").value.toLowerCase();
    const statusFilter = document.getElementById("ledger-status").value;
    const filtered = rows.filter((m) =>
      (!search || m.content.toLowerCase().includes(search)) &&
      (!statusFilter || m.status === statusFilter)
    );
    document.getElementById("ledger-rows").innerHTML = filtered.length
      ? filtered.map((m) => `
        <tr>
          <td class="content-cell">${esc(m.content)}${m.superseded_by ? `<div class="mono" style="margin-top:4px;">→ superseded by ${esc(m.superseded_by.slice(0, 8))}</div>` : ""}</td>
          <td class="mono">${esc(m.memory_type)}</td>
          <td>${statusBadge(m.superseded_by ? "superseded" : m.status)}</td>
          <td class="mono">${m.confidence.toFixed(2)}</td>
          <td class="mono">${m.access_count ?? 0}×</td>
          <td class="mono">${fmtTime(m.updated_at)}</td>
          <td><a class="link" data-history="${esc(m.memory_id)}">history</a></td>
        </tr>
      `).join("")
      : `<tr><td colspan="7" class="empty-state">No memories match.</td></tr>`;

    document.querySelectorAll("[data-history]").forEach((el) => {
      el.addEventListener("click", () => showHistory(el.dataset.history));
    });
  };

  document.getElementById("ledger-search").addEventListener("input", renderRows);
  document.getElementById("ledger-status").addEventListener("change", renderRows);
  renderRows();
}

async function showHistory(memoryId) {
  const data = await api(`/api/memories/${memoryId}/history`);
  alert(
    `Memory ${memoryId}\n\nSupersedes (older facts this replaced): ${data.supersedes.join(", ") || "none"}\n\n` +
    `Superseded by (chain forward): ${data.superseded_chain.join(" → ") || "still current"}`
  );
}

// ------------------------------------------------------------------ graph

async function renderGraph() {
  main.innerHTML = `<div class="spinner">Loading knowledge graph…</div>`;
  const data = await api(`/api/graph?${qs({ scope_key: state.scope })}`);

  main.innerHTML = `
    <h1>Knowledge Graph</h1>
    <div class="subtitle">Neo4j relationships${state.scope ? " for this scope" : " (all scopes)"}</div>
    ${!data.available ? `<div class="empty-state">Neo4j is not reachable right now. ${esc(data.error || "")}</div>` :
      !data.nodes.length ? `<div class="empty-state">No relationships yet for this scope.</div>` : `
      <div id="graph-canvas-wrap"><svg id="graph-svg" width="100%" height="560"></svg></div>
      <div class="legend">
        <span><span class="swatch" style="background:#7c9eff;"></span> current relationship</span>
        <span><span class="swatch" style="background:#565f75;"></span> historical (superseded)</span>
      </div>
    `}
  `;

  if (data.available && data.nodes.length) drawGraph(data.nodes, data.edges);
}

function drawGraph(nodes, edges) {
  const svg = d3.select("#graph-svg");
  const width = document.getElementById("graph-canvas-wrap").clientWidth;
  const height = 560;
  svg.attr("viewBox", [0, 0, width, height]);

  const nodeData = nodes.map((n) => ({ ...n }));
  const linkData = edges.map((e) => ({ source: e.source, target: e.target, relation: e.relation, historical: e.historical }));

  const simulation = d3.forceSimulation(nodeData)
    .force("link", d3.forceLink(linkData).id((d) => d.id).distance(110).strength(0.5))
    .force("charge", d3.forceManyBody().strength(-260))
    .force("center", d3.forceCenter(width / 2, height / 2))
    .force("collide", d3.forceCollide(36));

  svg.append("defs").append("marker")
    .attr("id", "arrow").attr("viewBox", "0 -5 10 10").attr("refX", 22).attr("refY", 0)
    .attr("markerWidth", 6).attr("markerHeight", 6).attr("orient", "auto")
    .append("path").attr("d", "M0,-5L10,0L0,5").attr("fill", "#4a5266");

  const link = svg.append("g").selectAll("line")
    .data(linkData).join("line")
    .attr("stroke", (d) => (d.historical ? "#3a3f4d" : "#3d4a7a"))
    .attr("stroke-dasharray", (d) => (d.historical ? "4,3" : null))
    .attr("stroke-width", 1.6)
    .attr("marker-end", "url(#arrow)");

  const linkLabel = svg.append("g").selectAll("text")
    .data(linkData).join("text")
    .attr("font-size", 9)
    .attr("fill", "#8b93a7")
    .text((d) => d.relation);

  const node = svg.append("g").selectAll("circle")
    .data(nodeData).join("circle")
    .attr("r", 8)
    .attr("fill", "#7c9eff")
    .attr("stroke", "#0b0d12")
    .attr("stroke-width", 2)
    .call(drag(simulation));

  const label = svg.append("g").selectAll("text")
    .data(nodeData).join("text")
    .attr("font-size", 12)
    .attr("font-weight", 600)
    .attr("fill", "#e8eaf0")
    .attr("dx", 12)
    .attr("dy", 4)
    .text((d) => d.label);

  simulation.on("tick", () => {
    link.attr("x1", (d) => d.source.x).attr("y1", (d) => d.source.y).attr("x2", (d) => d.target.x).attr("y2", (d) => d.target.y);
    linkLabel.attr("x", (d) => (d.source.x + d.target.x) / 2).attr("y", (d) => (d.source.y + d.target.y) / 2);
    node.attr("cx", (d) => d.x).attr("cy", (d) => d.y);
    label.attr("x", (d) => d.x).attr("y", (d) => d.y);
  });

  function drag(sim) {
    function started(event) { if (!event.active) sim.alphaTarget(0.3).restart(); event.subject.fx = event.subject.x; event.subject.fy = event.subject.y; }
    function dragged(event) { event.subject.fx = event.x; event.subject.fy = event.y; }
    function ended(event) { if (!event.active) sim.alphaTarget(0); event.subject.fx = null; event.subject.fy = null; }
    return d3.drag().on("start", started).on("drag", dragged).on("end", ended);
  }
}

// ------------------------------------------------------------------- docs

async function renderDocs() {
  main.innerHTML = `<div class="spinner">Loading knowledge documents…</div>`;
  const data = await api(`/api/documents?${qs({ scope_key: state.scope })}`);

  main.innerHTML = `
    <h1>Knowledge</h1>
    <div class="subtitle">Consolidated, human-readable pages in OpenKnowledge</div>
    ${!data.available ? `<div class="empty-state">OpenKnowledge is not reachable right now.</div>` :
      !data.documents.length ? `<div class="empty-state">No consolidated documents yet for this scope.</div>` :
      `<div class="doc-list">${data.documents.map((d) => `
        <div class="doc-row" data-path="${esc(d.path)}">
          <div><div class="doc-title">${esc(d.title)}</div><div class="doc-path">${esc(d.path)}</div></div>
          <div class="mono muted">${fmtTime(d.updated_at)}</div>
        </div>`).join("")}</div>
      <div id="doc-content"></div>`}
  `;

  document.querySelectorAll("[data-path]").forEach((el) => {
    el.addEventListener("click", async () => {
      const content = await api(`/api/documents/content?path=${encodeURIComponent(el.dataset.path)}`);
      const body = content.markdown || content.content || JSON.stringify(content, null, 2);
      document.getElementById("doc-content").innerHTML = `<div class="doc-content">${esc(body)}</div>`;
    });
  });
}

// --------------------------------------------------------------- sessions

async function renderSessions() {
  main.innerHTML = `<div class="spinner">Loading checkpoint timeline…</div>`;
  const data = await api(`/api/checkpoints?${qs({ scope_key: state.scope })}`);

  main.innerHTML = `
    <h1>Sessions &amp; Checkpoints</h1>
    <div class="subtitle">How work continued across sessions (Hermes, Claude Code, ...)</div>
    ${!data.checkpoints.length ? `<div class="empty-state">No checkpoints recorded yet for this scope.</div>` :
      `<div class="timeline">${data.checkpoints.map((c) => `
        <div class="timeline-item">
          <div class="tl-header">
            <span class="tl-version">v${c.version}</span>
            <span class="tl-reason">${esc(c.reason)}</span>
            <span class="tl-time">${fmtTime(c.created_at)}</span>
          </div>
          <div class="tl-goal">${esc(c.goal || "(no goal)")}</div>
          <div class="tl-current">${esc(c.current || "")}</div>
          ${c.completed.length ? `<div class="tl-next">Completed: ${c.completed.map(esc).join("; ")}</div>` : ""}
          ${c.next_steps.length ? `<div class="tl-next">Next: ${c.next_steps.map(esc).join("; ")}</div>` : ""}
        </div>
      `).join("")}</div>`}
  `;
}

// ----------------------------------------------------------------- trace

async function renderTrace() {
  main.innerHTML = `
    <h1>Recall Trace</h1>
    <div class="subtitle">For any question, see exactly what was retrieved, ranked, and injected — and where it fell short</div>
    <div class="trace-box">
      <div class="trace-query-row">
        <input id="trace-query" placeholder="Ask a question, e.g. What database does Aftermind use?" />
        <button id="trace-run">Run</button>
      </div>
    </div>
    <div id="trace-result"></div>
    <div class="section">
      <div class="section-title">Recent traces</div>
      <div id="recent-traces"><div class="spinner">Loading…</div></div>
    </div>
  `;

  document.getElementById("trace-run").addEventListener("click", runTraceQuery);
  document.getElementById("trace-query").addEventListener("keydown", (e) => { if (e.key === "Enter") runTraceQuery(); });

  loadRecentTraces();
}

async function loadRecentTraces() {
  try {
    const data = await api("/api/traces?operation=recall&limit=15");
    const box = document.getElementById("recent-traces");
    if (!data.traces.length) { box.innerHTML = `<div class="empty-state">No recall traces yet — run a query above, or ask via Hermes/Claude Code.</div>`; return; }
    box.innerHTML = `<table>
      <thead><tr><th>Time</th><th>Scope</th><th>Sources</th><th>Latency</th><th></th></tr></thead>
      <tbody>${data.traces.map((t) => `
        <tr>
          <td class="mono">${fmtTime(t.started_at)}</td>
          <td class="mono">${esc(t.scope || "—")}</td>
          <td class="mono">${esc((t.recall_sources || []).join(", ") || "—")}</td>
          <td class="mono">${t.latency_ms ? t.latency_ms.toFixed(0) + " ms" : "—"}</td>
          <td><a class="link" data-trace="${esc(t.trace_id)}">view</a></td>
        </tr>`).join("")}</tbody>
    </table>`;
    document.querySelectorAll("[data-trace]").forEach((el) => el.addEventListener("click", () => showTrace(el.dataset.trace)));
  } catch {
    document.getElementById("recent-traces").innerHTML = `<div class="empty-state">Aftermind API unreachable.</div>`;
  }
}

async function runTraceQuery() {
  const text = document.getElementById("trace-query").value.trim();
  if (!text) return;
  const resultBox = document.getElementById("trace-result");
  resultBox.innerHTML = `<div class="spinner">Running recall…</div>`;

  const scopeLevels = {};
  if (state.scope) {
    const scopeMeta = state.scopes.find((s) => s.scope_key === state.scope);
    Object.assign(scopeLevels, scopeMeta ? scopeMeta.scope_levels : {});
  }

  try {
    const data = await api("/api/recall-preview", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, scope_levels: scopeLevels }),
    });
    renderTraceResult(data);
  } catch (e) {
    resultBox.innerHTML = `<div class="empty-state">Failed: ${esc(e.message)}</div>`;
  }
}

async function showTrace(traceId) {
  const trace = await api(`/api/traces/${traceId}`);
  renderTraceResult({ recall: null, trace });
}

function renderTraceResult({ recall, trace }) {
  const box = document.getElementById("trace-result");
  const stages = trace ? [
    { name: "SQLite", status: trace.sqlite_write || trace.sqlite_search || "ok" },
    { name: "Neo4j", status: trace.neo4j_sync || trace.graph_search || "skipped" },
    { name: "OpenKnowledge", status: trace.openknowledge_sync || trace.openknowledge_search || "skipped" },
    { name: "Checkpoint", status: trace.checkpoint_created != null ? (trace.checkpoint_created ? "ok" : "skipped") : "skipped" },
  ] : [];

  box.innerHTML = `
    ${trace ? `
    <div class="pipeline">
      ${stages.map((s) => `
        <div class="pipeline-stage">
          <div class="stage-name">${s.name}</div>
          <div class="stage-status ${esc(s.status)}">${esc(s.status)}</div>
        </div>
      `).join("")}
    </div>
    <div class="grid grid-4" style="margin-bottom:16px;">
      <div class="card"><div class="label">LLM calls</div><div class="value small">${trace.llm_calls ?? "—"}</div></div>
      <div class="card"><div class="label">LLM latency</div><div class="value small">${trace.llm_latency_ms ? trace.llm_latency_ms.toFixed(0) + " ms" : "—"}</div></div>
      <div class="card"><div class="label">Total latency</div><div class="value small">${trace.latency_ms ? trace.latency_ms.toFixed(0) + " ms" : "—"}</div></div>
      <div class="card"><div class="label">Trace id</div><div class="value small mono">${esc((trace.trace_id || "").slice(0, 12))}</div></div>
    </div>` : `<div class="empty-state">No trace metadata available for this call (older Aftermind version?).</div>`}

    ${recall ? `
    <div class="section-title">Injected context (what the LLM actually saw)</div>
    <div class="context-output">${esc(recall.context || "(empty — nothing relevant found)")}</div>
    <div class="section-title" style="margin-top:16px;">Ranked memories returned</div>
    <table>
      <thead><tr><th>Content</th><th>Type</th><th>Confidence</th></tr></thead>
      <tbody>${(recall.memories || []).map((m) => `
        <tr><td class="content-cell">${esc(m.content)}</td><td class="mono">${esc(m.memory_type)}</td><td class="mono">${m.confidence.toFixed(2)}</td></tr>
      `).join("") || `<tr><td colspan="3" class="empty-state">Nothing retrieved.</td></tr>`}</tbody>
    </table>` : ""}
  `;
}

// ----------------------------------------------------------------- router

const renderers = { overview: renderOverview, ledger: renderLedger, graph: renderGraph, docs: renderDocs, sessions: renderSessions, trace: renderTrace };

function setView(view) {
  state.view = view;
  document.querySelectorAll("#nav button").forEach((b) => b.classList.toggle("active", b.dataset.view === view));
  renderers[view]();
}

document.querySelectorAll("#nav button").forEach((b) => b.addEventListener("click", () => setView(b.dataset.view)));
document.getElementById("scope-select").addEventListener("change", (e) => { state.scope = e.target.value; renderers[state.view](); });

loadScopes().then(() => setView("overview"));
