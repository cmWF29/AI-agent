/* 节点与分配独立页面（待接线产物）：直连 nodes 模块只读 RPC。
 * 视图规格注册进控制台导航属待接线项；本文件不改动既有控制台脚本，
 * 也不出现业务需求 id 字面量（由后端视图规格下发）。
 */

function token() {
  return localStorage.getItem("ai_new_token") ||
    (document.cookie.match(/hive_token=([^;]+)/) || [])[1] || "";
}

async function rpc(route, payload) {
  const resp = await fetch("/api/rpc/" + route.replace(".", "/"), {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Auth-Token": token() },
    body: JSON.stringify(payload || {})
  });
  const text = await resp.text();
  let body;
  try { body = JSON.parse(text); } catch (e) { body = { ok: false, error: "bad_yaml" }; }
  if (!body.ok) throw new Error(body.error || body.code || "request_failed");
  return body.result || {};
}

function escNode(value) {
  return String(value == null ? "" : value)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function pill(state) {
  const variant = state === "alive" ? "success" : state === "held" ? "primary"
    : state === "released" ? "neutral" : "danger";
  return `<sl-badge variant="${variant}">${escNode(state)}</sl-badge>`;
}

function renderNodes(nodes) {
  const body = document.getElementById("nodes-body");
  if (!nodes || !nodes.length) {
    body.innerHTML = `<tr><td colspan="6" class="muted">暂无节点</td></tr>`;
    return;
  }
  body.innerHTML = nodes.map(n => `
    <tr>
      <td>${escNode(n.id)}</td>
      <td>${escNode(n.endpoint)}</td>
      <td>${escNode(n.transport)}</td>
      <td>${pill(n.health)}</td>
      <td>${escNode((n.load || {}).running)}</td>
      <td>${escNode((n.projects || []).join(", ")) || "<span class='muted'>—</span>"}</td>
    </tr>`).join("");
}

function renderAssignments(assignments) {
  const body = document.getElementById("assignments-body");
  if (!assignments || !assignments.length) {
    body.innerHTML = `<tr><td colspan="6" class="muted">暂无分配</td></tr>`;
    return;
  }
  body.innerHTML = assignments.map(a => `
    <tr>
      <td>${escNode(a.project)}</td>
      <td>${escNode(a.node)}</td>
      <td>${escNode(a.epoch)}</td>
      <td>${pill(a.state)}</td>
      <td>${escNode(a.tier)}</td>
      <td>${escNode(a.expires_at)}</td>
    </tr>`).join("");
}

function renderBackups(backups) {
  const body = document.getElementById("backups-body");
  if (!backups || !backups.length) {
    body.innerHTML = `<tr><td colspan="4" class="muted">暂无备份</td></tr>`;
    return;
  }
  body.innerHTML = backups.map(b => `
    <tr>
      <td>${escNode(b.project)}</td>
      <td>${escNode(b.snapshot_id)}</td>
      <td>${pill(b.state)}</td>
      <td>${escNode((b.entries || []).length)}</td>
    </tr>`).join("");
}

function renderMigrations(migrations) {
  const body = document.getElementById("migrations-body");
  if (!migrations || !migrations.length) {
    body.innerHTML = `<tr><td colspan="7" class="muted">暂无迁移记录</td></tr>`;
    return;
  }
  body.innerHTML = migrations.map(m => `
    <tr>
      <td>${escNode(m.project)}</td>
      <td>${escNode(m.from_node)}</td>
      <td>${escNode(m.to_node || "—")}</td>
      <td>${escNode(m.reason)}</td>
      <td>${escNode(m.epoch)}</td>
      <td>${pill(m.state)}</td>
      <td>${escNode(m.migrated_at)}</td>
    </tr>`).join("");
}

async function lookupProject() {
  const project = document.getElementById("project-lookup").value.trim();
  const out = document.getElementById("lookup-result");
  if (!project) { out.textContent = ""; return; }
  try {
    const row = await rpc("nodes.project_node", { project });
    const assignment = row && row.assignment;
    if (!assignment) { out.textContent = "该项目无归属节点"; return; }
    out.textContent = `归属节点：${assignment.node}（${escNode(assignment.state)} · 档位 ${assignment.tier}）`;
  } catch (e) {
    out.textContent = "查询失败：" + e.message;
  }
}

async function load() {
  try {
    const [list, assignments, backups, migrations] = await Promise.all([
      rpc("nodes.nodes_view"),
      rpc("nodes.assignments"),
      rpc("nodes.backups"),
      rpc("nodes.migrations")
    ]);
    renderNodes(list.nodes);
    renderAssignments(assignments.assignments);
    renderBackups(backups.backups);
    renderMigrations(migrations.migrations);
  } catch (e) {
    document.getElementById("nodes-body").innerHTML =
      `<tr><td colspan="6" class="muted">加载失败：${escNode(e.message)}</td></tr>`;
  }
}

document.getElementById("lookup-btn").addEventListener("click", lookupProject);
load();
