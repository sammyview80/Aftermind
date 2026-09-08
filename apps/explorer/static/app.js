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

const STATUS_LABELS = { active: "Active", decayed: "Fading", archived: "Set aside", expired: "Expired", forgotten: "Removed", superseded: "Replaced" };

function statusBadge(status) {
  return `<span class="badge ${esc(status)}">${esc(STATUS_LABELS[status] || status)}</span>`;
}

function confidenceLabel(c) {
  const pct = Math.round(c * 100);
  const word = c >= 0.85 ? "Very sure" : c >= 0.6 ? "Fairly sure" : "Unsure";
  return `<span title="${pct}% confidence">${word}</span>`;
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
  select.innerHTML = '<option value="">All projects</option>' + data.scopes
    .map((s) => `<option value="${esc(s.scope_key)}">${esc(labelForScope(s))}</option>`)
    .join("");
  select.value = state.scope;
}

function labelForScope(s) {
  const levels = s.scope_levels || {};
  const name = levels.project_id || s.scope_key;
  const parts = [];
  if (s.memory_count) parts.push(`${s.memory_count} ${s.memory_count === 1 ? "memory" : "memories"}`);
  if (s.checkpoint_count) parts.push(`${s.checkpoint_count} ${s.checkpoint_count === 1 ? "checkpoint" : "checkpoints"}`);
  return `${name}${parts.length ? " (" + parts.join(", ") + ")" : ""}`;
}

// --------------------------------------------------------------- overview

async function renderOverview() {
  main.innerHTML = `<div class="spinner">Loading overview…</div>`;
  const data = await api(`/api/overview?${qs({ scope_key: state.scope })}`);
  const status = data.lifecycle_status || {};

  const activeCount = status.active || 0;
  const needsAttention = (status.decayed || 0) + (status.expired || 0);

  main.innerHTML = `
    <h1>Overview</h1>
    <div class="subtitle">A quick health check of your AI's memory${state.scope ? " for this project" : " across every project"} — how much it remembers, how it's organized, and whether anything needs cleaning up.</div>

    <div class="summary-sentence">
      <span class="ok-emoji">${needsAttention === 0 ? "✅" : "🧹"}</span>
      Your assistant currently has <b>${data.memories.total} things it remembers</b>
      (${activeCount} actively used, ${data.memories.superseded} replaced by newer facts)${
        data.relationships.available ? `, understands <b>${data.relationships.current} connections</b> between things` : ""
      }${data.documents.available && data.documents.total ? `, and has written up <b>${data.documents.total} summary page${data.documents.total === 1 ? "" : "s"}</b> of organized knowledge` : ""}.
      ${needsAttention > 0 ? `${needsAttention} memor${needsAttention === 1 ? "y is" : "ies are"} old and rarely used — worth a look in "What it remembers".` : "Everything looks healthy."}
    </div>

    <div class="grid grid-4">
      <div class="card">
        <div class="label">Total memories <span class="tip" title="Every distinct fact your assistant has learned and saved, across all your conversations.">?</span></div>
        <div class="value">${data.memories.total}</div>
        <div class="sub">${data.memories.live} still current · ${data.memories.superseded} replaced by something newer</div>
      </div>
      <div class="card">
        <div class="label">Connections <span class="tip" title="How facts relate to each other — e.g. 'Billing uses RabbitMQ'. Powers the Knowledge Graph view.">?</span></div>
        <div class="value">${data.relationships.available ? data.relationships.current : "—"}</div>
        <div class="sub">${data.relationships.available ? data.relationships.historical + " older connections kept for history" : "Not connected right now"}</div>
      </div>
      <div class="card">
        <div class="label">Knowledge pages <span class="tip" title="Readable summary documents your assistant writes once it notices several related facts, so it doesn't have to re-derive them every time.">?</span></div>
        <div class="value">${data.documents.available ? data.documents.total : "—"}</div>
        <div class="sub">${data.documents.available ? "Organized write-ups, not raw facts" : "Not connected right now"}</div>
      </div>
      <div class="card">
        <div class="label">Checkpoints <span class="tip" title="Snapshots of 'what we were working on' saved between sessions, so a new conversation can pick up where the last one left off.">?</span></div>
        <div class="value">${data.checkpoints}</div>
        <div class="sub">${data.latest_checkpoint ? "Progress saved " + data.checkpoints + " times" : "No progress saved yet"}</div>
      </div>
    </div>

    <div class="section">
      <div class="section-title">Memory health breakdown</div>
      <div class="info-banner">
        <span class="info-icon">💡</span>
        <div>Memories aren't just "there" or "gone" — they age like anything else. <b>Active</b> = used recently. <b>Fading</b> = hasn't come up in a while. <b>Set aside</b> = replaced or cleaned up automatically, but never deleted, so history is never lost.</div>
      </div>
      <div class="grid grid-4">
        <div class="card"><div class="label">Active</div><div class="value small">${status.active || 0}</div><div class="sub">used recently</div></div>
        <div class="card"><div class="label">Fading</div><div class="value small">${status.decayed || 0}</div><div class="sub">hasn't come up lately</div></div>
        <div class="card"><div class="label">Set aside</div><div class="value small">${(status.archived || 0) + (status.expired || 0)}</div><div class="sub">replaced or cleaned up</div></div>
        <div class="card"><div class="label">Removed</div><div class="value small">${status.forgotten || 0}</div><div class="sub">explicitly deleted</div></div>
      </div>
    </div>

    ${data.latest_checkpoint ? `
    <div class="section">
      <div class="section-title">What it's currently working on</div>
      <div class="card">
        <div class="value small">${esc(data.latest_checkpoint.goal || "(no goal recorded)")}</div>
        <div class="sub" style="margin-top:8px;">${esc(data.latest_checkpoint.current || "")}</div>
        ${data.latest_checkpoint.next_steps.length ? `<div class="sub" style="margin-top:8px;">Coming up next: ${data.latest_checkpoint.next_steps.map(esc).join("; ")}</div>` : ""}
        <div class="mono" style="margin-top:10px;">Last updated ${fmtTime(data.latest_checkpoint.created_at)}</div>
      </div>
    </div>` : ""}
  `;
}

// ----------------------------------------------------------------- ledger

const ledgerState = { page: 1, pageSize: 25, search: "", status: "", memoryType: "" };
let ledgerSearchDebounce = null;

function paginationControls(id, page, totalPages, total) {
  return `
    <div class="pagination" id="${id}">
      <button data-page="prev" ${page <= 1 ? "disabled" : ""}>‹ Prev</button>
      <span class="mono">Page ${page} of ${totalPages} · ${total} total</span>
      <button data-page="next" ${page >= totalPages ? "disabled" : ""}>Next ›</button>
    </div>
  `;
}

async function renderLedger() {
  main.innerHTML = `<div class="spinner">Loading what it remembers…</div>`;
  const types = await api("/api/memory-types");

  main.innerHTML = `
    <h1>What it remembers</h1>
    <div class="subtitle">Every individual fact your assistant has saved — search it, filter it, and see why each one is where it is.</div>
    <div class="filters">
      <input id="ledger-search" placeholder="Search what it remembers…" value="${esc(ledgerState.search)}" />
      <select id="ledger-status" title="Filter by how 'fresh' a memory is">
        <option value="">Any freshness</option>
        <option value="active" ${ledgerState.status === "active" ? "selected" : ""}>Active (used recently)</option>
        <option value="decayed" ${ledgerState.status === "decayed" ? "selected" : ""}>Fading (unused a while)</option>
        <option value="archived" ${ledgerState.status === "archived" ? "selected" : ""}>Set aside</option>
        <option value="expired" ${ledgerState.status === "expired" ? "selected" : ""}>Expired</option>
        <option value="forgotten" ${ledgerState.status === "forgotten" ? "selected" : ""}>Removed</option>
      </select>
      <select id="ledger-type" title="Filter by kind of memory">
        <option value="">Any kind</option>
        ${types.memory_types.map((t) => `<option value="${esc(t)}" ${ledgerState.memoryType === t ? "selected" : ""}>${esc(t)}</option>`).join("")}
      </select>
      <select id="ledger-page-size">
        ${[10, 25, 50, 100].map((n) => `<option value="${n}" ${ledgerState.pageSize === n ? "selected" : ""}>Show ${n} at a time</option>`).join("")}
      </select>
    </div>
    <table>
      <thead><tr>
        <th>What it remembers</th>
        <th>Kind</th>
        <th title="How fresh/current this memory is">Freshness</th>
        <th title="How sure the assistant is this is accurate">Sure?</th>
        <th title="Number of times this memory was actually used to answer something">Used</th>
        <th>Last updated</th>
        <th></th>
      </tr></thead>
      <tbody id="ledger-rows"><tr><td colspan="7" class="empty-state">Loading…</td></tr></tbody>
    </table>
    <div id="ledger-pagination"></div>
  `;

  document.getElementById("ledger-search").addEventListener("input", (e) => {
    clearTimeout(ledgerSearchDebounce);
    ledgerSearchDebounce = setTimeout(() => { ledgerState.search = e.target.value; ledgerState.page = 1; loadLedgerPage(); }, 250);
  });
  document.getElementById("ledger-status").addEventListener("change", (e) => { ledgerState.status = e.target.value; ledgerState.page = 1; loadLedgerPage(); });
  document.getElementById("ledger-type").addEventListener("change", (e) => { ledgerState.memoryType = e.target.value; ledgerState.page = 1; loadLedgerPage(); });
  document.getElementById("ledger-page-size").addEventListener("change", (e) => { ledgerState.pageSize = Number(e.target.value); ledgerState.page = 1; loadLedgerPage(); });

  loadLedgerPage();
}

async function loadLedgerPage() {
  const data = await api(`/api/memories?${qs({
    scope_key: state.scope, status: ledgerState.status, memory_type: ledgerState.memoryType,
    search: ledgerState.search, page: ledgerState.page, page_size: ledgerState.pageSize,
  })}`);

  document.getElementById("ledger-rows").innerHTML = data.memories.length
    ? data.memories.map((m) => `
      <tr>
        <td class="content-cell">${esc(m.content)}${m.superseded_by ? `<div class="mono" style="margin-top:4px;">→ replaced by a newer memory</div>` : ""}</td>
        <td class="mono">${esc(m.memory_type)}</td>
        <td>${statusBadge(m.superseded_by ? "superseded" : m.status)}</td>
        <td>${confidenceLabel(m.confidence)}</td>
        <td class="mono">${m.access_count ? m.access_count + "×" : "never"}</td>
        <td class="mono">${fmtTime(m.updated_at)}</td>
        <td><a class="link" data-history="${esc(m.memory_id)}">see history</a></td>
      </tr>
    `).join("")
    : `<tr><td colspan="7" class="empty-state">Nothing matches your search — try clearing a filter.</td></tr>`;

  document.querySelectorAll("[data-history]").forEach((el) => el.addEventListener("click", () => showHistory(el.dataset.history)));

  document.getElementById("ledger-pagination").innerHTML = paginationControls("ledger-pg", data.page, data.total_pages, data.total);
  document.querySelectorAll("#ledger-pagination button").forEach((btn) => {
    btn.addEventListener("click", () => {
      ledgerState.page += btn.dataset.page === "next" ? 1 : -1;
      loadLedgerPage();
    });
  });
}

async function showHistory(memoryId) {
  const data = await api(`/api/memories/${memoryId}/history`);
  const before = data.supersedes.length ? `It replaced ${data.supersedes.length} older ${data.supersedes.length === 1 ? "memory" : "memories"}.` : "It didn't replace anything — this was new information.";
  const after = data.superseded_chain.length ? `It has since been replaced ${data.superseded_chain.length} time(s) by newer facts.` : "It's still the current, up-to-date answer.";
  alert(`Where this memory came from:\n\n${before}\n${after}`);
}

// ------------------------------------------------------------------ graph

async function renderGraph() {
  main.innerHTML = `<div class="spinner">Mapping out connections…</div>`;
  const data = await api(`/api/graph?${qs({ scope_key: state.scope })}`);

  main.innerHTML = `
    <h1>How things connect</h1>
    <div class="subtitle">A map of how the things your assistant knows about relate to each other — click any bubble to see what it's connected to.</div>
    ${!data.available ? `<div class="empty-state">Can't reach the connections database right now. Nothing is lost — just not viewable at this moment.</div>` :
      !data.nodes.length ? `<div class="empty-state">No connections yet — once your assistant learns a few related facts, they'll show up here as a map.</div>` : `
      <div class="info-banner">
        <span class="info-icon">🖱️</span>
        <div><b>Try it:</b> click a bubble to spotlight what it connects to. Scroll or use the buttons to zoom in for detail. Drag empty space to move around, or click it to reset.</div>
      </div>
      <div class="graph-toolbar">
        <button id="graph-zoom-in">🔍 Zoom in</button>
        <button id="graph-zoom-out">🔎 Zoom out</button>
        <button id="graph-reset">↺ Reset view</button>
      </div>
      <div id="graph-canvas-wrap"><svg id="graph-svg" width="100%" height="560"></svg></div>
      <div class="legend">
        <span><span class="swatch" style="background:#7c9eff;"></span> Current connection</span>
        <span><span class="swatch" style="background:#565f75;"></span> Old connection (kept for history)</span>
        <span><span class="swatch" style="background:#c084fc;"></span> Selected</span>
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
  svg.selectAll("*").remove();

  const nodeData = nodes.map((n) => ({ ...n }));
  const linkData = edges.map((e) => ({ source: e.source, target: e.target, relation: e.relation, historical: e.historical }));

  const neighborsOf = (id) => {
    const set = new Set([id]);
    linkData.forEach((l) => {
      const s = l.source.id || l.source, t = l.target.id || l.target;
      if (s === id) set.add(t);
      if (t === id) set.add(s);
    });
    return set;
  };

  let focused = null;

  const zoomLayer = svg.append("g");

  const zoom = d3.zoom()
    .scaleExtent([0.2, 4])
    .on("zoom", (event) => zoomLayer.attr("transform", event.transform));
  svg.call(zoom);
  svg.on("click", () => setFocus(null)); // click background clears focus

  const simulation = d3.forceSimulation(nodeData)
    .force("link", d3.forceLink(linkData).id((d) => d.id).distance(110).strength(0.5))
    .force("charge", d3.forceManyBody().strength(-260))
    .force("center", d3.forceCenter(width / 2, height / 2))
    .force("collide", d3.forceCollide(36));

  zoomLayer.append("defs").append("marker")
    .attr("id", "arrow").attr("viewBox", "0 -5 10 10").attr("refX", 22).attr("refY", 0)
    .attr("markerWidth", 6).attr("markerHeight", 6).attr("orient", "auto")
    .append("path").attr("d", "M0,-5L10,0L0,5").attr("fill", "#4a5266");

  const link = zoomLayer.append("g").selectAll("line")
    .data(linkData).join("line")
    .attr("stroke", (d) => (d.historical ? "#3a3f4d" : "#3d4a7a"))
    .attr("stroke-dasharray", (d) => (d.historical ? "4,3" : null))
    .attr("stroke-width", 1.6)
    .attr("marker-end", "url(#arrow)");

  const linkLabel = zoomLayer.append("g").selectAll("text")
    .data(linkData).join("text")
    .attr("font-size", 9)
    .attr("fill", "#8b93a7")
    .text((d) => d.relation);

  const node = zoomLayer.append("g").selectAll("circle")
    .data(nodeData).join("circle")
    .attr("r", 8)
    .attr("fill", "#7c9eff")
    .attr("stroke", "#0b0d12")
    .attr("stroke-width", 2)
    .style("cursor", "pointer")
    .call(drag(simulation))
    .on("click", (event, d) => { event.stopPropagation(); setFocus(d.id); });

  const label = zoomLayer.append("g").selectAll("text")
    .data(nodeData).join("text")
    .attr("font-size", 12)
    .attr("font-weight", 600)
    .attr("fill", "#e8eaf0")
    .attr("dx", 12)
    .attr("dy", 4)
    .style("cursor", "pointer")
    .text((d) => d.label)
    .on("click", (event, d) => { event.stopPropagation(); setFocus(d.id); });

  function setFocus(id) {
    focused = focused === id ? null : id;
    if (!focused) {
      node.attr("fill", "#7c9eff").attr("opacity", 1);
      link.attr("opacity", (d) => (d.historical ? 0.5 : 0.85));
      linkLabel.attr("opacity", 1);
      label.attr("opacity", 1);
      return;
    }
    const neighbors = neighborsOf(focused);
    node.attr("fill", (d) => (d.id === focused ? "#c084fc" : neighbors.has(d.id) ? "#7c9eff" : "#3a3f4d"))
      .attr("opacity", (d) => (neighbors.has(d.id) ? 1 : 0.25));
    const linkTouches = (d) => (d.source.id || d.source) === focused || (d.target.id || d.target) === focused;
    link.attr("opacity", (d) => (linkTouches(d) ? 0.95 : 0.08));
    linkLabel.attr("opacity", (d) => (linkTouches(d) ? 1 : 0.08));
    label.attr("opacity", (d) => (neighbors.has(d.id) ? 1 : 0.2));
  }

  document.getElementById("graph-zoom-in").onclick = () => svg.transition().duration(200).call(zoom.scaleBy, 1.4);
  document.getElementById("graph-zoom-out").onclick = () => svg.transition().duration(200).call(zoom.scaleBy, 1 / 1.4);
  document.getElementById("graph-reset").onclick = () => {
    setFocus(null); focused = null;
    svg.transition().duration(300).call(zoom.transform, d3.zoomIdentity);
  };

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
  main.innerHTML = `<div class="spinner">Loading written knowledge…</div>`;
  const data = await api(`/api/documents?${qs({ scope_key: state.scope })}`);

  main.innerHTML = `
    <h1>Written knowledge</h1>
    <div class="subtitle">Once your assistant notices several related facts, it writes them up as a readable page — like a wiki it maintains on its own.</div>
    ${!data.available ? `<div class="empty-state">Can't reach the knowledge pages right now.</div>` :
      !data.documents.length ? `<div class="empty-state">No write-ups yet — these appear automatically once enough related facts pile up on one topic.</div>` :
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

const sessionsState = { page: 1, pageSize: 15 };

async function renderSessions() {
  main.innerHTML = `
    <h1>Work history</h1>
    <div class="subtitle">See how your assistant picked up where it left off, session after session — even across different conversations or tools.</div>
    <div class="section">
      <div class="section-title">Recent conversations</div>
      <div id="sessions-list"><div class="spinner">Loading…</div></div>
    </div>
    <div class="section">
      <div class="section-title">Progress over time${state.scope ? "" : " — across all projects, pick one above to narrow it down"}</div>
      <div class="info-banner">
        <span class="info-icon">📌</span>
        <div>Each entry below is a snapshot your assistant saved of "what we were doing" — so the next conversation (even a brand-new one) can continue instead of starting from scratch. This is tracked per <b>project</b>, not per individual conversation — by design, progress belongs to the project, not to any one chat.</div>
      </div>
      <div id="checkpoint-timeline"><div class="spinner">Loading…</div></div>
      <div id="checkpoint-pagination"></div>
    </div>
  `;
  loadSessionsList();
  loadCheckpointPage();
}

async function loadSessionsList() {
  try {
    const data = await api(`/api/sessions?${qs({ scope_key: state.scope })}`);
    const box = document.getElementById("sessions-list");
    box.innerHTML = data.sessions.length
      ? `<table><thead><tr><th>Project</th><th>Conversation</th><th>Things it did</th><th>Last active</th></tr></thead>
        <tbody>${data.sessions.map((s) => `
          <tr><td>${esc(s.project_id || "—")}</td><td class="mono">${esc(s.session_id.slice(0, 12))}</td><td class="mono">${s.operations}</td><td class="mono">${fmtTime(s.last_seen)}</td></tr>
        `).join("")}</tbody></table>`
      : `<div class="empty-state">No recent conversation activity yet.</div>`;
  } catch {
    document.getElementById("sessions-list").innerHTML = `<div class="empty-state">Can't reach Aftermind right now.</div>`;
  }
}

async function loadCheckpointPage() {
  const data = await api(`/api/checkpoints?${qs({ scope_key: state.scope, page: sessionsState.page, page_size: sessionsState.pageSize })}`);
  // Server returns newest-first for pagination; render each page as a chronological mini-timeline.
  const ordered = [...data.checkpoints].reverse();

  document.getElementById("checkpoint-timeline").innerHTML = ordered.length
    ? `<div class="timeline">${ordered.map((c) => `
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
    `).join("")}</div>`
    : `<div class="empty-state">No checkpoints recorded yet for this scope.</div>`;

  document.getElementById("checkpoint-pagination").innerHTML = paginationControls("cp-pg", data.page, data.total_pages, data.total);
  document.querySelectorAll("#checkpoint-pagination button").forEach((btn) => {
    btn.addEventListener("click", () => { sessionsState.page += btn.dataset.page === "next" ? 1 : -1; loadCheckpointPage(); });
  });
}

// ----------------------------------------------------------------- trace

async function renderTrace() {
  main.innerHTML = `
    <h1>Why this answer?</h1>
    <div class="subtitle">If your assistant ever gives a wrong or surprising answer, this is where you find out why — ask the same question here and see exactly what it looked up.</div>
    <div class="info-banner">
      <span class="info-icon">🔍</span>
      <div>Type any question below to see, step by step, where your assistant looked for the answer, what it found, and what it actually used to respond.</div>
    </div>
    <div class="trace-box">
      <div class="trace-query-row">
        <input id="trace-query" placeholder="Try: What database does Aftermind use?" />
        <button id="trace-run">Ask &amp; explain</button>
      </div>
    </div>
    <div id="trace-result"></div>
    <div class="section">
      <div class="section-title">Past questions</div>
      <div class="filters">
        <select id="trace-operation" title="What kind of activity to show">
          <option value="recall">Questions asked</option>
          <option value="observe">Facts learned</option>
          <option value="checkpoint">Progress saved</option>
          <option value="">Everything</option>
        </select>
        <select id="trace-session" title="Show only one conversation"><option value="">All conversations</option></select>
      </div>
      <div id="recent-traces"><div class="spinner">Loading…</div></div>
    </div>
  `;

  document.getElementById("trace-run").addEventListener("click", runTraceQuery);
  document.getElementById("trace-query").addEventListener("keydown", (e) => { if (e.key === "Enter") runTraceQuery(); });
  document.getElementById("trace-operation").addEventListener("change", loadRecentTraces);
  document.getElementById("trace-session").addEventListener("change", loadRecentTraces);

  loadSessionFilterOptions();
  loadRecentTraces();
}

async function loadSessionFilterOptions() {
  try {
    const data = await api(`/api/sessions?${qs({ scope_key: state.scope })}`);
    const select = document.getElementById("trace-session");
    select.innerHTML = '<option value="">All sessions</option>' + data.sessions
      .map((s) => `<option value="${esc(s.session_id)}">${esc((s.project_id || "?") + " · " + s.session_id.slice(0, 10))}</option>`).join("");
  } catch { /* best-effort */ }
}

async function loadRecentTraces() {
  const operation = document.getElementById("trace-operation")?.value ?? "recall";
  const sessionId = document.getElementById("trace-session")?.value ?? "";
  try {
    const data = await api(`/api/traces?${qs({ operation, session_id: sessionId, limit: 20 })}`);
    const box = document.getElementById("recent-traces");
    if (!data.traces.length) { box.innerHTML = `<div class="empty-state">No recall traces yet — run a query above, or ask via Hermes/Claude Code.</div>`; return; }
    box.innerHTML = `<table>
      <thead><tr><th>When</th><th>Looked in</th><th>How long it took</th><th></th></tr></thead>
      <tbody>${data.traces.map((t) => `
        <tr>
          <td class="mono">${fmtTime(t.started_at)}</td>
          <td class="mono">${esc((t.recall_sources || []).join(", ") || "—")}</td>
          <td class="mono">${t.latency_ms ? t.latency_ms.toFixed(0) + " ms" : "—"}</td>
          <td><a class="link" data-trace="${esc(t.trace_id)}">explain this</a></td>
        </tr>`).join("")}</tbody>
    </table>`;
    document.querySelectorAll("[data-trace]").forEach((el) => el.addEventListener("click", () => showTrace(el.dataset.trace)));
  } catch {
    document.getElementById("recent-traces").innerHTML = `<div class="empty-state">Can't reach Aftermind right now.</div>`;
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

const STAGE_STATUS_WORDS = { ok: "Found it", failed: "Had a problem", pending: "Still trying", skipped: "Didn't need to" };

function renderTraceResult({ recall, trace }) {
  const box = document.getElementById("trace-result");
  const stages = trace ? [
    { name: "Saved facts (SQLite)", status: trace.sqlite_write || trace.sqlite_search || "ok" },
    { name: "Connections (Neo4j)", status: trace.neo4j_sync || trace.graph_search || "skipped" },
    { name: "Written knowledge", status: trace.openknowledge_sync || trace.openknowledge_search || "skipped" },
    { name: "Saved progress", status: trace.checkpoint_created != null ? (trace.checkpoint_created ? "ok" : "skipped") : "skipped" },
  ] : [];

  box.innerHTML = `
    ${trace ? `
    <div class="section-title">Where it looked</div>
    <div class="pipeline">
      ${stages.map((s) => `
        <div class="pipeline-stage">
          <div class="stage-name">${s.name}</div>
          <div class="stage-status ${esc(s.status)}">${esc(STAGE_STATUS_WORDS[s.status] || s.status)}</div>
        </div>
      `).join("")}
    </div>
    <div class="grid grid-4" style="margin-bottom:16px;">
      <div class="card"><div class="label">AI thinking steps <span class="tip" title="How many times it had to think/decide something while forming this answer">?</span></div><div class="value small">${trace.llm_calls ?? "—"}</div></div>
      <div class="card"><div class="label">Thinking time</div><div class="value small">${trace.llm_latency_ms ? trace.llm_latency_ms.toFixed(0) + " ms" : "—"}</div></div>
      <div class="card"><div class="label">Total time</div><div class="value small">${trace.latency_ms ? trace.latency_ms.toFixed(0) + " ms" : "—"}</div></div>
      <div class="card"><div class="label">Reference id</div><div class="value small mono">${esc((trace.trace_id || "").slice(0, 12))}</div></div>
    </div>` : `<div class="empty-state">No detailed trace available for this one (may be from an older version).</div>`}

    ${recall ? `
    <div class="section-title">What it actually used to answer</div>
    <div class="context-output">${esc(recall.context || "(Nothing — it didn't find anything relevant. This is usually why an answer would be wrong or made up.)")}</div>
    <div class="section-title" style="margin-top:16px;">The individual facts it pulled up</div>
    <table>
      <thead><tr><th>Fact</th><th>Kind</th><th>How sure</th></tr></thead>
      <tbody>${(recall.memories || []).map((m) => `
        <tr><td class="content-cell">${esc(m.content)}</td><td class="mono">${esc(m.memory_type)}</td><td>${confidenceLabel(m.confidence)}</td></tr>
      `).join("") || `<tr><td colspan="3" class="empty-state">Nothing relevant was found for this question.</td></tr>`}</tbody>
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
