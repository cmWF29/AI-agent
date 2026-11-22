/* render：规格 -> DOM（只认原语 cards/table/chat/kv/composer/empty）
   只认识原语（cards / table / chat / kv / composer / empty），不认识业务。
*/
/* 点击绑定用"单调 id 表"，不用数组下标：
   下标会被下一次渲染/别的页面改写，保活页拿回来的 DOM 就会点到别人身上（或点空）。 */
/* 折叠态：键 = 内容身份（会话/序位/工具/标签），存在 sessionStorage，
   任何一次重渲染或整页刷新都按原状恢复；展开是用户的意图，不能被渲染抹掉。 */
function foldLoad() {
  try { return new Map(Object.entries(JSON.parse(sessionStorage.getItem("hive.folds") || "{}"))); }
  catch (e) { return new Map(); }
}
let FOLDS = foldLoad();
function foldSet(key, open) {
  if (!key) return;
  FOLDS.set(key, !!open);
  try {
    const obj = {};
    for (const [k, v] of FOLDS) if (v) obj[k] = true;   // 只存展开的，数量有界
    sessionStorage.setItem("hive.folds", JSON.stringify(obj));
  } catch (e) {}
}
function foldAttr(key) {
  if (!key) return "";
  return ` data-fold="${esc(key)}"${FOLDS.get(key) ? " open" : ""}`;
}

function regAct(binding) {
  ACT_SEQ += 1;
  const id = "a" + ACT_SEQ;
  ACTS.set(id, binding);
  return id;
}
/* 控件身份：每个按钮一个稳定 id，由"标签 + 控件种类"算出（显式 ctl 可覆盖）。
   规格里 controls: 按同一套算法登记，增删按钮立刻对不上，门禁脚本就报错。 */
function ctlSlug(label) {
  return String(label == null ? "" : label)
    .replace(/[\s+＋]/g, "")
    .replace(/[^0-9A-Za-z_\-\u4e00-\u9fff]/g, "_") || "x";
}
function ctlOf(act, kind) {
  if (act && act.ctl) return String(act.ctl);
  return "ctl." + String(kind || "card_act") + "." + ctlSlug(act && act.label);
}
function actIndex(act, ctx) {
  return regAct({ act, ctx });
}
function buttonHtml(act, ctx, opts) {
  opts = opts || {};
  const binding = { act, ctx };
  const kind = act.clk || opts.clk || "card_act";
  if (opts.composer) binding.composer = true;
  const id = regAct(binding);
  const ctl = String(act.ctl || opts.ctl || ctlOf(act, kind));
  const disabled = opts.disabled === true
    || (act.disabled_when != null && condOf(act.disabled_when, ctx));
  const hint = act.disabled_hint || opts.hint || "";
  const title = disabled && hint ? ` title="${esc(hint)}"` : "";
  const cls = act.tone === "primary" ? "primary" : (act.tone === "danger" ? "danger" : "");
  // data-ctl 是这个按钮自己的状态机名：门禁脚本按它比对规格，浏览器按它读状态
  const st = disabled ? "disabled" : "idle";
  return `<button class="${cls}" data-clk="${esc(kind)}" data-act="${id}" data-ctl="${esc(ctl)}" data-ctl-state="${st}" ${disabled ? "disabled" : ""}${title}>${esc(fill(act.label, ctx))}</button>`;
}
function badgeHtml(value, ctx) {
  const s = String(value == null ? "" : value);
  const kind = statusKind(s);
  const cls = kind === "offline" ? "closed" : (kind === "busy" ? "open" : "");
  return `<span class="badge ${cls}">${esc(s || uiText("badge_offline"))}</span>`;
}
/* 状态语义在 shell.status：哪些值算忙、哪些算下线、显示什么字，后端说了算 */
function statusKind(s) {
  s = String(s == null ? "" : s);
  if (STATUS_META.busy.includes(s)) return "busy";
  if (STATUS_META.offline.includes(s)) return "offline";
  return "idle";
}
function statusText(s) {
  return STATUS_META.labels[statusKind(s)] || "";
}
function emptyHtml(block) {
  block = block || {};
  return `<div class="empty">${block.title ? `<strong>${esc(fill(block.title, {}))}</strong>` : ""}${esc(fill(block.text || "", {}))}</div>`;
}

function cardsHtml(sec, ctx) {
  const rows = arr(ref(sec.source, ctx));
  if (!rows.length) return sec.hide_when_empty ? "" : emptyHtml(sec.empty);
  // layout: deck = 卡片堆叠：收缩时叠在一起、左右滑动换牌，点「展开」铺成列表
  const deck = sec.layout === "deck";
  const cards = rows.map((row, idx) => {
    const c = { ...ctx, row };
    const archived = sec.archived_when != null && condOf(sec.archived_when, c);
    const acts = (sec.actions || []).map((a) => buttonHtml(a, c, { clk: "card_act" })).join("");
    const badge = (sec.badge && condOf(sec.badge.when, c))
      ? `<span class="badge archived">${esc(fill(sec.badge.text, c))}</span>` : "";
    const stat = sec.stat ? `<div class="stat"><b>${esc(fill(sec.stat.count, c))}</b> ${esc(fill(sec.stat.label, c))}<span class="muted">· ${esc(fill(sec.stat.note || "", c))}</span></div>` : "";
    const metaVal = (m) => {
      const v = fmtVal(m, c);
      if (v === undefined || v === null || v === "") return m.fallback ? fill(m.fallback, c) : "";
      return v;
    };
    const meta = (sec.meta || []).filter((m) => m.hide_if_empty ? !!metaVal(m) : true)
      .map((m) => `<span>${esc(fill(m.label, c))} ${esc(metaVal(m))}</span>`).join("");
    const groups = Array.isArray(sec.chips) ? sec.chips : (sec.chips ? [sec.chips] : []);
    const chips = groups.map((g) => shareChips(g, c)).join("");
    const click = sec.on_click ? actIndex({ view: sec.on_click.view, params: sec.on_click.params || {} }, c) : "";
    return `<article class="pcard${archived ? " archived" : ""}" data-clk="card_open" ${click ? `data-go="${click}"` : ""}${deck ? ` data-deck-i="${idx}"` : ""} role="button" tabindex="0" aria-label="${esc(uiText("card_open", fill(sec.title, c)))}">
      <div class="phead">
        <h3 class="pname">${esc(fill(sec.title, c))}</h3>
        ${badge}
        <div class="acts">${acts}</div>
      </div>
      ${stat}
      <div class="meta">${meta}</div>
      ${chips}
      <span class="ar">›</span>
    </article>`;
  }).join("");
  // 只有一张牌时堆叠没有意义（还会多出一次"滑不动"的手势），退回普通列表
  if (!deck || rows.length < 2) return `<div class="cards">${cards}</div>`;
  return `<div class="cards deck" data-deck="1" data-open="0" data-pos="0">
    <div class="deck-bar">
      <span class="deck-pos">${esc(uiText("deck_pos", 1, rows.length))}</span>
      <button class="deck-more" data-clk="deck_toggle" data-deck-open="1">${esc(uiText("deck_expand", rows.length))}</button>
    </div>
    <div class="deck-stage" data-clk="deck_swipe">${cards}</div>
  </div>`;
}

function shareChips(spec, c) {
  if (!spec || !spec.from) return "";
  const rows = arr(fill(spec.from, c));
  if (!rows.length) return "";
  const items = rows.map((x) => `<span class="chip">${spec.text ? esc(dig(x, spec.text))
    : esc(typeof x === "object" ? (x.cn || x.id || "") : x)}</span>`).join("");
  const label = spec.label ? `<span class="chips-label">${esc(fill(spec.label, {}))}</span>` : "";
  return `<div class="chips-row">${label}<div class="chips">${items}</div></div>`;
}

function tableHtml(sec, ctx) {
  const rows0 = arr(ref(sec.source, ctx));
  let rows = rows0.slice();
  if (sec.sort) {
    const by = sec.sort.by, dir = sec.sort.order === "asc" ? 1 : "";
    rows.sort((a, b) => dir * String(dig(a, by) || "").localeCompare(String(dig(b, by) || "")));
  }
  let truncated = 0;
  if (sec.limit && rows.length > sec.limit) { truncated = rows.length - sec.limit; rows = rows.slice(0, sec.limit); }
  const filters = sec.filters || [];
  if (filters.length) {
    const active = filters.find((f) => f.key === FILTER) || filters[0];
    if (active && active.keep) rows = rows.filter((r) => matchCond(r, active.keep));
    sec._active = active ? active.key : null;
  }
  const head = `<div class="tbl-head">
    ${sec.heading ? `<strong style="font-size:13px">${esc(fill(sec.heading, ctx))}</strong>` : ""}
    ${sec.count_note ? `<span class="muted">${esc(fill(sec.count_note, ctx))}</span>` : ""}
    ${truncated ? `<span class="muted">… ${esc(uiText("more_rows", truncated))}</span>` : ""}
    <div class="spacer" style="margin-left:auto"></div>
    ${filters.length ? `<span class="seg" id="seg">${filters.map((f) =>
      `<button data-clk="filter" data-filter="${esc(f.key)}" class="${f.key === (sec._active || filters[0].key) ? "on" : ""}">${esc(f.label)}</button>`).join("")}</span>` : ""}
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
        val = Array.isArray(raw)
          ? (col.chips ? raw.map((x) => `<span class="chip">${esc(x)}</span>`).join("") : raw.map((x) => esc(x)).join("<br>"))
          : esc(raw);
        if (col.suffix) val += ` ${esc(fill(col.suffix, c))}`;
        if (col.sub) val += `<div class="muted">${esc(fill(col.sub, c))}</div>`;
      }
      if (val === "" || val === "undefined") val = esc(col.fallback ? fill(col.fallback, c) : "—");
      // 列名同时写进单元格：手机端表格会折成「字段 + 值」的行式卡片，靠这个标签对齐
      const th = esc(fill(col.label || "", c));
      return `<td class="${col.muted ? "muted" : ""}"${th ? ` data-th="${th}"` : ""}>${val}</td>`;
    }).join("");
    const acts = rowActs.length ? `<td class="actions">${rowActs.map((a) => buttonHtml(a, c, { clk: "row_act" })).join("")}</td>` : "";
    const click = sec.on_click ? actIndex({ view: sec.on_click.view, params: sec.on_click.params || {} }, c) : "";
    return `<tr data-clk="row_open" ${click ? `data-go="${click}"` : ""}>${cells}${acts}</tr>`;
  }).join("") : `<tr><td colspan="${cols.length + (rowActs.length ? 1 : 0)}" class="muted">${esc((sec.empty || {}).text || uiText("empty"))}</td></tr>`;
  if (sec.hide_when_empty && !rows0.length) return "";
  const actHead = rowActs.length ? "<th>" + esc(uiText("col_actions")) + "</th>" : "";
  const wrap = `<div class="tbl-wrap">${sec.heading || filters.length || sec.count_note ? head : ""}<table>
    <thead><tr>${cols.map((c) => `<th>${esc(c.label || "")}</th>`).join("")}${actHead}</tr></thead>
    <tbody>${body}</tbody></table></div>`;
  if (sec.summarize) {
    return `<div class="orphans"><details><summary data-clk="summary_fold">${esc(fill(sec.title || "", ctx))}（${rows0.length}）</summary>${wrap}</details></div>`;
  }
  return wrap;
}

/* 角色固定配色：同名同色，跨会话一致；配色表与回退色板都由后端下发 */
function paletteOf() { return ROLE_PALETTE.length ? ROLE_PALETTE : ["#2f6bff"]; }
function speakerOf(msg, roles) {
  if (msg.kind === "note") return roleLabel("system");
  const actor = msg.actor || msg.role || "assistant";
  if (actor === "tool") return msg.name ? (roleLabel("tool") + " · " + msg.name) : roleLabel("tool");
  const hit = (roles || []).find((r) => r.role === actor || r.session === actor);
  if (hit && (hit.display || hit.role)) return hit.display || hit.role;
  return roleLabel(actor);
}
function bubbleClass(msg) {
  if (msg.kind === "note") return "system";
  if (msg.role === "tool") return "tool";
  if (msg.role === "system") return "system";
  // 左右按发言人不按 role：PM 与各角色都是群成员（左），只有真人输入在右。
  // 会话装配会把工单简介等注入消息 role 记为 user，靠 actor 才不会让同一个人左右横跳。
  const actor = msg.actor || msg.role || "assistant";
  if (actor === "user") return "user";
  if (actor === "system") return "system";
  return "member";
}
function avatarColor(name) {
  const key = String(name || "").trim();
  if (ROLE_COLORS[key]) return ROLE_COLORS[key];
  const pal = paletteOf();
  let h = 0;
  for (const ch of key) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return pal[h % pal.length];
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
      return task ? roleOf(one.text) + " · " + task : roleOf(one.text) + " " + uiText("role_spawned");
    }
    const roles = items.map((h) => roleOf(h.text)).filter(Boolean);
    return roles.length ? roles.join("、") + " " + uiText("role_spawned") : "";
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
  if (at == null || at === "" || at === 0 || at === "0") return "";
  const t = atSeconds(at);
  if (!isFinite(t)) return "";
  const d = new Date(t * 1000);
  // 只给时分看不出是哪天：会话可能跨周，一律带年月日
  return d.toLocaleString("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit",
                                     hour: "2-digit", minute: "2-digit" });
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
  // 合并事件按发生时刻排：取组内首条，保证「派角色 ×3」落在三个角色干活之前
  return groups.map((g) => ({
    kind: "event", event: g.event, items: g.items,
    at: atSeconds((g.items[0] || {}).at),
  }));
}
function eventGroupHtml(g) {
  const n = g.items.length;
  const label = eventLabel(g.event);
  const cnt = n > 1 ? ` ×${n}` : "";
  const first = g.items[0] || {};
  const text = eventText(g);
  const long = text.length > 60;
  const shown = long ? text.slice(0, 58) + "…" : text;
  const fold = long ? ` data-clk="fold_text" data-expand data-full="${esc(text)}" data-short="${esc(shown)}"` : "";
  return `<div class="msg event"><div class="sys-body${long ? " clamp" : ""}"${fold}><span class="ev-line"><span class="ev-label">${esc(label + cnt)}</span>${shown ? `<span class="ev-text">${esc(shown)}</span>` : ""}</span><span class="ev-ts">${esc(when(first.at))}</span></div></div>`;
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
                     at: atSeconds(m.at), owner: m };
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
  if (!o || typeof o !== "object") return { ok: true, text: raw.replace(/\s+/g, " ").slice(0, 92) };
  if (o.ok === false) return { ok: false, text: String(o.error || raw).slice(0, 120) };
  const res = (o.result && typeof o.result === "object") ? o.result : o;
  for (const k of ["text", "content", "summary", "message"]) {
    for (const src of [res, o]) {
      const v = src[k];
      if (typeof v === "string" && v.trim()) return { ok: true, text: v.trim().replace(/\s+/g, " ").slice(0, 92) };
    }
  }
  if (res.size === 0) return { ok: true, text: uiText("empty_file") };
  const bits = [];
  const items = Array.isArray(o.items) ? o.items : (Array.isArray(res.items) ? res.items : null);
  if (items) bits.push(items.length + " " + uiText("items_unit"));
  for (const k of FIELD_ORDER) {
    if (k === "demand") continue;
    let v = res[k];
    if (v == null || v === "" || typeof v === "object") continue;
    if (typeof v === "boolean") v = v ? uiText("stamp_yes") : uiText("stamp_no");
    bits.push((FIELD_LABELS[k] || k) + " " + v);
    if (bits.length >= 3) break;
  }
  return { ok: true, text: bits.join(" · ") || uiText("done_word") };
}
/* 工具卡：只有一种形状——头行（工具名 + 参数）+ 结果体 + 可选原文。
   调用与结果、有无 tool_call 配对，都落到同一张卡里，不再"有的嵌套有的没有"。 */
function toolResultBody(o, raw, foldKey) {
  const res = (o.result && typeof o.result === "object") ? o.result : o;
  const metaObj = Object.assign({}, res, o);
  ["result", "effects", "applied", "history", "items"].forEach((k) => delete metaObj[k]);
  const parts = [];
  parts.push(toolMetaChips(metaObj));
  if (Array.isArray(res.items)) {
    if (!res.items.length) parts.push(`<div class="tool-empty">${esc(uiText("call_empty"))}</div>`);
    else parts.push(`<ul class="tool-items">${res.items.map((it) => {
      const label = typeof it === "string" ? it : (it.title || it.path || it.summary || JSON.stringify(it));
      return `<li>${esc(label)}</li>`;
    }).join("")}</ul>`);
  }
  toolCollectTexts(o).forEach((t) => parts.push(`<div class="tool-text md">${renderMarkdown(t)}</div>`));
  parts.push(toolTraceHtml(o));
  let pretty = raw;
  try { pretty = JSON.stringify(o, null, 2); } catch (e) {}
  parts.push(`<details class="tool-raw"${foldAttr(foldKey)}><summary data-clk="raw_fold">${esc(uiText("call_raw"))}</summary><pre>${esc(pretty)}</pre></details>`);
  return parts.join("");
}
function toolCardHtml(name, args, raw, foldKey) {
  const argsText = String(args || "").trim();
  const argsHtml = argsText && argsText !== "{}"
    ? `<span class="tool-call-args">${esc(argsText.length > 72 ? argsText.slice(0, 72) + "…" : argsText)}</span>` : "";
  const inner = `<span class="tool-call-name">${esc(name || "tool")}</span>${argsHtml}`;
  const head = `<div class="tool-call-head">${inner}</div>`;                 // 只读小卡（结果未到/报错）不折叠
  const fhead = `<summary class="tool-call-head">${inner}</summary>`;        // 可折叠卡：点头行才展开细节
  if (!raw) return `<div class="tool-call">${head}<div class="tool-line pending">${esc(uiText("call_pending"))}</div></div>`;
  let o = null;
  try { o = JSON.parse(raw); } catch (e) {}
  if (o && typeof o === "object" && o.ok === false) {
    return `<div class="tool-call error">${head}<div class="tool-line err md">${renderMarkdown(o.error || raw)}</div></div>`;
  }
  if (o && typeof o === "object") {
    return `<details class="tool-call"${foldAttr(foldKey)}>${fhead}<div class="tool-call-body">${toolResultBody(o, raw, foldKey)}</div></details>`;
  }
  return `<details class="tool-call"${foldAttr(foldKey)}>${fhead}<div class="tool-call-body"><div class="tool-line md">${renderMarkdown(String(raw))}</div></div></details>`;
}
function toolCallCard(it) {
  const raw = it.result ? String(it.result.content == null ? "" : it.result.content) : "";
  const key = "tool|" + String(it.name || "") + "|" + String(it.at || "") + "|" + raw.length;
  return toolCardHtml(it.name, it.args, raw, key);
}
function toolBodyHtml(m) {
  const raw = m.content == null ? "" : String(m.content);
  let o = null;
  try { o = JSON.parse(raw); } catch (e) {}
  const name = m.name || (o && (o.tool || o.name)) || "";
  const key = "tool|" + String(name) + "|" + String(m.at || "") + "|" + raw.length;
  return toolCardHtml(name, "", raw, key);
}
function itemHtml(it) {
  if (it.kind === "call") return toolCallCard(it);
  if (it.kind === "tool") return toolBodyHtml(it.m);
  const m = it.m;
  const text = String(m.content == null ? "" : m.content).trim();
  if (!text) return "";
  return `<div class="bubble-body md">${renderMarkdown(m.content)}</div>`;
}
/* 可点位置统一补控件 id：data-clk 就是它的点击种类，没登记的按「ctl.<种类>」兜底。
   目的只有一个——页面上不存在"看不见的可点区域"，清点脚本能逐个点名。 */
function stampCtl(root) {
  (root || document).querySelectorAll("[data-clk]").forEach((el) => {
    if (!el.dataset.ctl) el.dataset.ctl = "ctl." + el.dataset.clk;
    if (!el.dataset.ctlState) el.dataset.ctlState = "idle";
  });
}
/* 一条发言里的工具往返收成一个折叠块：群聊只看到「工具调用 ×N」，点开才是明细 */
function toolGroupHtml(items) {
  const cards = items.map((it) => (it.kind === "call" ? toolCallCard(it) : toolBodyHtml(it.m))).join("");
  const fails = items.filter((it) => it.kind === "call" && it.result && !toolBrief(it.result).ok).length;
  const first = items[0] || {};
  const key = "group|" + String((first.owner || first.m || {}).session || "") + "|" + String(first.at || "");
  const title = uiText("tool_group", items.length) + (fails ? uiText("tool_group_fail", fails) : "");
  return `<details class="tool-group"${foldAttr(key)}><summary data-clk="raw_fold">${esc(title)}</summary><div class="tool-group-body">${cards}</div></details>`;
}
function groupBody(g) {
  const calls = [];
  const texts = [];
  for (const it of g.items) {
    if (it.kind === "call" || it.kind === "tool") { calls.push(it); continue; }
    const html = itemHtml(it);
    if (html) texts.push(html);
  }
  return (calls.length ? toolGroupHtml(calls) : "") + texts.join("");
}

function renderBubbles(msgs, roles, wireDemand, wireChars, rawChars) {
  const groups = [];
  for (const it of pairItems(msgs)) {
    const m = it.owner || it.m || {};
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
    const bodies = groupBody(g);
    if (!bodies) return "";
    const av = `<div class="avatar" style="--av:${avatarColor(g.who)}">${initial(g.who)}</div>`;
    const ts = clockText((g.items[g.items.length - 1] || {}).at);
    return `<div class="msg ${side}">${side === "left" ? av : ""}
      <div class="msg-main"><div class="msg-name">${esc(g.who)}</div>
      <div class="bubble-stack">${bodies}</div>${ts ? `<div class="msg-ts">${esc(ts)}</div>` : ""}
      ${wireHtml(g.items, wireDemand, wireChars)}
      ${rawHtml(g.items.map((it) => it.owner || it.m).filter(Boolean), uiText("raw_title"), rawChars)}</div>${side === "right" ? av : ""}</div>`;
  }).join("");
}

/* 消息与工单历程事件按时间穿插：同一时刻先消息后事件，无时间戳的排最前保序 */
function streamHtml(msgs, events, roles, wireDemand, wireChars, rawChars) {
  const stream = [];
  msgs.forEach((m, i) => stream.push({ kind: "m", at: atSeconds(m.at), i, m }));
  events.forEach((e, i) => stream.push({ kind: "e", at: e.at, i: msgs.length + i, e }));
  stream.sort((a, b) => (a.at === b.at ? a.i - b.i : (a.at < b.at ? -1 : 1)));
  const out = [];
  let buf = [];
  const flush = () => {
    if (buf.length) { out.push(renderBubbles(buf, roles, wireDemand, wireChars, rawChars)); buf = []; }
  };
  for (const s of stream) {
    if (s.kind === "m") { buf.push(s.m); continue; }
    flush();
    out.push(eventGroupHtml(s.e));
  }
  flush();
  return out.join("");
}

/* 角色状态条：每个角色当前阶段与活跃状态，点开是同一个人（data-member 复用成员卡） */
function roleBoardHtml(roles) {
  const rows = arr(roles).filter((r) => r && ((r.machine || {}).states || []).length);
  if (!rows.length) return "";
  const cells = rows.map((r) => {
    const mc = r.machine || {};
    const states = mc.states || [];
    const cur = states.find((s) => s.id === mc.stage) || {};
    const acts = (mc.active || []).filter((id) => id !== mc.stage)
      .map((id) => (states.find((s) => s.id === id) || {}).cn || id);
    const idx = arr(roles).indexOf(r);
    return `<button class="role-mini st-${statusKind(r.status)}" data-clk="member_chip" data-member="${idx}" title="${esc((mc.flow || {}).cn || "")}">
      <i class="rm-dot"></i><b>${esc(r.display || r.role)}</b>
      <span class="rm-stage">${esc(cur.cn || "—")}</span>
      ${acts.length ? `<span class="rm-active">${esc(acts.join("/"))}</span>` : ""}
    </button>`;
  }).join("");
  return `<div class="role-board">${cells}</div>`;
}
/* 待办板：模型自己排的分步计划，和岗位流程状态机不是一回事，单独一条 */
function todoBoardHtml(todos) {
  const list = arr(todos);
  if (!list.length) return "";
  const done = list.filter((t) => (t.status || "") === "done").length;
  const doing = list.find((t) => (t.status || "") === "doing");
  const rows = list.map((t) => {
    const st = t.status || "pending";
    const word = st === "done" ? uiText("todo_state_done")
      : (st === "doing" ? uiText("todo_state_doing") : uiText("todo_state_pending"));
    return `<div class="td-row"><i class="td-dot ${esc(st)}"></i><span class="td-id">${esc(t.id || "")}</span><span class="td-text ${st === "done" ? "off" : ""}">${esc(t.text || "")}</span><em>${esc(word)}</em></div>`;
  }).join("");
  return `<details class="todo-board"><summary data-clk="summary_fold"${esc(uiText("todo_title", done, list.length))}${doing ? esc(uiText("todo_doing", doing.text || "")) : ""}</summary><div class="td-list">${rows}</div></details>`;
}

/* 网络报文：这一轮真实发出去/收回来的东西。视图只带摘要（模型、状态、字节量），
   请求体与响应原文在展开时按会话与序位回读 message-wire，不随首屏下发。 */
function wireHtml(items, demand, chars) {
  const hit = arr(items).find((it) => {
    const w = ((it.owner || it.m) || {}).wire;
    return w && w.url;
  });
  if (!hit) return "";
  const m = hit.owner || hit.m || {};
  const w = m.wire;
  const size = (v) => (typeof v === "number" && v > 0 ? uiText("chars_unit", v) : "—");
  if (!demand) return "";
  const foldKey = "wire|" + String(m.session || "") + "|" + String(w.seq == null ? -1 : w.seq);
  return `<details class="raw-box wire-box"${foldAttr(foldKey)} data-clk="wire_fold" data-demand="${esc(demand)}" data-chars="${esc(String(chars || 0))}" data-session="${esc(m.session || "")}" data-seq="${esc(String(w.seq == null ? -1 : w.seq))}"><summary data-clk="wire_fold">${esc(uiText("wire_title"))} · ${esc(w.model || "")} · HTTP ${esc(String(w.status == null ? "—" : w.status))} · ${esc(uiText("wire_req"))} ${esc(size(w.req_len))} / ${esc(uiText("wire_resp"))} ${esc(size(w.res_len))}</summary>
    <pre class="wire-body">${esc(uiText("wire_expand"))}</pre></details>`;
}

/* 结构化原文：所有通信都是结构化对象，原样吐出看得到字段，不用猜 */
function rawHtml(objs, label, limit) {
  const list = arr(objs);
  if (!list.length) return "";
  let text = "";
  try {
    text = jsyaml.dump(list, { noRefs: true, lineWidth: 140, sortKeys: false });
  } catch (e) {
    try { text = JSON.stringify(list, null, 2); } catch (e2) { text = String(list); }
  }
  const cap = limit || 6000;
  const cut = text.length > cap ? text.slice(0, cap) + "\n" + uiText("trunc_note", text.length) : text;
  const first = list[0] || {};
  const foldKey = "raw|" + String(label || "") + "|" + String(first.session || "") + "|" +
    String(first.at || "") + "|" + list.length;
  return `<details class="raw-box"${foldAttr(foldKey)} data-clk="raw_fold"><summary data-clk="raw_fold">${esc(label)}</summary><pre>${esc(cut)}</pre></details>`;
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
  const chips = arr(roles).map((r, i) => `<button class="av-chip st-${statusKind(r.status)}" data-clk="member_chip" data-member="${i}"
      style="--av:${avatarColor(r.display || r.role)}" title="${esc(r.display || r.role)} · ${statusText(r.status)}">${initial(r.display || r.role)}<i class="dot"></i></button>`).join("");
  const draft = (ctx.data && ctx.data.draft) || {};
  const draftHtml = draftBubbleHtml(draft, roles);
  const summary = (src.summary || "").trim();
  const summaryHtml = summary ? `<details class="chat-summary"><summary data-clk="summary_fold">${esc(uiText("summary_title"))}</summary><div class="chat-summary-text">${esc(summary)}</div></details>` : "";
  const hiddenEvents = sec.hide_events || [];
  const events = groupEvents(sec.history_source ? ref(sec.history_source, ctx) : undefined)
    .filter((g) => !hiddenEvents.includes(g.event));
  const stream = streamHtml(msgs, events, roles, sec.wire_demand || "", sec.wire_chars || 0, sec.raw_chars || 0);
  const hiddenMsgs = arr(src.messages).filter((m) => hidden.includes(m.role || ""));
  const inject = hiddenMsgs.length
    ? `<div class="inject">${rawHtml(hiddenMsgs, uiText("inject_title", hiddenMsgs.length))}</div>` : "";
  const body = inject + todoBoardHtml(src.todos) +
    (stream || `<div class="chat-empty">${esc(fill(sec.empty || "", ctx))}</div>`) + draftHtml;
  return `<section class="chat-card card">
    ${headMain || chips ? `<div class="chat-head">${headMain}<div class="members">${chips}</div></div>` : ""}
    ${summaryHtml}
    ${roleBoardHtml(roles)}
    <div class="chat">${body}</div>
  </section>`;
}
/* 工具结果字段的显示名与顺序来自后端词表，前端不认识任何字段名 */

function toolMetaChips(obj) {
  const chips = [];
  for (const k of FIELD_ORDER) {
    let v = obj[k];
    if (v == null || v === "") continue;
    if (typeof v === "boolean") v = v ? uiText("stamp_yes") : uiText("stamp_no");
    chips.push(`<span class="tool-meta-item"><b>${esc(FIELD_LABELS[k] || k)}</b> ${esc(v)}</span>`);
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
    const seg = (a.written === false ? uiText("not_written") : uiText("written")) + (a.path ? " · " + a.path : "");
    lines.push(seg);
  });
  (o.history || []).forEach((h) => {
    if (h && h.text) lines.push((h.event || uiText("record")) + " · " + String(h.text).slice(0, 120));
  });
  return lines.length ? `<div class="tool-trace">${lines.map(esc).join("<br>")}</div>` : "";
}

function treeDocHtml(doc, sec, ctx) {
  const c = { ...ctx, row: doc };
  const click = sec.on_click ? actIndex({ view: sec.on_click.view, params: sec.on_click.params || {} }, c) : "";
  // 没有跳转目标的叶子就是纯展示行：不注册点击种类，点了也不算违规
  if (!click) return `<div class="tree-doc"><span class="tree-doc-name">${esc(fill("row.name", c))}</span><span class="muted tree-doc-path">${esc(fill("row.path", c))}</span></div>`;
  return `<div class="tree-doc" data-clk="tree_doc" data-go="${click}" role="button" tabindex="0">
    <span class="tree-doc-name">${esc(fill("row.name", c))}</span>
    <span class="muted tree-doc-path">${esc(fill("row.path", c))}</span>
  </div>`;
}
function treeNodeHtml(node, sec, ctx, path) {
  // 叶子（doc/log/交付件）没有 children 键，一律渲染成可点的行；
  // 分组（公共/项目/工单）恒有 children：没有条目也要露出这一级，否则层级就断了
  if (!("children" in node)) return treeDocHtml(node, sec, ctx);
  const kids = node.children || [];
  const count = kids.length;
  const sub = node.sub ? `<span class="muted tree-node-sub">${esc(node.sub)}</span>` : "";
  const here = ((ctx.route || {}).view || "") + ":" + (path || "tree") + "/" + (node.type || "g") + ":" + (node.label || "");
  if (!count) {
    // 空层不装成可折叠的样子：一行说明，不给假三角也不给占位壳
    return `<div class="tree-node tree-node-blank muted">${esc(node.label || "")} · ${esc(uiText("tree_empty_layer") || uiText("empty_tree"))}</div>`;
  }
  // 折叠是用户意图：键挂内容身份，重渲染/刷新按原状恢复；没动过按声明默认展开
  const stored = FOLDS.get(here);
  const openAttr = (stored === undefined ? !sec.collapsed : !!stored) ? " open" : "";
  return `<details class="tree-node" data-fold="${esc(here)}"${openAttr}>
    <summary data-clk="tree_group"><span class="badge">${esc(node.badge || "")}</span><span class="tree-node-label">${esc(node.label || "")}</span>${sub}${sec.hide_count ? "" : `<span class="muted tree-node-count">${count}</span>`}</summary>
    <div class="tree-children">${kids.map((k) => treeNodeHtml(k, sec, ctx, here)).join("")}</div>
  </details>`;
}
function secHead(sec, ctx) {
  if (sec.fold || (!sec.heading && !sec.note)) return "";
  return `<div class="sec-head">${sec.heading ? `<strong>${esc(fill(sec.heading, ctx))}</strong>` : ""}${
    sec.note ? `<span class="muted">${esc(fill(sec.note, ctx))}</span>` : ""}</div>`;
}

function statsHtml(sec, ctx) {
  const rows = sec.rows || [];
  if (!rows.length) return "";
  const cells = rows.map((r) => {
    const v = fill(r.value, ctx);
    // 读法固定：先标题、再数字、最后一行说明。倒过来是"9 张工单"式的错位阅读
    return `<div class="stat-cell"><span class="stat-label">${esc(fill(r.label, ctx))}</span><b>${esc(v === "" ? "—" : v)}</b>${
      r.note ? `<em>${esc(fill(r.note, ctx))}</em>` : ""}</div>`;
  }).join("");
  return `<div class="stat-strip">${cells}</div>`;
}

function wfMs(v) { const n = Number(v || 0); return Number.isFinite(n) && n > 0 ? n : 0; }
function wfStart(s) { return wfMs(s.start); }
function wfDur(s) { return wfMs(s.dur_ms); }
function wfFmt(ms) {
  if (ms >= 1000) return (ms / 1000).toFixed(2) + "s";
  if (ms >= 10) return ms.toFixed(1) + "ms";
  return ms.toFixed(2) + "ms";
}
function waterfallHtml(sec, ctx) {
  const head = secHead(sec, ctx);
  const spans = arr(ref(sec.source, ctx));
  if (!spans.length) return head + emptyHtml(sec.empty);
  const by = {};
  spans.forEach((s) => { if (s && s.span) by[s.span] = s; });
  // 父节点：优先采信记录里的 parent；跨执行器/跨通道丢了父时，用时间包含关系推断
  // （真实嵌套必然"包含 + 起点不晚"，取包含者里最内层那个）。
  const inferParent = (s) => {
    const b0 = wfStart(s), b1 = b0 + wfDur(s) / 1000;
    let best = null;
    for (const o of spans) {
      if (!o || o === s || !o.span) continue;
      const a0 = wfStart(o), a1 = a0 + wfDur(o) / 1000;
      if (a0 > b0 + 1e-6 || a1 < b1 - 1e-6) continue;
      if (wfDur(o) <= wfDur(s) + 0.005) continue;
      if (!best || a0 > wfStart(best) || (a0 === wfStart(best) && wfDur(o) < wfDur(best))) best = o;
    }
    return best ? best.span : "";
  };
  const parentOf = (s) => (s.parent && by[s.parent]) ? s.parent : inferParent(s);
  const depthOf = (s) => {
    let d = 0, p = parentOf(s), seen = {};
    while (p && by[p] && !seen[p] && d < 12) { seen[p] = 1; d += 1; p = parentOf(by[p]); }
    return d;
  };
  let t0 = Infinity, t1 = -Infinity;
  spans.forEach((s) => {
    const a = wfStart(s);
    t0 = Math.min(t0, a);
    t1 = Math.max(t1, a + wfDur(s) / 1000);
  });
  const total = Math.max(0.001, (isFinite(t1) ? t1 : 0) - (isFinite(t0) ? t0 : 0));
  const rows = spans.slice().sort((a, b) => wfStart(a) - wfStart(b) || depthOf(a) - depthOf(b));
  const bars = rows.map((s) => {
    const d = Math.min(depthOf(s), 3), a = wfStart(s), du = wfDur(s);
    const left = Math.max(0, (a - t0) / total * 100);
    const w = Math.max(0.4, du / 1000 / total * 100);
    const pct = du / 1000 / total * 100;
    const bad = String(s.status || "ok") !== "ok";
    return `<div class="wf-row">
      <div class="wf-label" style="padding-left:${d * 14}px">
        <span class="wf-name" title="${esc(s.name || "")}">${esc(s.name || "?")}</span>
        ${s.caller ? `<span class="wf-caller">${esc(s.caller)}</span>` : ""}
        <span class="wf-meta">${wfFmt(du)} · ${pct.toFixed(0)}%</span>
      </div>
      <div class="wf-track"><i class="wf-bar d${d}${bad ? " bad" : ""}" style="left:${left.toFixed(2)}%;width:${w.toFixed(2)}%"></i></div>
    </div>`;
  }).join("");
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((f) => `<i>${wfFmt(total * f * 1000)}</i>`).join("");
  return head + `<div class="wf">
    <div class="wf-row wf-head"><div class="wf-label">${esc(uiText("wf_head"))}</div><div class="wf-ticks">${ticks}</div></div>
    ${bars}
  </div>`;
}

function mapHtml(sec, ctx) {
  // 全景图：一列一个环节，节点上带当前在库的数量，列间箭头是数据的去向
  const head = secHead(sec, ctx);
  const nodeOf = (n) => {
    const v = n.value ? fill(n.value, ctx) : "";
    const note = n.note ? fill(n.note, ctx) : "";
    return `<div class="flow-node"><b>${esc(fill(n.label, ctx))}</b>${
      v === "" || v === "undefined" ? "" : `<i class="map-num">${esc(String(v))}</i>`}${
      note ? `<span>${esc(note)}</span>` : ""}</div>`;
  };
  const cols = (sec.cols || []).map((col) => {
    const items = col.from
      ? arr(ref(col.from, ctx)).map((n) => `<div class="flow-node"><b>${esc(n.label || n.id || "")}</b>${
        n.badge === undefined || n.badge === "" ? "" : `<i class="map-num">${esc(String(n.badge))}</i>`}${
        n.sub ? `<span>${esc(String(n.sub))}</span>` : ""}</div>`).join("")
      : (col.nodes || []).map(nodeOf).join("");
    if (!items) return "";
    return `<div class="flow-col">${col.title ? `<div class="flow-col-t">${esc(fill(col.title, ctx))}</div>` : ""}${items}</div>`;
  }).filter(Boolean);
  if (!cols.length) return head + emptyHtml(sec.empty);
  // 图下方一行分布 chips：数量多的分组不铺成节点，免得把图挤成一列长条
  const foot = sec.foot ? `<div class="map-foot"><span class="muted">${esc(fill(sec.foot.label || "", ctx))}</span><div class="chips">${
    arr(ref(sec.foot.from, ctx)).map((n) => `<span class="chip"><span class="chip-name">${esc(n.label || n.id || "")}</span>${
      n.badge === undefined || n.badge === "" ? "" : `<span>${esc(String(n.badge))}</span>`}</span>`).join("")
  }</div></div>` : "";
  return `<div class="flow-grid map-grid"><article class="flow-card">${head}<div class="flow-map">${
    cols.join('<div class="flow-arrow">→</div>')}</div>${foot}</article></div>`;
}

function flowHtml(sec, ctx) {
  const head = secHead(sec, ctx);
  const cards = arr(ref(sec.source, ctx));
  if (!cards.length) return head + emptyHtml(sec.empty);
  const body = cards.map((row) => {
    const states = arr(row.states && row.states.length ? row.states : (row.flow || {}).states);
    if (!states.length) return "";
    const ids = new Set(states.map((s) => s.id).filter(Boolean));
    const indeg = {};
    states.forEach((s) => { if (s.id) indeg[s.id] = 0; });
    states.forEach((s) => arr(s.next).forEach((n) => { if (ids.has(n)) indeg[n] += 1; }));
    const level = new Map();
    const queue = states.filter((s) => s.id && !indeg[s.id]).map((s) => s.id);
    queue.forEach((id) => level.set(id, 0));
    let guard = 0;
    while (queue.length && guard < states.length * 6) {
      const id = queue.shift(); guard += 1;
      const cur = states.find((s) => s.id === id) || {};
      arr(cur.next).forEach((n) => {
        if (!ids.has(n)) return;
        const want = (level.get(id) || 0) + 1;
        if (!level.has(n) || level.get(n) < want) level.set(n, want);
        queue.push(n);
      });
    }
    states.forEach((s, i) => { if (s.id && !level.has(s.id)) level.set(s.id, i); });
    const maxLv = Math.max(0, ...Array.from(level.values()));
    const cols = [];
    for (let l = 0; l <= maxLv; l += 1) cols.push(states.filter((s) => level.get(s.id) === l));
    const node = (s) => `<div class="flow-node${s.terminal ? " term" : ""}" title="${esc(s.desc || "")}">
        <b>${esc(s.cn || s.id || "")}</b><span>${esc(s.id || "")}</span></div>`;
    const map = cols.filter((c) => c.length).map((c) => `<div class="flow-col">${c.map(node).join("")}</div>`).join('<div class="flow-arrow">→</div>');
    return `<article class="flow-card"><header><h4>${esc(row.cn || row.id || "")}</h4>
      <span class="muted">${esc(row.id || "")} · ${esc(uiText("flow_states", states.length))}</span></header>
      <div class="flow-map">${map}</div></article>`;
  }).join("");
  return head + `<div class="flow-grid">${body}</div>`;
}

/* DAG 渲染器：固定框、按层自动布局、支持缩放；回边（环）画虚线并标注条件。
   图上的每个节点就是岗位流程状态机的一个状态，边就是一次允许的迁移——
   顺序条看不出"打回重做"和"分支裁决"，这里一眼能看到。 */
function dagEdgeTo(x) {
  return x && typeof x === "object" ? String(x.to || x.id || "") : String(x || "");
}
function dagNodes(states) {
  const by = new Map();
  arr(states).forEach((s) => { if (s && s.id) by.set(s.id, s); });
  return by;
}
function dagLayout(states) {
  const by = dagNodes(states);
  const ids = [...by.keys()];
  // 先用 DFS 找出成环的边（回到栈上的点）：这些是"回边"，只影响画法，不参与分层
  const state = new Map(), backSet = new Set();
  const dfs = (start) => {
    const stack = [[start, 0]];
    state.set(start, 1);
    while (stack.length) {
      const fr = stack[stack.length - 1];
      const [id, i] = fr;
      const outs = arr((by.get(id) || {}).next).map(dagEdgeTo).filter((t) => by.has(t));
      if (i >= outs.length) { state.set(id, 2); stack.pop(); continue; }
      fr[1] += 1;
      const to = outs[i];
      if (state.get(to) === 1) { backSet.add(id + "|" + to); continue; }
      if (state.get(to) === 2) continue;
      state.set(to, 1);
      stack.push([to, 0]);
    }
  };
  ids.forEach((id) => { if (!state.get(id)) dfs(id); });
  // 分层：只在非回边上做最长路径松弛，几轮就稳定
  const level = new Map(ids.map((id) => [id, 0]));
  for (let it = 0; it < ids.length; it += 1) {
    let moved = false;
    ids.forEach((id) => {
      arr((by.get(id) || {}).next).forEach((n) => {
        const to = dagEdgeTo(n);
        if (!by.has(to) || backSet.has(id + "|" + to)) return;
        const want = (level.get(id) || 0) + 1;
        if (want > (level.get(to) || 0)) { level.set(to, want); moved = true; }
      });
    });
    if (!moved) break;
  }
  const edges = [], back = [];
  ids.forEach((id) => {
    arr((by.get(id) || {}).next).forEach((n) => {
      const to = dagEdgeTo(n);
      if (!by.has(to)) return;
      const e = { from: id, to, when: ((by.get(id) || {})["when"] || {})[to] || "" };
      (backSet.has(id + "|" + to) ? back : edges).push(e);
    });
  });
  const cols = new Map();
  ids.slice().sort((a, b) => (level.get(a) - level.get(b)) || (a < b ? -1 : 1))
    .forEach((id) => {
      const lv = level.get(id) || 0;
      if (!cols.has(lv)) cols.set(lv, []);
      cols.get(lv).push(id);
    });
  const COL_W = 172, ROW_H = 88, NODE_W = 128, NODE_H = 54, PAD = 18;
  const rows = Math.max(1, ...[...cols.values()].map((c) => c.length));
  const maxLv = Math.max(0, ...[...cols.keys()]);
  const pos = new Map();
  [...cols.entries()].forEach(([lv, list]) => list.forEach((id, i) => {
    pos.set(id, { x: PAD + lv * COL_W, y: PAD + i * ROW_H });
  }));
  return { by, pos, edges: edges.concat(back), cols, rows, maxLv,
           width: PAD * 2 + maxLv * COL_W + NODE_W,
           height: PAD * 2 + rows * ROW_H,
           w: NODE_W, h: NODE_H };
}
function dagSvg(L) {
  const path = (e) => {
    const a = L.pos.get(e.from), b = L.pos.get(e.to);
    if (!a || !b) return "";
    const x1 = a.x + L.w, y1 = a.y + L.h / 2;
    const x2 = b.x, y2 = b.y + L.h / 2;
    const isBack = (L.pos.get(e.to) || {}).x <= (L.pos.get(e.from) || {}).x;
    const mx = (x1 + x2) / 2;
    // 回边从上方绕回：控制点都落在两端之间，不会被画到画布外
    const yTop = Math.max(4, Math.min(y1, y2) - 30);
    const fromTop = Math.max(4, y1 - 26), toTop = Math.max(4, y2 - 26);
    const d = isBack
      ? `M${x1},${y1} C${x1 - 26},${fromTop} ${x2 + 26},${toTop} ${x2},${y2}`
      : `M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}`;
    const label = e.when
      ? `<text x="${mx}" y="${(y1 + y2) / 2 - 6}" class="dag-elabel">${esc(e.when)}</text>` : "";
    return `<g class="dag-edge${isBack ? " back" : ""}"><path d="${d}" marker-end="url(#dag-arrow${isBack ? "-back" : ""})"/>${label}</g>`;
  };
  return `<defs>
      <marker id="dag-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="currentColor"/></marker>
      <marker id="dag-arrow-back" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="#e2571e"/></marker>
    </defs>${L.edges.map(path).join("")}`;
}
function dagCard(row, sec, index, ctx) {
  const states = arr(row.states && row.states.length ? row.states : (row.flow || {}).states);
  if (!states.length) return "";
  const L = dagLayout(states);
  const nodes = [...L.pos.entries()].map(([id, p]) => {
    const s = L.by.get(id) || {};
    return `<div class="flow-node${s.terminal ? " term" : ""}" style="left:${p.x}px;top:${p.y}px;width:${L.w}px;height:${L.h}px" title="${esc(s.desc || "")}">
      <b>${esc(s.cn || s.id)}</b><span>${esc(s.id)}</span></div>`;
  }).join("");
  const zoom = `<div class="dag-zoom">
      <button data-clk="dag_zoom" data-dag="out" data-dag-i="${index}" aria-label="缩小">−</button>
      <span class="dag-pct" data-dag-pct="${index}">100%</span>
      <button data-clk="dag_zoom" data-dag="in" data-dag-i="${index}" aria-label="放大">＋</button>
      <button data-clk="dag_zoom" data-dag="fit" data-dag-i="${index}">适应</button>
    </div>`;
  const title = row.cn || row.id || (sec.title ? fill(sec.title, ctx || {}) : "");
  return `<article class="flow-card" data-dag-card="${index}">
    <header><h4>${esc(title)}</h4>
      <span class="muted">${esc(row.id || "")} · ${esc(uiText("flow_states", states.length))} · ${esc(uiText("dag_edges", L.edges.length))}</span>${zoom}</header>
    <div class="dag-viewport"><div class="dag-stage" data-dag-stage="${index}" style="width:${L.width}px;height:${L.height}px">
      <svg class="dag-edges" width="${L.width}" height="${L.height}" viewBox="0 0 ${L.width} ${L.height}">${dagSvg(L)}</svg>
      ${nodes}
    </div></div>
  </article>`;
}
function dagHtml(sec, ctx) {
  const head = secHead(sec, ctx);
  let rows = arr(ref(sec.source, ctx));
  if (!rows.length) return head + emptyHtml(sec.empty);
  // source 直接给"状态列表"时包成一张图：岗位详情就是一整套状态，不该再要求外面套一层
  if (rows.every((r) => r && typeof r === "object" && r.id && "next" in r)) {
    rows = [{ id: "", cn: "", states: rows }];
  }
  const body = rows.map((row, i) => dagCard(row, sec, i, ctx)).join("");
  return head + `<div class="flow-grid">${body}</div>`;
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
  const acts = (sec.actions || []).map((a) => buttonHtml(a, { ...ctx, row: src }, { clk: "card_act" })).join("");
  return `<aside class="side-card">
    ${sec.heading ? `<h3>${esc(fill(sec.heading, ctx))}</h3>` : ""}
    ${rows}
    ${acts ? `<div class="actions" style="margin-top:12px">${acts}</div>` : ""}
  </aside>`;
}

function docHtml(sec, ctx) {
  const raw = String(ref(sec.source, ctx) == null ? "" : ref(sec.source, ctx));
  if (sec.hide_when_empty && !raw.trim()) return "";
  const body = raw.trim() ? renderMarkdown(raw) : esc(sec.fallback || uiText("doc_empty"));
  return `<aside class="side-card">
    ${sec.heading ? `<h3>${esc(fill(sec.heading, ctx))}</h3>` : ""}
    <div class="doc-body">${body}</div>
  </aside>`;
}

function composerHtml(sec, ctx) {
  // 只读是"整块"的：工单结单或所在项目归档，追加备注/结单/语音/发送四个控件一起灰，
  // 不再出现"少一个按钮"或"其中几个还亮着"的半开状态。
  const disabled = sec.disabled_when != null && condOf(sec.disabled_when, ctx);
  const submit = sec.submit || {};
  const submitId = regAct({ act: submit, ctx, composer: true });
  const voice = sec.voice || null;
  const voiceId = voice ? regAct({ act: voice, ctx, composer: true, voice: true }) : "";
  const hint = disabled ? String(fill(sec.disabled_hint || sec.disabled_reason || "", ctx)) : "";
  const gate = disabled ? ` disabled${hint ? ` title="${esc(hint)}"` : ""}` : "";
  const st = disabled ? "disabled" : "idle";
  const acts = (sec.actions || []).map((a) =>
    buttonHtml(a, ctx, { disabled, hint, composer: true, clk: a.clk || "composer_voice" })).join("");
  const busyVal = sec.busy_from ? String(fill(sec.busy_from, ctx) || "") : "";
  const busy = !disabled && busyVal && busyVal === (sec.busy_when || "running");
  const voiceBtn = voice
    ? `<button class="voice" data-clk="composer_voice" data-act="${voiceId}" data-ctl="${esc(ctlOf(voice, "composer_voice"))}" data-ctl-state="${st}"${gate} title="${esc(fill(voice.hint || "", ctx))}">${esc(fill(voice.label || uiText("voice"), ctx))}</button>`
    : "";
  const submitCtl = String(submit.ctl || ctlOf(submit, "composer_send"));
  return `<div class="composer-wrap">
    <div class="composer${disabled ? " off" : ""}">
      <textarea placeholder="${esc(fill(sec.placeholder || "", ctx))}"${gate}></textarea>
      ${acts}
      ${voiceBtn}
      <button class="primary" data-clk="composer_send" data-act="${submitId}" data-ctl="${esc(submitCtl)}" data-ctl-state="${st}"${gate}>${esc(fill(submit.label || uiText("send"), ctx))}</button>
    </div>
    ${hint ? `<div class="composer-hint">${esc(hint)}</div>` : ""}
    ${busy ? `<div class="composer-hint busy">${esc(fill(sec.busy_text || "", ctx))}</div>` : ""}
  </div>`;
}
/* 点击状态机图：规格驱动，7 个状态环形排布，有向边是允许的迁移 */
function clickMachineHtml(sec, ctx) {
  const m = ref(sec.source, ctx) || {};
  const states = arr(m.states);
  let trans = m.transitions || {};
  if (typeof trans !== "object" || Array.isArray(trans)) trans = {};
  if (!states.length) return emptyHtml(sec.empty);
  // 手机竖排：画布按竖比例给，字号才能在 390 宽下保持可读（横版会被等比缩成蚂蚁字）
  const W = 380, H = 364, NW = 88, NH = 40;
  // 边按来源状态着色：20 条边都连到 idle，颜色是分辨"从哪出发"的唯一线索
  const TONE = { idle: "#5f87dd", press: "#3fae68", drag: "#2aa9a4", scroll: "#6f7fd0", swallow: "#98a2b1", busy: "#dd8f3f", modal: "#9a6adb" };
  const notes = m.edge_notes || {};
  // 坐标由规格给（at 为归一化位置）；没给就退回环形，规格漏了也不会白屏
  const pos = {};
  states.forEach((s, i) => {
    if (Array.isArray(s.at) && s.at.length === 2) pos[s.key] = { x: s.at[0] * W, y: s.at[1] * H };
    else {
      const a = -Math.PI / 2 + (i * 2 * Math.PI) / states.length;
      pos[s.key] = { x: W / 2 + 150 * Math.cos(a), y: H / 2 + 150 * Math.sin(a) };
    }
  });
  const edge = (from, to) => {
    const a = pos[from], b = pos[to];
    if (!a || !b) return "";
    const dx = b.x - a.x, dy = b.y - a.y, len = Math.hypot(dx, dy) || 1;
    const ux = dx / len, uy = dy / len;
    // 从矩形边界出发：按方向分量换算到边框上，箭头才不会被节点盖住
    const k = 1 / (Math.abs(ux) / (NW / 2 + 8) + Math.abs(uy) / (NH / 2 + 8));
    const sx = a.x + ux * k, sy = a.y + uy * k, ex = b.x - ux * k, ey = b.y - uy * k;
    const mx = (sx + ex) / 2, my = (sy + ey) / 2;
    // 互为反向的两条边各自外偏，避免重叠成一条；单向边也带一点弧度更好认
    const both = !!(trans[to] || []).includes(from);
    const bend = (both ? (String(from) < String(to) ? 1 : -1) * 16 : 8);
    const qx = mx - uy * bend, qy = my + ux * bend;
    const tone = TONE[from] || "#a9b6c6";
    const label = notes[from + ">" + to];
    // 标签再往外让 9px，不然会压在弧线或节点边上
    const lx = Math.min(Math.max(mx - uy * (bend + 9), 26), W - 26);
    const ly = Math.min(Math.max(my + ux * (bend + 9), 18), H - 12);
    const tag = label ? `<text class="mch-edge-label" x="${lx.toFixed(1)}" y="${ly.toFixed(1)}" text-anchor="middle">${esc(label)}</text>` : "";
    return `<path class="mch-edge" style="stroke:${tone}" d="M${sx.toFixed(1)},${sy.toFixed(1)} Q${qx.toFixed(1)},${qy.toFixed(1)} ${ex.toFixed(1)},${ey.toFixed(1)}" marker-end="url(#mch-arrow-${from})"/>${tag}`;
  };
  const edges = Object.keys(trans).map((from) => arr(trans[from]).map((to) => edge(from, to)).join("")).join("");
  const nodes = states.map((s) => {
    const p = pos[s.key];
    return `<g class="mch-node" data-state="${esc(s.key)}" transform="translate(${p.x.toFixed(1)},${p.y.toFixed(1)})">
      <rect x="${-NW / 2}" y="${-NH / 2}" width="${NW}" height="${NH}" rx="11"/>
      <text class="mch-cn" y="-3" text-anchor="middle">${esc(s.label || s.key)}</text>
      <text class="mch-key" y="13" text-anchor="middle">${esc(s.key)}</text></g>`;
  }).join("");
  return `<div class="machine-wrap">
    <svg class="mch-svg" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(uiText("machine_svg_alt"))}">
      <defs>${states.map((s) => `<marker id="mch-arrow-${esc(s.key)}" viewBox="0 0 10 10" refX="8" refY="5"
        markerWidth="6" markerHeight="6" orient="auto-start-reverse">
        <path d="M0,0 L10,5 L0,10 z" fill="${TONE[s.key] || "#a9b6c6"}"/></marker>`).join("")}</defs>
      ${edges}${nodes}
    </svg>
  </div>`;
}

/* 可点位置清单：一行一类，允许态 → 进入 → 回落；比多列表格省一半高度 */
function clickKindsHtml(sec, ctx) {
  const rows = arr(ref(sec.source, ctx));
  if (!rows.length) return emptyHtml(sec.empty);
  const chip = (v) => `<span class="chip">${esc(v)}</span>`;
  return `<div class="kind-list">${rows.map((r) =>
    `<div class="kind-row">
      <div class="kind-top"><b>${esc(r.label || r.key)}</b><em>${esc(r.key)}</em>
        <span class="kind-flow">${arr(r.allow).map(chip).join("")}${
          r.enter ? `<i>→</i>${chip(r.enter)}` : ""}${r.exit ? `<i>→</i>${chip(r.exit)}` : ""}</span>
      </div>
      ${r.note ? `<p>${esc(r.note)}</p>` : ""}
    </div>`).join("")}</div>`;
}

function sectionHtml(sec, ctx, idx) {
  const kind = sec.kind;
  // data-as：这一块吃哪份数据（规格里声明的）；失效来了只换它吃的那几块
  const marks = (idx == null ? "" : ` data-sec="${idx}"`) + (sec.as ? ` data-as="${esc(sec.as)}"` : "");
  let html = "";
  if (kind === "cards") html = secHead(sec, ctx) + cardsHtml(sec, ctx);
  else if (kind === "stats") html = statsHtml(sec, ctx);
  else if (kind === "flow") html = flowHtml(sec, ctx);
  else if (kind === "dag") html = dagHtml(sec, ctx);
  else if (kind === "machine") html = secHead(sec, ctx) + clickMachineHtml(sec, ctx);
  else if (kind === "kinds") html = secHead(sec, ctx) + clickKindsHtml(sec, ctx);
  else if (kind === "map") html = mapHtml(sec, ctx);
  else if (kind === "waterfall") html = waterfallHtml(sec, ctx);
  else if (kind === "table") html = tableHtml(sec, ctx);
  else if (kind === "chat") html = chatHtml(sec, ctx);
  else if (kind === "kv") html = kvHtml(sec, ctx);
  else if (kind === "tree") html = secHead(sec, ctx) + treeHtml(sec, ctx);
  else if (kind === "doc") html = docHtml(sec, ctx);
  else if (kind === "composer") html = composerHtml(sec, ctx);
  else html = emptyHtml({ text: uiText("unknown_kind", kind) });
  if (sec.fold) {
    const title = fill((sec.fold || {}).title || sec.heading || "", ctx);
    return `<div class="vsec${sec.list ? " vsec-list" : ""} vsec-fold" data-kind="${esc(kind)}"${marks}><details><summary data-clk="section_fold" data-ctl="ctl.section_fold" data-ctl-state="idle"><strong>${esc(title)}</strong>${
      sec.note ? `<span class="muted">${esc(fill(sec.note, ctx))}</span>` : ""}</summary>${html}</details></div>`;
  }
  return `<div class="vsec${sec.list ? " vsec-list" : ""}" data-kind="${esc(kind)}"${marks}>${html}</div>`;
}

function pruneEmptyCards() {
  // hide_when_empty 之类会留下空壳，空壳在手机卡片轨里就是一张白卡，直接剔掉
  document.querySelectorAll("#view-body .view-scroll .vsec").forEach((s) => {
    if (!s.textContent.trim() && !s.querySelector("table,img,canvas,svg,input,textarea")) s.remove();
  });
}

function expandFolds() {
  // 手机上一页到底：折叠块直接摊开，标题与说明都看得见
  const rail = document.querySelector("#view-body .view-scroll");
  if (!rail) return;
  // 群聊页把双栏合成一张卡，里面的 chat/composer 不是独立页，不参与翻页计数
  const cards = [...rail.querySelectorAll(".vsec")].filter((s) => {
    const grid = s.closest(".ticket-grid");
    return !grid || getComputedStyle(grid).display === "contents";
  });
  if (!cards.length) return;
  // 手机上是纵向卡片堆叠：折叠块默认摊开，免得只看到一行标题不知道这页是什么
  if (getComputedStyle(rail).flexDirection === "column") {
    // 只摊开区块级的折叠（整块内容），组/条目级保持可点，否则一棵树会展开成几万像素
    cards.forEach((c) => c.querySelectorAll(":scope > details, :scope > .orphans > details")
      .forEach((d) => { d.open = true; }));
  }
}

function headHtml(spec, ctx) {
  // 页头徽章：已归档/只读这类"整页的态"必须写在标题旁，而不是藏在某个区块里
  const badges = (spec.badges || []).filter((b) => b && condOf(b.when, ctx))
    .map((b) => `<span class="badge ${esc(b.tone || "archived")}">${esc(fill(b.text || "", ctx))}</span>`).join("");
  return `<div class="view-head">
      <div style="min-width:0"><h2>${esc(fill(spec.heading || spec.heading_from || "", ctx))}${badges}</h2>
      <div class="desc">${esc(fill(spec.subheading || "", ctx))}</div></div>
      <div class="spacer"></div>
      <div class="actions">${(spec.actions || []).map((a) => buttonHtml(a, ctx, { clk: "head_act" })).join("")}</div>
    </div>`;
}

function renderView(spec, ctx) {
  ACTS = new Map();   // 每页一份绑定表：旧页面的表由保活实例自己留着
  const head = headHtml(spec, ctx);
  const left = [], right = [], single = [];
  (spec.sections || []).forEach((sec, i) => {
    const html = sectionHtml(sec, ctx, i);
    if (sec.lane === "left") left.push(html);
    else if (sec.lane === "right") right.push(html);
    else single.push(html);
  })
  let body = single.join("");
  if (left.length || right.length) {
    // 单侧有内容就占满整行：空的那一列不占位，避免留下大片空白
    const twoSided = left.length && right.length;
    body = `<div class="ticket-grid${twoSided ? "" : " solo"}">
      <div class="lane lane-left">${left.join("")}</div>
      ${twoSided ? `<div class="lane lane-right">${right.join("")}</div>` : ""}
    </div>`;
  }
  // 内容区单独包一层：桌面纵向排布，手机变成横滑吸附的卡片轨
  $("view-body").innerHTML = head + `<div class="view-scroll">${body}</div>`;
  pruneEmptyCards();
  expandFolds();
  if (typeof mountDecks === "function") mountDecks();
  // 浏览器标题也由外壳词表拼：视图名走规格，品牌名走后端
  const name = String(fill(spec.heading || spec.heading_from || "", ctx) || "").trim();
  if (BRAND.title_view && name) {
    const parts = [name, BRAND.name || ""];
    let idx = 0;
    document.title = String(BRAND.title_view).replace(/\{\}/g, () => (idx++ === 0 ? parts[0] : parts[1]));
  }
  else if (BRAND.title) document.title = BRAND.title;
}
