/* render：规格 -> DOM（只认原语 cards/table/chat/kv/composer/empty）
   只认识原语（cards / table / chat / kv / composer / empty），不认识业务。
*/
function actIndex(act, ctx) {
  ACTS.push({ act, ctx });
  return ACTS.length - 1;
}
function buttonHtml(act, ctx, opts) {
  opts = opts || {};
  const disabled = act.disabled_when != null && condOf(act.disabled_when, ctx);
  const title = disabled && act.disabled_hint ? ` title="${esc(act.disabled_hint)}"` : "";
  const cls = act.tone === "primary" ? "primary" : (act.tone === "danger" ? "danger" : "");
  return `<button class="${cls}" data-act="${actIndex(act, ctx)}" ${disabled ? "disabled" : ""}${title}>${esc(fill(act.label, ctx))}</button>`;
}
function badgeHtml(value, ctx) {
  const s = String(value == null ? "" : value);
  const cls = s === "closed" || s === "gone" || s === "done" ? "closed"
    : (s === "open" || s === "running" || s === "queued" || s === "doing" ? "open" : "");
  return `<span class="badge ${cls}">${esc(s || "open")}</span>`;
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
  const body = rows.length ? rows.map((row) => {
    const c = { ...ctx, row };
    const cells = cols.map((col) => {
      let val;
      if (col.badge) val = badgeHtml(fill(col.badge, c), c);
      else {
        val = esc(col.format ? fmtVal(col, c) : fill(col.value, c));
        if (col.suffix) val += ` ${esc(fill(col.suffix, c))}`;
        if (col.sub) val += `<div class="muted">${esc(fill(col.sub, c))}</div>`;
      }
      if (val === "" || val === "undefined") val = esc(col.fallback ? fill(col.fallback, c) : "—");
      return `<td class="${col.muted ? "muted" : ""}">${val}</td>`;
    }).join("");
    const click = sec.on_click ? actIndex({ view: sec.on_click.view, params: sec.on_click.params || {} }, c) : -1;
    return `<tr ${click >= 0 ? `data-go="${click}"` : ""}>${cells}</tr>`;
  }).join("") : `<tr><td colspan="${cols.length}" class="muted">${esc((sec.empty || {}).text || "暂无数据")}</td></tr>`;
  if (sec.hide_when_empty && !rows0.length) return "";
  const wrap = `<div class="tbl-wrap">${sec.heading || filters.length || sec.count_note ? head : ""}<table>
    <thead><tr>${cols.map((c) => `<th>${esc(c.label || "")}</th>`).join("")}</tr></thead>
    <tbody>${body}</tbody></table></div>`;
  if (sec.summarize) {
    return `<div class="orphans"><details><summary>${esc(fill(sec.title || "", ctx))}（${rows0.length}）</summary>${wrap}</details></div>`;
  }
  return wrap;
}

const ROLE_CN = { pm: "PM", user: "用户", assistant: "助手", system: "系统" };
const AVATAR_PALETTE = ["#2f6bff", "#00b42a", "#ff7d00", "#722ed1", "#0fc6c2", "#f53f3f", "#eb0aa4"];
function speakerOf(msg, roles) {
  const role = msg.role || "assistant";
  if (role === "user") return "用户";
  if (role === "system") return "系统";
  if (role === "pm" || role === "assistant") return ROLE_CN[role] || role;
  const hit = (roles || []).find((r) => r.role === role || r.session === role);
  return (hit && (hit.display || hit.role)) || role;
}
function bubbleClass(msg) {
  const role = msg.role || "assistant";
  if (role === "user") return "user";
  if (role === "system") return "system";
  if (role === "assistant" || role === "pm") return "assistant";
  return "role";
}
function avatarColor(name) {
  let h = 0;
  for (const ch of String(name || "")) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return AVATAR_PALETTE[h % AVATAR_PALETTE.length];
}
function initial(name) {
  const s = String(name || "?").trim();
  return s ? esc(s[0]) : "?";
}
function chatHtml(sec, ctx) {
  const src = ref(sec.source, ctx) || {};
  const roles = ref(sec.roles_source, ctx) || [];
  const hidden = sec.hide_roles || [];
  const msgs = arr(src.messages).filter((m) => !hidden.includes(m.role || ""));
  const headTitle = sec.heading ? `<div class="chat-title">${esc(fill(sec.heading, ctx))}</div>` : "";
  const body = msgs.length ? renderBubbles(msgs, roles) : `<div class="chat-empty">${esc(fill(sec.empty || "", ctx))}</div>`;
  return `<section class="chat-card card">
    ${headTitle ? `<div class="chat-head">${headTitle}<div class="spacer" style="margin-left:auto"></div><div class="chips">${arr(roles).map((r) => `<span class="chip">${esc((r.display || r.role) + " · " + (r.status || ""))}</span>`).join("")}</div></div>` : ""}
    <div class="chat">${body}</div>
  </section>`;
}
function renderBubbles(msgs, roles) {
  const groups = [];
  for (const m of msgs) {
    const cls = bubbleClass(m);
    const who = cls === "system" ? "" : speakerOf(m, roles);
    const key = cls + "|" + who;
    const last = groups[groups.length - 1];
    if (last && last.key === key) last.msgs.push(m);
    else groups.push({ key, cls, who, msgs: [m] });
  }
  return groups.map((g) => {
    if (g.cls === "system") {
      return g.msgs.map((m) => `<div class="msg system"><div class="sys-body">${esc(m.content == null ? "" : m.content)}</div></div>`).join("");
    }
    const side = g.cls === "user" ? "right" : "left";
    const av = `<div class="avatar" style="--av:${avatarColor(g.who)}">${initial(g.who)}</div>`;
    const bodies = g.msgs.map((m) => `<div class="bubble-body">${esc(m.content == null ? "" : m.content)}</div>`).join("");
    const last = g.msgs[g.msgs.length - 1];
    const ts = last.ts ? `<div class="msg-ts">${when(last.ts)}</div>` : "";
    return `<div class="msg ${side}">${side === "left" ? av : ""}
      <div class="msg-main"><div class="msg-name">${esc(g.who)}</div>
      <div class="bubble-stack">${bodies}</div>${ts}</div>${side === "right" ? av : ""}</div>`;
  }).join("");
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

function composerHtml(sec, ctx) {
  const disabled = sec.disabled_when != null && condOf(sec.disabled_when, ctx);
  const submit = sec.submit || {};
  ACTS.push({ act: submit, ctx, composer: true });
  const submitIdx = ACTS.length - 1;
  const acts = (sec.actions || []).map((a) => buttonHtml({ ...a, composer: true }, ctx)).join("");
  return `<div class="composer">
    <textarea placeholder="${esc(fill(sec.placeholder || "", ctx))}" ${disabled ? "disabled" : ""}></textarea>
    ${acts}
    <button class="primary" data-act="${submitIdx}" ${disabled ? "disabled" : ""}>${esc(fill(submit.label || "发送", ctx))}</button>
  </div>`;
}

function sectionHtml(sec, ctx) {
  const kind = sec.kind;
  let html = "";
  if (kind === "cards") html = cardsHtml(sec, ctx);
  else if (kind === "table") html = tableHtml(sec, ctx);
  else if (kind === "chat") html = chatHtml(sec, ctx);
  else if (kind === "kv") html = kvHtml(sec, ctx);
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
    body = `<div class="ticket-grid">
      <div class="lane lane-left">${left.join("")}</div>
      <div class="lane lane-right">${right.join("")}</div>
    </div>`;
  }
  $("view-body").innerHTML = head + body;
}
