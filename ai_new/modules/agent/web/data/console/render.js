/* render：规格 -> DOM（只认原语 cards/table/chat/kv/composer/empty）
   只认识原语（cards / table / chat / kv / composer / empty），不认识业务。
*/
function actIndex(act, ctx) {
  ACTS.push({ act, ctx });
  return ACTS.length - 1;
}
function buttonHtml(act, ctx, opts) {
  opts = opts || {};
  const binding = { act, ctx };
  if (opts.composer) binding.composer = true;
  ACTS.push(binding);
  const disabled = opts.disabled === true
    || (act.disabled_when != null && condOf(act.disabled_when, ctx));
  const hint = act.disabled_hint || opts.hint || "";
  const title = disabled && hint ? ` title="${esc(hint)}"` : "";
  const cls = act.tone === "primary" ? "primary" : (act.tone === "danger" ? "danger" : "");
  return `<button class="${cls}" data-act="${ACTS.length - 1}" ${disabled ? "disabled" : ""}${title}>${esc(fill(act.label, ctx))}</button>`;
}
function badgeHtml(value, ctx) {
  const s = String(value == null ? "" : value);
  const cls = s === "closed" || s === "gone" || s === "done" ? "closed"
    : (s === "open" || s === "running" || s === "queued" || s === "doing" ? "open" : "");
  return `<span class="badge ${cls}">${esc(s || "下线")}</span>`;
}
const BUSY_STATUS = ["running", "queued", "doing"];
const OFFLINE_STATUS = ["gone", "done", "closed", ""];
function statusKind(s) {
  s = String(s == null ? "" : s);
  if (BUSY_STATUS.includes(s)) return "busy";
  if (OFFLINE_STATUS.includes(s)) return "offline";
  return "idle";
}
function statusText(s) {
  return { busy: "忙", idle: "空闲", offline: "下线" }[statusKind(s)];
}
function emptyHtml(block) {
  block = block || {};
  return `<div class="empty">${block.title ? `<strong>${esc(fill(block.title, {}))}</strong>` : ""}${esc(fill(block.text || "", {}))}</div>`;
}

function cardsHtml(sec, ctx) {
  const rows = arr(ref(sec.source, ctx));
  if (!rows.length) return emptyHtml(sec.empty);
  const cards = rows.map((row) => {
    const c = { ...ctx, row };
    const archived = sec.archived_when != null && condOf(sec.archived_when, c);
    const acts = (sec.actions || []).map((a) => buttonHtml(a, c)).join("");
    const badge = (sec.badge && condOf(sec.badge.when, c))
      ? `<span class="badge archived">${esc(fill(sec.badge.text, c))}</span>` : "";
    const stat = sec.stat ? `<div class="stat"><b>${esc(fill(sec.stat.count, c))}</b> ${esc(fill(sec.stat.label, c))}<span class="muted">· ${esc(fill(sec.stat.note || "", c))}</span></div>` : "";
    const meta = (sec.meta || []).filter((m) => m.hide_if_empty ? !!fmtVal(m, c) : true)
      .map((m) => `<span>${esc(fill(m.label, c))} ${esc(fmtVal(m, c))}</span>`).join("");
    const click = sec.on_click ? actIndex({ view: sec.on_click.view, params: sec.on_click.params || {} }, c) : -1;
    return `<article class="pcard${archived ? " archived" : ""}" ${click >= 0 ? `data-go="${click}"` : ""} role="button" tabindex="0" aria-label="进入 ${esc(fill(sec.title, c))}">
      <div class="acts">${acts}</div>
      <h3 class="pname">${esc(fill(sec.title, c))}</h3>
      ${badge}${stat}
      <div class="meta">${meta}</div>
      <span class="ar">›</span>
    </article>`;
  }).join("");
  return `<div class="cards">${cards}</div>`;
}

function tableHtml(sec, ctx) {
  const rows0 = arr(ref(sec.source, ctx));
  let rows = rows0.slice();
  if (sec.sort) {
    const by = sec.sort.by, dir = sec.sort.order === "asc" ? 1 : -1;
    rows.sort((a, b) => dir * String(dig(a, by) || "").localeCompare(String(dig(b, by) || "")));
  }
  const filters = sec.filters || [];
  if (filters.length) {
    const active = filters.find((f) => f.key === FILTER) || filters[0];
    if (active && active.keep) rows = rows.filter((r) => matchCond(r, active.keep));
    sec._active = active ? active.key : null;
  }
  const head = `<div class="tbl-head">
    ${sec.heading ? `<strong style="font-size:13px">${esc(fill(sec.heading, ctx))}</strong>` : ""}
    ${sec.count_note ? `<span class="muted">${esc(fill(sec.count_note, ctx))}</span>` : ""}
    <div class="spacer" style="margin-left:auto"></div>
    ${filters.length ? `<span class="seg" id="seg">${filters.map((f) =>
      `<button data-filter="${esc(f.key)}" class="${f.key === (sec._active || filters[0].key) ? "on" : ""}">${esc(f.label)}</button>`).join("")}</span>` : ""}
  </div>`;
  const cols = sec.columns || [];
  const rowActs = sec.actions || [];
  const body = rows.length ? rows.map((row) => {
    const c = { ...ctx, row };
    const cells = cols.map((col) => {
      let val;
      if (col.badge) val = badgeHtml(fill(col.badge, c), c);
      else {
        const raw = col.format ? fmtVal(col, c) : fill(col.value, c);
        val = Array.isArray(raw) ? raw.map((x) => esc(x)).join("<br>") : esc(raw);
        if (col.suffix) val += ` ${esc(fill(col.suffix, c))}`;
        if (col.sub) val += `<div class="muted">${esc(fill(col.sub, c))}</div>`;
      }
      if (val === "" || val === "undefined") val = esc(col.fallback ? fill(col.fallback, c) : "—");
      return `<td class="${col.muted ? "muted" : ""}">${val}</td>`;
    }).join("");
    const acts = rowActs.length ? `<td class="actions">${rowActs.map((a) => buttonHtml(a, c)).join("")}</td>` : "";
    const click = sec.on_click ? actIndex({ view: sec.on_click.view, params: sec.on_click.params || {} }, c) : -1;
    return `<tr ${click >= 0 ? `data-go="${click}"` : ""}>${cells}${acts}</tr>`;
  }).join("") : `<tr><td colspan="${cols.length + (rowActs.length ? 1 : 0)}" class="muted">${esc((sec.empty || {}).text || "暂无数据")}</td></tr>`;
  if (sec.hide_when_empty && !rows0.length) return "";
  const actHead = rowActs.length ? "<th>操作</th>" : "";
  const wrap = `<div class="tbl-wrap">${sec.heading || filters.length || sec.count_note ? head : ""}<table>
    <thead><tr>${cols.map((c) => `<th>${esc(c.label || "")}</th>`).join("")}${actHead}</tr></thead>
    <tbody>${body}</tbody></table></div>`;
  if (sec.summarize) {
    return `<div class="orphans"><details><summary>${esc(fill(sec.title || "", ctx))}（${rows0.length}）</summary>${wrap}</details></div>`;
  }
  return wrap;
}

const AVATAR_PALETTE = ["#2f6bff", "#00b42a", "#ff7d00", "#722ed1", "#0fc6c2", "#f53f3f", "#eb0aa4"];
/* 角色固定配色：同名同色，跨会话一致；未命中回退哈希取色 */
const ROLE_COLOR = {
  "pm": "#2f6bff", "PM": "#2f6bff",
  "developer": "#722ed1", "tester": "#0fc6c2", "reviewer": "#ff7d00",
  "user": "#00b42a", "用户": "#00b42a",
  "tool": "#86909c", "工具": "#86909c", "系统": "#86909c"
};
function speakerOf(msg, roles) {
  if (msg.kind === "note") return "系统";
  const actor = msg.actor || msg.role || "assistant";
  if (actor === "user") return "用户";
  if (actor === "system") return "系统";
  if (actor === "tool") return msg.name ? ("工具 · " + msg.name) : "工具";
  if (actor === "pm" || actor === "assistant") return "PM";
  const hit = (roles || []).find((r) => r.role === actor || r.session === actor);
  return (hit && (hit.display || hit.role)) || actor;
}
function bubbleClass(msg) {
  if (msg.kind === "note") return "system";
  const role = msg.role || "assistant";
  if (role === "user") return "user";
  if (role === "system") return "system";
  if (role === "tool") return "tool";
  const actor = msg.actor || role;
  if (actor === "pm" || actor === "assistant") return "assistant";
  return "role";
}
function avatarColor(name) {
  const key = String(name || "").trim();
  if (ROLE_COLOR[key]) return ROLE_COLOR[key];
  let h = 0;
  for (const ch of key) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return AVATAR_PALETTE[h % AVATAR_PALETTE.length];
}
function initial(name) {
  const s = String(name || "?").trim();
  return s ? esc(s[0]) : "?";
}
function draftBubbleHtml(draft, roles) {
  const draftTxt = String((draft && draft.text) || "");
  if (!(draft && draft.running && draftTxt.trim())) return "";
  const who = speakerOf({ role: "assistant" }, roles);
  return `<div class="msg left draft-bubble"><div class="avatar" style="--av:${avatarColor(who)}">${initial(who)}</div>
        <div class="msg-main"><div class="msg-name">${esc(who)}</div>
        <div class="bubble-stack"><div class="bubble-body draft">${esc(draftTxt)}<span class="cursor">▍</span></div></div></div></div>`;
}
/* 工单历程 → 系统事件气泡：连续同类事件合并计数，长文本折行折叠 */
function eventLabel(event) { return EVENT_LABELS[event] || event || ""; }
/* role_spawn 的事件正文是「角色: 任务」，合并后只报角色名，任务统一在一句里 */
function roleOf(text) {
  const s = String(text || "");
  const i = s.indexOf(":");
  return i > 0 ? s.slice(0, i).trim() : s.trim();
}
function taskOf(text) {
  const s = String(text || "");
  const i = s.indexOf(":");
  return i > 0 ? s.slice(i + 1).trim() : "";
}
function eventText(group) {
  const items = group.items;
  if (group.event === "role_spawn") {
    if (items.length === 1) {
      const one = items[0];
      const task = taskOf(one.text);
      return task ? roleOf(one.text) + " · " + task : roleOf(one.text) + " 已派出";
    }
    const roles = items.map((h) => roleOf(h.text)).filter(Boolean);
    return roles.length ? roles.join("、") + " 已派出" : "";
  }
  const last = items[items.length - 1] || {};
  return String(last.text || "");
}
function atSeconds(at) {
  if (at == null || at === "") return -Infinity;
  if (typeof at === "number") return isFinite(at) ? at : -Infinity;
  const n = Number(at);
  if (isFinite(n) && n > 0) return n;
  const d = Date.parse(at);
  return isFinite(d) ? d / 1000 : -Infinity;
}
function clockText(at) {
  const t = atSeconds(at);
  if (!isFinite(t)) return "";
  const d = new Date(t * 1000);
  return d.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
}
/* 连续同类事件合并：派角色合并成「A、B 已派出」，其余取最后一条正文 */
function groupEvents(events) {
  const groups = [];
  for (const h of arr(events)) {
    if (!h) continue;
    const last = groups[groups.length - 1];
    if (last && last.event === h.event) last.items.push(h);
    else groups.push({ event: h.event, items: [h] });
  }
  return groups.map((g) => ({
    kind: "event", event: g.event, items: g.items,
    at: atSeconds((g.items[g.items.length - 1] || {}).at),
  }));
}
function eventGroupHtml(g) {
  const n = g.items.length;
  const last = g.items[n - 1] || {};
  const label = eventLabel(g.event);
  const cnt = n > 1 ? ` ×${n}` : "";
  const text = eventText(g);
  const long = text.length > 60;
  const shown = long ? text.slice(0, 58) + "…" : text;
  const fold = long ? ` data-expand data-full="${esc(text)}" data-short="${esc(shown)}"` : "";
  return `<div class="msg event"><div class="sys-body${long ? " clamp" : ""}"${fold}><span class="ev-line"><span class="ev-label">${esc(label + cnt)}</span>${shown ? `<span class="ev-text">${esc(shown)}</span>` : ""}</span><span class="ev-ts">${esc(when(last.at))}</span></div></div>`;
}

/* 工具调用与它自己的结果合并成一张卡：assistant.tool_calls + 对应 tool_call_id 的回填 */
function pairItems(msgs) {
  const pending = {};
  const items = [];
  for (const m of msgs) {
    if (m.role === "tool") {
      const call = m.tool_call_id ? pending[m.tool_call_id] : null;
      if (call && !call.result) { call.result = m; continue; }
      items.push({ kind: "tool", m, at: atSeconds(m.at) });
      continue;
    }
    items.push({ kind: "msg", m, at: atSeconds(m.at) });
    for (const tc of m.tool_calls || []) {
      const fn = (tc && tc.function) || {};
      const call = { kind: "call", name: fn.name || "", args: fn.arguments || "", result: null,
                     at: atSeconds(m.at) };
      items.push(call);
      if (tc && tc.id) pending[tc.id] = call;
    }
  }
  return items;
}
function toolBrief(m) {
  const raw = String((m && m.content) == null ? "" : m.content);
  let o = null;
  try { o = JSON.parse(raw); } catch (e) {}
  if (!o || typeof o !== "object") return { ok: true, text: raw.slice(0, 92) };
  if (o.ok === false) return { ok: false, text: String(o.error || raw).slice(0, 120) };
  for (const k of ["text", "content", "summary", "message"]) {
    const v = o[k];
    if (typeof v === "string" && v.trim()) return { ok: true, text: v.trim().replace(/\s+/g, " ").slice(0, 92) };
  }
  const bits = [];
  for (const k of TOOL_META_ORDER) {
    let v = o[k];
    if (v == null || v === "" || typeof v === "object") continue;
    if (typeof v === "boolean") v = v ? "是" : "否";
    bits.push((TOOL_META_LABELS[k] || k) + " " + v);
    if (bits.length >= 3) break;
  }
  if (Array.isArray(o.items)) bits.unshift(o.items.length + " 项");
  return { ok: true, text: bits.join(" · ") || "完成" };
}
function toolCallCard(it) {
  const args = String(it.args || "").trim();
  const argsHtml = args && args !== "{}"
    ? `<span class="tool-call-args">${esc(args.length > 72 ? args.slice(0, 72) + "…" : args)}</span>` : "";
  let line = `<div class="tool-line pending">执行中…</div>`;
  let raw = "";
  if (it.result) {
    const brief = toolBrief(it.result);
    line = `<div class="tool-line ${brief.ok ? "" : "err"}">${esc(brief.text)}</div>`;
    raw = `<details class="tool-raw"><summary>原始数据</summary><pre>${esc(String(it.result.content == null ? "" : it.result.content))}</pre></details>`;
  }
  return `<div class="tool-call"><div class="tool-call-head"><span class="tool-call-name">${esc(it.name)}</span>${argsHtml}</div>${line}${raw}</div>`;
}
function itemHtml(it) {
  if (it.kind === "call") return toolCallCard(it);
  if (it.kind === "tool") return toolBodyHtml(it.m);
  const m = it.m;
  const text = String(m.content == null ? "" : m.content).trim();
  if (!text) return "";
  return `<div class="bubble-body md">${renderMarkdown(m.content)}</div>`;
}
function renderBubbles(msgs, roles) {
  const groups = [];
  for (const it of pairItems(msgs)) {
    const m = it.m || {};
    const cls = it.kind === "tool" ? "tool" : bubbleClass(m);
    const who = cls === "system" ? "" : speakerOf(m, roles);
    const key = cls + "|" + who;
    const last = groups[groups.length - 1];
    if (last && last.key === key) last.items.push(it);
    else groups.push({ key, cls, who, items: [it] });
  }
  return groups.map((g) => {
    if (g.cls === "system") {
      return g.items.map((it) => `<div class="msg system"><div class="sys-body md">${renderMarkdown((it.m || {}).content == null ? "" : it.m.content)}</div></div>`).join("");
    }
    const side = g.cls === "user" ? "right" : "left";
    const bodies = g.items.map(itemHtml).join("");
    if (!bodies) return "";
    const av = `<div class="avatar" style="--av:${avatarColor(g.who)}">${initial(g.who)}</div>`;
    const ts = clockText((g.items[g.items.length - 1] || {}).at);
    return `<div class="msg ${side}">${side === "left" ? av : ""}
      <div class="msg-main"><div class="msg-name">${esc(g.who)}</div>
      <div class="bubble-stack">${bodies}</div>${ts ? `<div class="msg-ts">${esc(ts)}</div>` : ""}</div>${side === "right" ? av : ""}</div>`;
  }).join("");
}

/* 消息与工单历程事件按时间穿插：同一时刻先消息后事件，无时间戳的排最前保序 */
function streamHtml(msgs, events, roles) {
  const stream = [];
  msgs.forEach((m, i) => stream.push({ kind: "m", at: atSeconds(m.at), i, m }));
  events.forEach((e, i) => stream.push({ kind: "e", at: e.at, i: msgs.length + i, e }));
  stream.sort((a, b) => (a.at === b.at ? a.i - b.i : (a.at < b.at ? -1 : 1)));
  const out = [];
  let buf = [];
  const flush = () => {
    if (buf.length) { out.push(renderBubbles(buf, roles)); buf = []; }
  };
  for (const s of stream) {
    if (s.kind === "m") { buf.push(s.m); continue; }
    flush();
    out.push(eventGroupHtml(s.e));
  }
  flush();
  return out.join("");
}

function chatHtml(sec, ctx) {
  const src = ref(sec.source, ctx) || {};
  const roles = ref(sec.roles_source, ctx) || [];
  window.RENDER_MEMBERS = roles;
  const hidden = sec.hide_roles || [];
  const msgs = arr(src.messages).filter((m) => {
    if (hidden.includes(m.role || "")) return false;
    return true;
  });
  const badge = sec.badge ? badgeHtml(fill(sec.badge, ctx), ctx) : "";
  const title = sec.heading ? `<div class="chat-head-title"><strong>${esc(fill(sec.heading, ctx))}</strong></div>` : "";
  const metaBits = (sec.meta || []).map((x) => fill(x, ctx)).filter((x) => String(x == null ? "" : x).trim());
  const meta = (badge || metaBits.length)
    ? `<div class="chat-head-meta">${badge}${metaBits.map((x, i) => `<span>${i ? "<i>·</i>" : ""}${esc(x)}</span>`).join("")}</div>` : "";
  const headMain = (title || meta) ? `<div class="chat-head-main">${title}${meta}</div>` : "";
  const chips = arr(roles).map((r, i) => `<button class="av-chip st-${statusKind(r.status)}" data-member="${i}"
      style="--av:${avatarColor(r.display || r.role)}" title="${esc(r.display || r.role)} · ${statusText(r.status)}">${initial(r.display || r.role)}<i class="dot"></i></button>`).join("");
  const draft = (ctx.data && ctx.data.draft) || {};
  const draftHtml = draftBubbleHtml(draft, roles);
  const summary = (src.summary || "").trim();
  const summaryHtml = summary ? `<details class="chat-summary"><summary>上下文摘要</summary><div class="chat-summary-text">${esc(summary)}</div></details>` : "";
  const events = groupEvents(sec.history_source ? ref(sec.history_source, ctx) : undefined);
  const stream = streamHtml(msgs, events, roles);
  const body = (stream || `<div class="chat-empty">${esc(fill(sec.empty || "", ctx))}</div>`) + draftHtml;
  return `<section class="chat-card card">
    ${headMain || chips ? `<div class="chat-head">${headMain}<div class="members">${chips}</div></div>` : ""}
    ${summaryHtml}
    <div class="chat">${body}</div>
  </section>`;
}
const TOOL_META_LABELS = { path: "路径", id: "ID", title: "标题", status: "状态", project: "项目",
  kind: "类型", layer: "层", size: "字节", chars: "字符", query: "关键词", truncated: "截断",
  written: "已落盘", pm: "PM", demand: "需求", encoding: "编码" };
const TOOL_META_ORDER = ["demand", "id", "title", "status", "project", "kind", "layer", "path",
  "query", "size", "chars", "truncated", "written", "pm", "encoding"];

function toolMetaChips(obj) {
  const chips = [];
  for (const k of TOOL_META_ORDER) {
    let v = obj[k];
    if (v == null || v === "") continue;
    if (typeof v === "boolean") v = v ? "是" : "否";
    chips.push(`<span class="tool-meta-item"><b>${esc(TOOL_META_LABELS[k] || k)}</b> ${esc(v)}</span>`);
  }
  return chips.length ? `<div class="tool-meta">${chips.join("")}</div>` : "";
}

function toolCollectTexts(o) {
  const texts = [];
  const push = (t) => { if (typeof t === "string" && t.trim() && !texts.includes(t)) texts.push(t); };
  push(o.text); push(o.content);
  if (o.result && typeof o.result === "object") { push(o.result.text); push(o.result.content); }
  (o.effects || []).forEach((e) => e && push(e.text));
  return texts;
}

function toolTraceHtml(o) {
  const lines = [];
  (o.effects || []).forEach((e) => {
    if (!e) return;
    const seg = [e.kind, e.module, e.path].filter(Boolean).join(" · ");
    if (seg) lines.push(seg);
  });
  (o.applied || []).forEach((a) => {
    if (!a) return;
    const seg = (a.written === false ? "未写入" : "已写入") + (a.path ? " · " + a.path : "");
    lines.push(seg);
  });
  (o.history || []).forEach((h) => {
    if (h && h.text) lines.push((h.event || "记录") + " · " + String(h.text).slice(0, 120));
  });
  return lines.length ? `<div class="tool-trace">${lines.map(esc).join("<br>")}</div>` : "";
}

function toolResultHtml(o, raw) {
  const res = (o.result && typeof o.result === "object") ? o.result : o;
  const metaObj = Object.assign({}, res, o);
  ["result", "effects", "applied", "history", "items"].forEach((k) => delete metaObj[k]);
  const parts = [];
  parts.push(toolMetaChips(metaObj));
  if (Array.isArray(res.items)) {
    if (!res.items.length) parts.push(`<div class="tool-empty">无命中</div>`);
    else parts.push(`<ul class="tool-items">${res.items.map((it) => {
      const label = typeof it === "string" ? it : (it.title || it.path || it.summary || JSON.stringify(it));
      return `<li>${esc(label)}</li>`;
    }).join("")}</ul>`);
  }
  toolCollectTexts(o).forEach((t) => parts.push(`<div class="tool-text md">${renderMarkdown(t)}</div>`));
  parts.push(toolTraceHtml(o));
  let pretty = raw;
  try { pretty = JSON.stringify(o, null, 2); } catch (e) {}
  parts.push(`<details class="tool-raw"><summary>原始数据</summary><pre>${esc(pretty)}</pre></details>`);
  return `<div class="bubble-body tool md">${parts.join("")}</div>`;
}

function toolBodyHtml(m) {
  const raw = m.content == null ? "" : String(m.content);
  let o = null;
  try { o = JSON.parse(raw); } catch (e) {}
  if (o && typeof o === "object" && o.ok === false) {
    return `<div class="bubble-body tool error md">${renderMarkdown(o.error || raw)}</div>`;
  }
  if (o && typeof o === "object") return toolResultHtml(o, raw);
  return `<div class="bubble-body tool md">${renderMarkdown(raw)}</div>`;
}
function treeDocHtml(doc, sec, ctx) {
  const c = { ...ctx, row: doc };
  const click = sec.on_click ? actIndex({ view: sec.on_click.view, params: sec.on_click.params || {} }, c) : -1;
  return `<div class="tree-doc" ${click >= 0 ? `data-go="${click}"` : ""} role="button" tabindex="0">
    <span class="tree-doc-name">${esc(fill("row.name", c))}</span>
    <span class="muted tree-doc-path">${esc(fill("row.path", c))}</span>
  </div>`;
}
function treeNodeHtml(node, sec, ctx) {
  const kids = node.children || [];
  if (!kids.length) return treeDocHtml(node, sec, ctx);
  const count = kids.length;
  const sub = node.sub ? `<span class="muted tree-node-sub">${esc(node.sub)}</span>` : "";
  return `<details class="tree-node" open>
    <summary><span class="badge">${esc(node.badge || "")}</span><span class="tree-node-label">${esc(node.label || "")}</span>${sub}<span class="muted tree-node-count">${count}</span></summary>
    <div class="tree-children">${kids.map((k) => treeNodeHtml(k, sec, ctx)).join("")}</div>
  </details>`;
}
function treeHtml(sec, ctx) {
  const nodes = arr(ref(sec.source, ctx));
  if (!nodes.length) return emptyHtml(sec.empty);
  return `<div class="tree">${nodes.map((n) => treeNodeHtml(n, sec, ctx)).join("")}</div>`;
}

function kvHtml(sec, ctx) {
  const src = ref(sec.source, ctx) || {};
  const rows = (sec.rows || []).map((r) => {
    const c = { ...ctx, row: src };
    const val = r.badge ? badgeHtml(fill(r.badge, c), c)
      : esc((fmtVal(r, c) === undefined || fmtVal(r, c) === "" ? (r.fallback || "—") : fmtVal(r, c)));
    return `<div class="kv"><span>${esc(r.label)}</span><div>${val}</div></div>`;
  }).join("");
  const acts = (sec.actions || []).map((a) => buttonHtml(a, { ...ctx, row: src })).join("");
  return `<aside class="side-card">
    ${sec.heading ? `<h3>${esc(fill(sec.heading, ctx))}</h3>` : ""}
    ${rows}
    ${acts ? `<div class="actions" style="margin-top:12px">${acts}</div>` : ""}
  </aside>`;
}

function docHtml(sec, ctx) {
  const raw = String(ref(sec.source, ctx) == null ? "" : ref(sec.source, ctx));
  if (sec.hide_when_empty && !raw.trim()) return "";
  const body = raw.trim() ? renderMarkdown(raw) : esc(sec.fallback || "暂无正文");
  return `<aside class="side-card">
    ${sec.heading ? `<h3>${esc(fill(sec.heading, ctx))}</h3>` : ""}
    <div class="doc-body">${body}</div>
  </aside>`;
}

function composerHtml(sec, ctx) {
  const disabled = sec.disabled_when != null && condOf(sec.disabled_when, ctx);
  const submit = sec.submit || {};
  ACTS.push({ act: submit, ctx, composer: true });
  const submitIdx = ACTS.length - 1;
  const voice = sec.voice || null;
  let voiceIdx = -1;
  if (voice) {
    ACTS.push({ act: voice, ctx, composer: true, voice: true });
    voiceIdx = ACTS.length - 1;
  }
  const hint = disabled ? (sec.disabled_hint || "") : "";
  const gate = disabled ? ` disabled${hint ? ` title="${esc(hint)}"` : ""}` : "";
  const acts = (sec.actions || []).map((a) =>
    buttonHtml(a, ctx, { disabled, hint, composer: true })).join("");
  const busyVal = sec.busy_from ? String(fill(sec.busy_from, ctx) || "") : "";
  const busy = !disabled && busyVal && busyVal === (sec.busy_when || "running");
  const voiceBtn = voice && !disabled
    ? `<button class="voice" data-act="${voiceIdx}" title="${esc(fill(voice.hint || "", ctx))}">${esc(fill(voice.label || "语音", ctx))}</button>`
    : "";
  return `<div class="composer-wrap">
    <div class="composer${disabled ? " off" : ""}">
      <textarea placeholder="${esc(fill(sec.placeholder || "", ctx))}"${gate}></textarea>
      ${acts}
      ${voiceBtn}
      <button class="primary" data-act="${submitIdx}"${gate}>${esc(fill(submit.label || "发送", ctx))}</button>
    </div>
    ${hint ? `<div class="composer-hint">${esc(hint)}</div>` : ""}
    ${busy ? `<div class="composer-hint busy">${esc(fill(sec.busy_text || "", ctx))}</div>` : ""}
  </div>`;
}

function sectionHtml(sec, ctx) {
  const kind = sec.kind;
  let html = "";
  if (kind === "cards") html = cardsHtml(sec, ctx);
  else if (kind === "table") html = tableHtml(sec, ctx);
  else if (kind === "chat") html = chatHtml(sec, ctx);
  else if (kind === "kv") html = kvHtml(sec, ctx);
  else if (kind === "tree") html = treeHtml(sec, ctx);
  else if (kind === "doc") html = docHtml(sec, ctx);
  else if (kind === "composer") html = composerHtml(sec, ctx);
  else html = emptyHtml({ text: "未知区块: " + kind });
  return `<div class="vsec" data-kind="${esc(kind)}">${html}</div>`;
}

function renderView(spec, ctx) {
  ACTS = [];
  const head = `<div class="view-head">
      <div style="min-width:0"><h2>${esc(fill(spec.heading || spec.heading_from || "", ctx))}</h2>
      <div class="desc">${esc(fill(spec.subheading || "", ctx))}</div></div>
      <div class="spacer"></div>
      <div class="actions">${(spec.actions || []).map((a) => buttonHtml(a, ctx)).join("")}</div>
    </div>`;
  const left = [], right = [], single = [];
  for (const sec of spec.sections || []) {
    const html = sectionHtml(sec, ctx);
    if (sec.lane === "left") left.push(html);
    else if (sec.lane === "right") right.push(html);
    else single.push(html);
  }
  let body = single.join("");
  if (left.length || right.length) {
    // 单侧有内容就占满整行：空的那一列不占位，避免留下大片空白
    const twoSided = left.length && right.length;
    body = `<div class="ticket-grid${twoSided ? "" : " solo"}">
      <div class="lane lane-left">${left.join("")}</div>
      ${twoSided ? `<div class="lane lane-right">${right.join("")}</div>` : ""}
    </div>`;
  }
  $("view-body").innerHTML = head + body;
}
