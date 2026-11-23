/* 运维页洞察区块：存储压缩观测 + 节点归属 / 备份只读视图。
 * 边界：只做展示，不发写操作；任一数据请求失败降级为空态，不抛未捕获异常。
 * 数据出口：archive.metrics（存储台账、解压时延、缓存命中）；
 * nodes.nodes_view（节点健康、项目归属）；nodes.backups（备份状态）。
 */
(function () {
  "use strict";

  function token() {
    return localStorage.getItem("ai_new_token") ||
      (document.cookie.match(/hive_token=([^;]+)/) || [])[1] || "";
  }

  async function rpc(route, payload) {
    const resp = await fetch("/api/rpc/" + route.replace(".", "/"), {
      method: "POST",
      headers: { "Content-Type": "application/yaml", "X-Auth-Token": token() },
      body: JSON.stringify(payload || {})
    });
    const text = await resp.text();
    let body;
    try {
      body = (typeof jsyaml !== "undefined" && jsyaml.load)
        ? jsyaml.load(text) : JSON.parse(text);
    } catch (e) { body = { ok: false, error: "bad_yaml" }; }
    body = body || {};
    if (!body.ok) throw new Error(body.error || body.code || "request_failed");
    return body.result || {};
  }

  function esc(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  function fmtBytes(n) {
    const num = Number(n) || 0;
    if (num < 1024) return num + " B";
    const units = ["KB", "MB", "GB"];
    let v = num;
    let u = -1;
    do { v /= 1024; u += 1; } while (v >= 1024 && u < units.length - 1);
    return v.toFixed(1) + " " + units[u];
  }

  function fmtPct(x) {
    const num = Number(x) || 0;
    return (num * 100).toFixed(1) + "%";
  }

  function fmtLease(sec) {
    const s = Math.max(0, Math.ceil(Number(sec) || 0));
    if (s < 60) return s + "s";
    const m = Math.floor(s / 60);
    return m + "m " + (s % 60) + "s";
  }

  function statCell(label, value, sub) {
    return '<div class="stat-cell"><span class="stat-label">' + esc(label) + "</span>" +
      "<b>" + esc(value) + "</b>" +
      (sub ? "<span>" + esc(sub) + "</span>" : "") + "</div>";
  }

  function renderStorage(root, metrics) {
    const host = root.querySelector("[data-role='storage']") || root;
    if (!metrics) {
      host.innerHTML = '<div class="empty"><strong>存储观测</strong><span>存储指标暂不可用</span></div>';
      return;
    }
    const storage = metrics.storage || {};
    const labels = metrics.labels || {};
    if (!(storage.count > 0)) {
      host.innerHTML = '<div class="empty"><strong>存储归档</strong><span>' +
        esc(labels.storage_empty || "暂无已压缩归档") + "</span></div>";
      return;
    }
    const decomp = metrics.decompress || {};
    const cache = metrics.cache || {};
    const p50 = decomp.p50_ms == null ? "—" : decomp.p50_ms + " ms";
    const p95 = decomp.p95_ms == null ? "—" : decomp.p95_ms + " ms";
    const decompNote = decomp.status === "ok" ? "P50 / P95 解压耗时" :
      (labels.decompress_status || "解压样本不足，分位暂不可用");
    const cacheSub = (cache.entries || 0) + " / " + (cache.max_entries || 0) + " 条";
    const cells = [
      statCell("已压缩量", storage.count + " 条", fmtBytes(storage.comp_bytes)),
      statCell("节省空间", fmtBytes(storage.saved_bytes), "节省率 " + fmtPct(storage.saved_ratio)),
      statCell("压缩率", fmtPct(storage.compression_ratio), "压缩后 / 原始字节"),
      statCell("解压耗时", p50 + " / " + p95, decompNote),
      statCell("缓存命中率", fmtPct(cache.hit_rate), cacheSub)
    ];
    host.innerHTML = '<div class="stat-strip">' + cells.join("") + "</div>";
  }

  function backupChip(state) {
    const s = String(state || "").toLowerCase();
    const cls = (s === "verified" || s === "done" || s === "ok") ? "st-idle" :
      (s === "failed" ? "st-offline" : "st-busy");
    const text = s || "未登记";
    return '<span class="chip ' + cls + '"><span class="dot"></span>' + esc(text) + "</span>";
  }

  function renderNodes(root, nodes, backups) {
    const host = root.querySelector("[data-role='nodes']") || root;
    const list = Array.isArray(nodes) ? nodes : [];
    const backupByProject = {};
    (Array.isArray(backups) ? backups : []).forEach(function (b) {
      if (b && b.project) backupByProject[b.project] = b;
    });
    if (!list.length) {
      host.innerHTML = '<div class="empty"><strong>节点</strong><span>暂无节点在线信息</span></div>';
      return;
    }
    const nowSec = Date.now() / 1000;
    const rows = list.map(function (n) {
      const alive = n.health === "alive";
      const stateChip = alive
        ? '<span class="chip st-idle"><span class="dot"></span>在线</span>'
        : '<span class="chip st-offline"><span class="dot"></span>假死</span>';
      let lease = "—";
      if (!alive) {
        lease = "已失联";
      } else if (typeof n.lease_remaining === "number") {
        lease = fmtLease(n.lease_remaining);
      } else {
        const ttl = Number(n.lease_ttl) || 0;
        const seen = Number(n.last_seen) || 0;
        if (ttl > 0 && seen > 0) lease = fmtLease(ttl - (nowSec - seen));
      }
      const projects = Array.isArray(n.projects) ? n.projects : [];
      const projectHtml = projects.length
        ? projects.map(function (p) { return '<span class="chip">' + esc(p) + "</span>"; }).join(" ")
        : '<span class="muted">—</span>';
      let backupHtml;
      if (!projects.length) {
        backupHtml = '<span class="muted">—</span>';
      } else {
        const attached = projects.map(function (p) { return backupByProject[p]; })
          .filter(Boolean);
        backupHtml = attached.length
          ? attached.map(function (b) { return backupChip(b.state || b.backup_state); }).join(" ")
          : '<span class="muted">无备份记录</span>';
      }
      return "<tr><td>" + esc(n.id || "—") +
        '<div class="muted">' + esc(n.endpoint || "") + "</div></td>" +
        "<td>" + stateChip + "</td><td>" + esc(lease) + "</td>" +
        "<td>" + projectHtml + "</td><td>" + backupHtml + "</td></tr>";
    }).join("");
    host.innerHTML = '<div class="tbl-wrap"><div class="tbl-head"><strong>节点与归属</strong></div>' +
      "<table><thead><tr><th>节点</th><th>状态</th><th>租约剩余</th><th>项目归属</th><th>备份状态</th></tr></thead>" +
      "<tbody>" + rows + "</tbody></table></div>";
  }

  function ensureRoot() {
    let root = document.getElementById("ops-insight");
    if (root) return root;
    root = document.createElement("section");
    root.id = "ops-insight";
    const mount = document.getElementById("view-body") || document.body;
    mount.appendChild(root);
    return root;
  }

  async function load() {
    const root = ensureRoot();
    root.innerHTML =
      '<div data-role="storage"></div><div data-role="nodes"></div>';
    const [mRes, nRes, bRes] = await Promise.allSettled([
      rpc("archive.metrics"),
      rpc("nodes.nodes_view"),
      rpc("nodes.backups")
    ]);
    const metrics = mRes.status === "fulfilled" ? mRes.value : null;
    const nodes = nRes.status === "fulfilled" ? (nRes.value.nodes || []) : null;
    const backups = bRes.status === "fulfilled" ? (bRes.value.backups || []) : null;
    renderStorage(root, metrics);
    renderNodes(root, nodes, backups);
    root.hidden = false;
  }

  function boot() {
    try {
      load().catch(function () {
        const root = document.getElementById("ops-insight");
        if (root) {
          root.innerHTML =
            '<div class="empty"><strong>运维观测</strong><span>观测数据暂不可用</span></div>';
          root.hidden = false;
        }
      });
    } catch (e) {
      /* 控制台不因本区块抛未捕获异常 */
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
  window.opsInsightBoot = boot;
})();
