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
/* 折叠唯一出口：section / 元素页 / 树分组 / 工具卡全部走这里一套 summary 视觉与持久化。
   key 用 foldAttr 生成；未记录过状态的键由 expandFolds 在移动端默认摊开，已记录的不覆盖。 */
function foldBox(key, title, note, body, cls) {
  const clsAttr = cls ? ` ${cls}` : "";
  const noteHtml = note ? `<span class="muted">${esc(note)}</span>` : "";
  return `<details class="fold-box${clsAttr}"${foldAttr(key)}>
    <summary data-clk="section_fold" data-ctl="ctl.section_fold" data-ctl-state="idle"><strong>${esc(title)}</strong>${noteHtml}</summary>
    ${body}
  </details>`;
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
  // 危险动作沿用旧版描边样式：default 变体 + danger 类，不走实心 danger 底
  const variant = act.tone === "primary" ? "primary" : "default";
  const cls = act.tone === "primary" ? "primary" : (act.tone === "danger" ? "danger" : "");
  // data-ctl 是这个按钮自己的状态机名：门禁脚本按它比对规格，浏览器按它读状态
  const st = disabled ? "disabled" : "idle";
  return `<sl-button variant="${variant}" size="small" class="${cls}" data-clk="${esc(kind)}" data-act="${id}" data-ctl="${esc(ctl)}" data-ctl-state="${st}" ${disabled ? "disabled" : ""}${title}>${esc(fill(act.label, ctx))}</sl-button>`;
}
function badgeTone(tone) {
  if (tone === "success" || tone === "ok") return "success";
  if (tone === "primary" || tone === "busy" || tone === "open") return "primary";
  if (tone === "danger" || tone === "offline" || tone === "closed") return "danger";
  if (tone === "warning" || tone === "warn" || tone === "archived") return "warning";
  return "neutral";
}
function badgeHtml(value, ctx) {
  const s = String(value == null ? "" : value);
  const kind = statusKind(s);
  const variant = kind === "offline" ? "success" : (kind === "busy" ? "primary" : "neutral");
  const cls = kind === "offline" ? "closed" : (kind === "busy" ? "open" : "");
  return `<sl-badge variant="${variant}" class="badge ${cls}">${esc(s || uiText("badge_offline"))}</sl-badge>`;
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
  // items 是规格里的字面行（支持 {} 占位）；否则按 source 从取数结果取行
  const rows = Array.isArray(sec.items) ? sec.items : arr(ref(sec.source, ctx));
  if (!rows.length) return sec.hide_when_empty ? "" : emptyHtml(sec.empty);
  // layout: deck = 卡片堆叠：收缩时叠在一起、左右滑动换牌，点「展开」铺成列表；
  // grid = 项目卡片网格；list = 群聊式行列表；无 layout 保持既有普通卡片清单。
  const layout = sec.layout || "";
  const deck = layout === "deck";
  let sorted = rows.slice();
  if (sec.sort) {
    const by = sec.sort.by, dir = sec.sort.order === "asc" ? 1 : -1;
    sorted.sort((a, b) => dir * String(dig(a, by) || "").localeCompare(String(dig(b, by) || "")));
  }
  const cards = sorted.map((row, idx) => {
    const c = { ...ctx, row };
    const archived = sec.archived_when != null && condOf(sec.archived_when, c);
    const acts = (sec.actions || []).map((a) => buttonHtml(a, c, { clk: "card_act" })).join("");
    const badge = (sec.badge && condOf(sec.badge.when, c))
      ? `<sl-badge variant="warning" class="badge archived">${esc(fill(sec.badge.text, c))}</sl-badge>` : "";
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
    // 标题/副文案：区块级模板优先，缺省回落行上的 title/sub
    const titleText = fill(sec.title != null ? sec.title : dig(row, "title"), c);
    const subText = fill(sec.sub != null ? sec.sub : dig(row, "sub"), c);
    const sub = subText ? `<div class="csub">${esc(subText)}</div>` : "";
    // 头像字：标题填充后的第一个字符，英文转大写
    const firstChar = [...String(titleText || "")][0] || "";
    const pavChar = /[a-zA-Z]/.test(firstChar) ? firstChar.toUpperCase() : firstChar;
    const pav = (layout === "grid" || layout === "list") && pavChar
      ? `<span class="pav" aria-hidden="true">${esc(pavChar)}</span>` : "";
    const cardCls = deck ? "pcard" : (layout ? `pcard ${layout}` : "pcard");
    return `<article class="${cardCls}${archived ? " archived" : ""}" data-clk="card_open" ${click ? `data-go="${click}"` : ""}${deck ? ` data-deck-i="${idx}"` : ""} role="button" tabindex="0" aria-label="${esc(uiText("card_open", titleText))}">
      ${pav}
      <div class="phead">
        <h3 class="pname">${esc(titleText)}</h3>
        ${badge}
        <div class="acts">${acts}</div>
      </div>
      ${stat}
      ${sub}
      <div class="meta">${meta}</div>
      ${chips}
      <span class="ar">›</span>
    </article>`;
  }).join("");
  // 只有一张牌时堆叠没有意义（还会多出一次"滑不动"的手势），退回普通列表
  if (!deck || sorted.length < 2) {
    const wrapCls = deck ? "cards" : (layout ? `cards ${layout}` : "cards");
    return `<div class="${wrapCls}">${cards}</div>`;
  }
  return `<div class="cards deck" data-deck="1" data-open="0" data-pos="0">
    <div class="deck-bar">
      <span class="deck-pos">${esc(uiText("deck_pos", 1, sorted.length))}</span>
      <sl-button class="deck-more" variant="default" size="small" data-clk="deck_toggle" data-deck-open="1">${esc(uiText("deck_expand", sorted.length))}</sl-button>
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
      `<sl-button variant="${f.key === (sec._active || filters[0].key) ? "primary" : "default"}" size="small" data-clk="filter" data-filter="${esc(f.key)}" class="${f.key === (sec._active || filters[0].key) ? "on" : ""}">${esc(f.label)}</sl-button>`).join("")}</span>` : ""}
  </div>`;
  const cols = sec.columns || [];
  const rowActs = sec.actions || [];
  const body = rows.length ? rows.map((row) => {
    const c = { ...ctx, row };
    const cells = cols.map((col) => {
      let val;
      if (col.badge) {
        // badge 可为静态值，也可为 {when, text, off}：条件成立显 text，否则显 off。
        const specBadge = col.badge;
        if (specBadge && typeof specBadge === "object") {
          const on = condOf(specBadge.when, c);
          val = badgeHtml(fill(on ? specBadge.text : (specBadge.off || ""), c), c);
        } else val = badgeHtml(fill(col.badge, c), c);
      } else {
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
  // 真人发言（session-send 打 human 标）：显示"用户"，不借会话主人的名字
  if (msg.kind === "human") return roleLabel("user");
  const actor = msg.actor || msg.role || "assistant";
  if (actor === "tool") return msg.name ? (roleLabel("tool") + " · " + msg.name) : roleLabel("tool");
  const hit = (roles || []).find((r) => r.role === actor || r.session === actor);
  if (hit && (hit.display || hit.role)) return hit.display || hit.role;
  return roleLabel(actor);
}
function bubbleClass(msg) {
  if (msg.kind === "note") return "system";
  // 真人从控制台发的消息（session-send 落盘时打 human 标）在右侧；
  // 会话装配注入的提示 kind=note，不受影响，仍走系统条
  if (msg.kind === "human") return "user";
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
/* 气泡内的小时间（HH:MM），完整年月日放 title 悬停看 */
function timeText(at) {
  const t = atSeconds(at);
  if (!isFinite(t) || t < 0) return "";
  return new Date(t * 1000).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
}
/* 日期分隔签：跨天了先插一条居中日期，格式化口径与 clockText 一致 */
function dayKeyOf(at) {
  const t = atSeconds(at);
  return isFinite(t) && t > 0 ? new Date(t * 1000).toDateString() : "";
}
function dayLabelOf(at) {
  const t = atSeconds(at);
  if (!isFinite(t) || t < 0) return "";
  const d = new Date(t * 1000);
  const now = new Date();
  const day = 86400000;
  const startOfDay = (x) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const diff = Math.round((startOfDay(now) - startOfDay(d)) / day);
  const md = d.toLocaleDateString("zh-CN", { month: "numeric", day: "numeric" });
  if (diff === 0) return md + " 今天";
  if (diff === 1) return md + " 昨天";
  const y = d.getFullYear() === now.getFullYear() ? "" : d.getFullYear() + "年";
  return y + md;
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
  // 接收人：事件带 to 就标「发给 <to>」；旧数据没有 to 才退回全员口径。文案读词表，不写中文常量。
  const toLabel = first.to
    ? uiText("ev_to", first.to)
    : uiText("ev_to_all");
  const toHtml = toLabel ? `<span class="ev-to">${esc(toLabel)}</span>` : "";
  const text = eventText(g);
  const long = text.length > 60;
  const shown = long ? text.slice(0, 58) + "…" : text;
  const fold = long ? ` data-clk="fold_text" data-expand data-full="${esc(text)}" data-short="${esc(shown)}"` : "";
  return `<div class="msg event"><div class="sys-body${long ? " clamp" : ""}"${fold}><span class="ev-line"><span class="ev-label">${esc(label + cnt)}</span>${toHtml}${shown ? `<span class="ev-text">${esc(shown)}</span>` : ""}</span><span class="ev-ts">${esc(when(first.at))}</span></div></div>`;
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
      return g.items.map((it) => {
        const m = it.m || {};
        const toLabel = m.to ? uiText("ev_to", m.to) : uiText("ev_to_all");
        const toHtml = toLabel ? `<span class="ev-to">${esc(toLabel)}</span>` : "";
        return `<div class="msg system"><div class="sys-body md">${toHtml}${renderMarkdown(m.content == null ? "" : m.content)}</div></div>`;
      }).join("");
    }
    const side = g.cls === "user" ? "right" : "left";
    const bodies = groupBody(g);
    if (!bodies) return "";
    const av = `<div class="avatar" style="--av:${avatarColor(g.who)}">${initial(g.who)}</div>`;
    // 时间在消息之上：先看清"谁、什么时候发的"，再读内容；悬停给完整年月日
    const lastAt = (g.items[g.items.length - 1] || {}).at;
    const tm = timeText(lastAt);
    const full = clockText(lastAt);
    const ts = tm ? `<span class="msg-time"${full ? ` title="${esc(full)}"` : ""}>${esc(tm)}</span>` : "";
    // 自己的消息不显示名字（TG 口径）；成员消息名字用该角色专属色
    const name = side === "left"
      ? `<div class="msg-name" style="color:${avatarColor(g.who)}">${esc(g.who)}</div>` : "";
    // 左右两列：左列给用户的文字气泡，右列同一轮原始报文（默认折叠，展开走 message-wire 回读）
    const wire = wireHtml(g.items, wireDemand, wireChars);
    const raw = rawHtml(g.items.map((it) => it.owner || it.m).filter(Boolean), uiText("raw_title"), rawChars);
    return `<div class="msg ${side}">${side === "left" ? av : ""}
      <div class="msg-main"><div class="msg-head">${name}${ts}</div>
      <div class="wire-pair">
        <div class="wire-side wire-side-body">${bodies}</div>
        <div class="wire-side wire-side-raw">${wire}${raw}</div>
      </div></div>${side === "right" ? av : ""}</div>`;
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
  let lastDay = "";
  const daySep = (at) => {
    const day = dayKeyOf(at);
    if (!day || day === lastDay) return false;
    return day;
  };
  const flush = () => {
    if (buf.length) { out.push(renderBubbles(buf, roles, wireDemand, wireChars, rawChars)); buf = []; }
  };
  for (const s of stream) {
    const at = s.kind === "m" ? s.m.at : s.e.at;
    const day = daySep(at);
    if (day !== false) { flush(); out.push(`<div class="chat-day"><span>${esc(dayLabelOf(at))}</span></div>`); lastDay = day; }
    if (s.kind === "m") { buf.push(s.m); continue; }
    flush();
    out.push(eventGroupHtml(s.e));
  }
  flush();
  return out.join("");
}

/* 角色状态条：每个角色当前阶段与活跃状态，点开是同一个人（data-member 复用成员卡） */
function roleBoardHtml(roles, label) {
  const rows = arr(roles).filter((r) => r && ((r.machine || {}).states || []).length);
  if (!rows.length) return "";
  const cells = rows.map((r) => {
    const mc = r.machine || {};
    const states = mc.states || [];
    const cur = states.find((s) => s.id === mc.stage) || {};
    const acts = (mc.active || []).filter((id) => id !== mc.stage)
      .map((id) => (states.find((s) => s.id === id) || {}).cn || id);
    const idx = arr(roles).indexOf(r);
    return `<sl-button class="role-mini st-${statusKind(r.status)}" variant="default" size="small" data-clk="member_chip" data-member="${idx}" title="${esc((mc.flow || {}).cn || "")}">
      <i class="rm-dot"></i><b>${esc(r.display || r.role)}</b>
      <span class="rm-stage">${esc(cur.cn || "—")}</span>
      ${acts.length ? `<span class="rm-active">${esc(acts.join("/"))}</span>` : ""}
    </sl-button>`;
  }).join("");
  // 标题由 YAML roles_label 传入；缺词表条目时退回 roles_label 词表键，前端不写中文常量
  const title = label || uiText("roles_label");
  return `<div class="role-board"><span class="board-lab">${esc(title)}</span>${cells}</div>`;
}
/* 待办板：模型自己排的分步计划，和岗位流程状态机不是一回事，单独一条 */
function todoBoardHtml(todos, label) {
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
  // 主体标题由 YAML todos_label 传入；待办 id（T1/T2/T3）只是行内标识，不裸露成无主体状态机
  const prefix = label || uiText("todos_label");
  const head = (prefix ? `${esc(prefix)} ` : "") + esc(uiText("todo_title", done, list.length)) +
    (doing ? esc(uiText("todo_doing", doing.text || "")) : "");
  return `<details class="todo-board"><summary data-clk="summary_fold">${head}</summary><div class="td-list">${rows}</div></details>`;
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
  return `<details class="raw-box wire-box"${foldAttr(foldKey)} data-clk="wire_fold" data-demand="${esc(demand)}" data-chars="${esc(String(chars || 0))}" data-session="${esc(m.session || "")}" data-seq="${esc(String(w.seq == null ? -1 : w.seq))}"><summary data-clk="wire_fold" title="${esc(uiText("wire_note"))}">${esc(uiText("wire_title"))} · ${esc(w.model || "")} · HTTP ${esc(String(w.status == null ? "—" : w.status))} · ${esc(uiText("wire_req"))} ${esc(size(w.req_len))} / ${esc(uiText("wire_resp"))} ${esc(size(w.res_len))}</summary>
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
  return `<details class="raw-box"${foldAttr(foldKey)} data-clk="raw_fold"><summary data-clk="raw_fold" title="${esc(uiText("raw_note"))}">${esc(label)}</summary><pre>${esc(cut)}</pre></details>`;
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
  const chips = arr(roles).map((r, i) => `<sl-button class="av-chip st-${statusKind(r.status)}" variant="default" size="small" data-clk="member_chip" data-member="${i}"
      style="--av:${avatarColor(r.display || r.role)}" title="${esc(r.display || r.role)} · ${statusText(r.status)}">${initial(r.display || r.role)}<i class="dot"></i></sl-button>`).join("");
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
    ? `<div class="inject"><div class="inject-note">${esc(uiText("inject_note"))}</div>${rawHtml(hiddenMsgs, uiText("inject_title", hiddenMsgs.length))}</div>` : "";
  // chat 头部右侧动作区：结单等动作由 YAML actions 传入，disabled_when 由 buttonHtml 统一判灰态
  const headActions = arr(sec.actions || [])
    .map((a) => buttonHtml(a, ctx, { clk: a.clk || "card_act" })).join("");
  const body = inject + todoBoardHtml(src.todos, sec.todos_label) +
    (stream || `<div class="chat-empty">${esc(fill(sec.empty || "", ctx))}</div>`) + draftHtml;
  return `<section class="chat-card card">
    ${headMain || chips || headActions ? `<div class="chat-head">${headMain}<div class="members">${chips}</div><div class="chat-head-actions">${headActions}</div></div>` : ""}
    ${summaryHtml}
    ${roleBoardHtml(roles, sec.roles_label)}
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
    // 空层不装成可折叠的样子：不给假三角不给计数，但外观与折叠条同款一张卡——
    // 同一枚徽章、同一行高、同一个壳，视觉上是同一棵树里的同级条目
    const badge = (node.badge && node.badge !== node.label) ? `<sl-badge variant="neutral" class="badge">${esc(node.badge)}</sl-badge>` : "";
    return `<div class="tree-node tree-node-blank">${badge}<span class="tree-node-label">${esc(node.label || "")}</span><span class="muted tree-node-empty">${esc(uiText("tree_empty_layer") || uiText("empty_tree"))}</span></div>`;
  }
  // 折叠是用户意图：键挂内容身份，重渲染/刷新按原状恢复；没动过按声明默认展开
  const stored = FOLDS.get(here);
  const openAttr = (stored === undefined ? !sec.collapsed : !!stored) ? " open" : "";
  return `<details class="tree-node"${foldAttr(here)}${openAttr}>
    <summary data-clk="tree_group">${node.badge && node.badge !== node.label ? `<sl-badge variant="neutral" class="badge">${esc(node.badge)}</sl-badge>` : ""}<span class="tree-node-label">${esc(node.label || "")}</span>${sub}${sec.hide_count ? "" : `<span class="muted tree-node-count">${count}</span>`}</summary>
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

/* 状态机/流程图：唯一出口 HiveGraph（离线 cytoscape + dagre 布局）。
   节点是岗位/流程状态，边是允许的迁移；回边（环）虚线橙色，边上文字是迁移条件。 */
function dagEdgeTo(x) {
  return x && typeof x === "object" ? String(x.to || x.id || "") : String(x || "");
}
/* DFS 找出成环的回边（回到栈上的点）：这些边只影响画法，不参与 dagre 分层。 */
function dagBackSet(states) {
  const by = new Map();
  arr(states).forEach((s) => { if (s && s.id) by.set(s.id, s); });
  const state = new Map(), back = new Set();
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
      if (state.get(to) === 1) { back.add(id + "|" + to); continue; }
      if (state.get(to) === 2) continue;
      state.set(to, 1);
      stack.push([to, 0]);
    }
  };
  [...by.keys()].forEach((id) => { if (!state.get(id)) dfs(id); });
  return back;
}
function dagGraphSpec(row) {
  const states = arr(row.states && row.states.length ? row.states : (row.flow || {}).states);
  if (!states.length) return null;
  const by = new Map();
  states.forEach((s) => { if (s && s.id) by.set(s.id, s); });
  const back = dagBackSet(states);
  const active = new Set(arr(row.active));
  const nodes = states.map((s) => {
    const g = s.gate || {};
    const nm = arr(g.must).length, nf = arr(g.forbid).length;
    const parts = [];
    if (active.has(s.id)) parts.push(uiText("dag_current"));
    if (nm) parts.push(uiText("dag_must", nm));
    if (nf) parts.push(uiText("dag_forbid", nf));
    return { id: s.id, label: s.cn || s.id, sub: s.id, badge: parts.join(" · "),
             terminal: !!s.terminal, active: active.has(s.id) };
  });
  const edges = [];
  states.forEach((s) => {
    arr(s.next).forEach((n) => {
      const to = dagEdgeTo(n);
      if (!by.has(to)) return;
      const when = ((s.when || {})[to]) || "";
      const isBack = back.has(s.id + "|" + to);
      edges.push({ from: s.id, to, back: isBack,
                   label: isBack ? (uiText("dag_back") + "：" + when) : when });
    });
  });
  return { nodes, edges, direction: "LR" };
}
function dagCard(row, sec, index, ctx) {
  const spec = dagGraphSpec(row);
  if (!spec) return "";
  const backCount = spec.edges.filter((e) => e.back).length;
  const zoom = `<div class="graph-zoom">
      <sl-button size="small" data-clk="dag_zoom" data-dag="out" data-graph="out" aria-label="−">−</sl-button>
      <sl-button size="small" data-clk="dag_zoom" data-dag="in" data-graph="in" aria-label="＋">＋</sl-button>
      <sl-button size="small" data-clk="dag_zoom" data-dag="fit" data-graph="fit">${esc(uiText("dag_fit"))}</sl-button>
      <span class="dag-pct" data-graph-pct="${index}">100%</span>
    </div>`;
  const title = row.cn || row.id || (sec.title ? fill(sec.title, ctx || {}) : "");
  return `<article class="flow-card" data-graph-card="${index}">
    <header><h4>${esc(title)}</h4>
      <span class="muted">${esc(row.id || "")} · ${esc(uiText("flow_states", spec.nodes.length))} · ${esc(uiText("dag_edges", spec.edges.length))}</span>${zoom}</header>
    <div class="graph-wrap dag-stage" data-graph="1" data-graph-nodes="${spec.nodes.length}" data-graph-edges="${spec.edges.length}" data-graph-back="${backCount}" data-spec="${esc(JSON.stringify(spec))}"><div class="graph-canvas"></div></div>
    <div class="dag-legend">${esc(uiText("dag_legend"))}</div>
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

function gateHtml(sec, ctx) {
  const rows = arr(ref(sec.source, ctx));
  if (!rows.length) return emptyHtml(sec.empty);
  const blocks = rows.map((s) => {
    const g = (s && s.gate) || {}, must = arr(g.must), forbid = arr(g.forbid);
    if (!must.length && !forbid.length) return "";
    const mk = must.map((it) => `<li><code>${esc(it.id || "")}</code>${esc(it.text || "")}</li>`).join("");
    const fk = forbid.map((x) => `<li>${esc(typeof x === "string" ? x : (x.text || ""))}</li>`).join("");
    return `<article class="gate-card">
      <header><b>${esc(s.cn || s.id)}</b><span>${esc(s.id)}</span></header>
      ${mk ? `<h5>${esc(uiText("gate_must_head"))}</h5><ul class="gate-must">${mk}</ul>` : ""}
      ${fk ? `<h5>${esc(uiText("gate_forbid_head"))}</h5><ul class="gate-forbid">${fk}</ul>` : ""}</article>`;
  }).filter(Boolean).join("");
  return blocks || emptyHtml(sec.empty);
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
    ? `<sl-button class="voice" variant="text" size="small" data-clk="composer_voice" data-act="${voiceId}" data-ctl="${esc(ctlOf(voice, "composer_voice"))}" data-ctl-state="${st}"${gate} title="${esc(fill(voice.hint || "", ctx))}">${esc(fill(voice.label || uiText("voice"), ctx))}</sl-button>`
    : "";
  const submitCtl = String(submit.ctl || ctlOf(submit, "composer_send"));
  return `<div class="composer-wrap">
    <div class="composer${disabled ? " off" : ""}">
      <textarea placeholder="${esc(fill(sec.placeholder || "", ctx))}"${gate}></textarea>
      <div class="composer-actions">${acts}${voiceBtn}
        <sl-button class="primary" variant="primary" size="small" data-clk="composer_send" data-act="${submitId}" data-ctl="${esc(submitCtl)}" data-ctl-state="${st}"${gate}>${esc(fill(submit.label || uiText("send"), ctx))}</sl-button>
      </div>
    </div>
    ${hint ? `<div class="composer-hint">${esc(hint)}</div>` : ""}
    ${busy ? `<div class="composer-hint busy">${esc(fill(sec.busy_text || "", ctx))}</div>` : ""}
  </div>`;
}
/* 交互状态迁移图：规格驱动，节点是界面状态，有向边是允许的迁移；布局走 HiveGraph/dagre。 */
function clickMachineHtml(sec, ctx) {
  const m = ref(sec.source, ctx) || {};
  const states = arr(m.states);
  let trans = m.transitions || {};
  if (typeof trans !== "object" || Array.isArray(trans)) trans = {};
  if (!states.length) return emptyHtml(sec.empty);
  const notes = m.edge_notes || {};
  const nodes = states.map((s) => ({
    id: s.key, label: s.label || s.key, sub: s.key, tone: s.key,
  }));
  const edges = [];
  Object.keys(trans).forEach((from) => arr(trans[from]).forEach((to) => {
    edges.push({ from, to, label: notes[from + ">" + to] || "", back: false });
  }));
  const spec = { nodes, edges, direction: "TB" };
  const backCount = edges.filter((e) => e.back).length;
  const zoom = `<div class="graph-zoom">
      <sl-button size="small" data-clk="dag_zoom" data-dag="out" data-graph="out" aria-label="−">−</sl-button>
      <sl-button size="small" data-clk="dag_zoom" data-dag="in" data-graph="in" aria-label="＋">＋</sl-button>
      <sl-button size="small" data-clk="dag_zoom" data-dag="fit" data-graph="fit">${esc(uiText("dag_fit"))}</sl-button>
      <span class="dag-pct" data-graph-pct>100%</span>
    </div>`;
  return `<div class="machine-wrap flow-card">
    <header class="machine-head">${zoom}</header>
    <div class="graph-wrap dag-stage" data-graph="1" data-graph-nodes="${nodes.length}" data-graph-edges="${edges.length}" data-graph-back="${backCount}" data-spec="${esc(JSON.stringify(spec))}"><div class="graph-canvas"></div></div>
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

/* 用户视角：页面地图 = 一页一行，"从哪进 / 点哪里走 / 这页只做一件事" */
function userPagesHtml(sec, ctx) {
  const m = ((ctx || {}).data || {}).machine || {};
  // pages/routes 挂在 screen_machine 下：由页面与控件推导，不手维护
  const pages = arr((m.screen_machine || {}).pages);
  if (!pages.length) return emptyHtml(sec.empty);
  const chip = (x) => `<span class="pmp-chip"><i>${esc(x.by)}</i>${esc(x.label)}</span>`;
  return `<div class="pmap">${pages.map((p) => {
    const inChips = (p.from || []).length ? p.from.map(chip).join("") : `<span class="pmp-none">${esc(uiText("pmap_none"))}</span>`;
    const outChips = (p.to || []).length ? p.to.map(chip).join("") : `<span class="pmp-none">${esc(uiText("pmap_end"))}</span>`;
    return `<div class="pmap-row${p.entry ? " is-entry" : ""}">
      <div class="pmap-top"><b>${esc(p.label)}</b>${p.entry ? `<span class="pmp-pin">${esc(uiText("pmap_entry"))}</span>` : ""}</div>
      ${p.main ? `<div class="pmap-main">${esc(p.main)}</div>` : ""}
      <div class="pmap-flow"><span class="pmp-lab">${esc(uiText("pmap_in"))}</span>${inChips}<span class="pmp-arrow">→</span><span class="pmp-lab">${esc(uiText("pmap_out"))}</span>${outChips}</div>
    </div>`;
  }).join("")}</div>`;
}

/* 页面之间的跳转：一行一条"从这页点这个到那页" */
function userRoutesHtml(sec, ctx) {
  const m = ((ctx || {}).data || {}).machine || {};
  const rows = arr((m.screen_machine || {}).routes);
  if (!rows.length) return emptyHtml(sec.empty);
  return `<div class="route-list">${rows.map((r) =>
    `<div class="route-row"><span class="rt-from">${esc(r.from)}</span><span class="rt-arrow">→</span><span class="rt-by">点「${esc(r.by)}」</span><span class="rt-arrow">→</span><span class="rt-to">${esc(r.to)}</span></div>`).join("")}</div>`;
}

/* 一页里的元素：按页面折叠，每个元素写清"是什么、点下去发生什么、什么时候点不动" */
function userElemsHtml(sec, ctx) {
  const m = ((ctx || {}).data || {}).machine || {};
  const inv = (m.inventory || {}).rows || [];
  const labels = {};
  arr((m.screen_machine || {}).states).forEach((s) => { labels[s.id] = s.cn; });
  // 控件种类 → 允许态：门禁写成"什么时候点不动"，不写内部状态名
  const cm = m.click_machine || {};
  const stLabel = {};
  arr(cm.states).forEach((s) => { stLabel[s.key] = s.label || s.key; });
  const gate = {};
  arr(cm.kinds).forEach((k) => {
    const ok = arr(k.allow).map((x) => stLabel[x] || x).join(" / ");
    gate[k.key] = { allow: ok, note: k.note || "" };
  });
  if (!inv.length) return emptyHtml(sec.empty);
  const gateOf = (r) => {
    const g = gate[r.kind];
    if (!g) return "";
    return g.note ? `${g.note}｜只在「${g.allow}」时点得动` : `只在「${g.allow}」时点得动`;
  };
  return `<div class="elem-pages">${Object.keys(labels).filter((k) => inv.some((r) => ("view:" + r.view) === k))
    .map((k) => {
      const rows = inv.filter((r) => ("view:" + r.view) === k);
      // 同一控件在一页上出现多次（每行一个实例）只列一条，数量当计数
      const uniq = {};
      rows.forEach((r) => { (uniq[r.ctl] = uniq[r.ctl] || { row: r, n: 0 }).n += 1; });
      const list = Object.keys(uniq).map((c) => Object.assign({}, uniq[c].row, { count: uniq[c].n }));
      const elemKey = "view:" + (((ctx || {}).route || {}).view || "") + ":elem:" + k;
      return `<details class="elem-page"${foldAttr(elemKey)}><summary data-clk="section_fold" data-ctl="ctl.section_fold" data-ctl-state="idle"><b>${esc(labels[k])}</b><span class="elem-count">${list.length}</span></summary>
        <div class="elem-list">${list.map((r) =>
          `<div class="elem-row"><span class="elem-label">${esc(r.label || r.ctl)}${r.count > 1 ? `<i class="elem-n">×${r.count}</i>` : ""}</span><span class="elem-tag">${esc(r.tag || "")}</span>
            <span class="elem-eff">${esc(r.effect || "")}</span>
            <span class="elem-gate">${esc(gateOf(r))}</span></div>`).join("")}</div>
      </details>`;
    }).join("")}</div>`;
}

/* stack：只列前 N 条 + "还有 N 条点不开" 的替代原语。行数不截断，默认全部收起，
   展开态走 foldAttr 持久化；代表链路 chips 可点进链路详情。 */
const STACK_OPEN = "stack_open";
const STACK_LINK = "stack_link";
function stackRowKey(row, i) { return String(row.key || row.id || row.trace || i); }
function stackHtml(sec, ctx) {
  let rows = arr(ref(sec.source, ctx));
  if (!rows.length) return emptyHtml(sec.empty || {});
  if (sec.sort && sec.sort.by) {
    const dir = sec.sort.order === "asc" ? 1 : -1;
    rows = rows.slice().sort((a, b) => dir * String(dig(a, sec.sort.by) || "").localeCompare(String(dig(b, sec.sort.by) || "")));
  }
  const item = sec.item || {};
  const view = ((ctx.route || {}).view) || "";
  const bar = sec.count_note
    ? `<div class="stack-bar"><span class="muted">${esc(fill(sec.count_note, ctx))}</span></div>` : "";
  const items = rows.map((row, i) => {
    const c = { ...ctx, row };
    const key = "stack:" + view + ":" + (sec.as || "") + ":" + stackRowKey(row, i);
    const title = fill(item.title, c);
    const sub = item.sub ? fill(item.sub, c) : "";
    const badge = item.badge ? fill(item.badge, c) : "";
    const badgeSuffix = item.badge_suffix ? ` ${esc(item.badge_suffix)}` : "";
    const fields = (sec.fields || []).map((f) => {
      const raw = fmtVal(f, c);
      const v = raw === undefined || raw === null || raw === "" ? (f.fallback || "—") : raw;
      const suffix = f.suffix ? ` ${esc(f.suffix)}` : "";
      return `<div class="stack-field"><span>${esc(f.label || "")}</span><div>${esc(v)}${suffix}</div></div>`;
    }).join("");
    let samplesHtml = "";
    if (sec.samples) {
      const sp = sec.samples;
      const list = arr(fill(sp.from, c)).slice(0, sp.max || 5);
      if (list.length) {
        const chips = list.map((x) => {
          const t = dig(x, sp.text);
          const v = sp.value ? dig(x, sp.value) : "";
          let go = "";
          if (sp.on_click) {
            go = ` data-go="${actIndex({ view: sp.on_click.view, params: sp.on_click.params || {} }, c)}"`;
          }
          return `<span class="chip stack-sample" data-clk="${STACK_LINK}"${go}>${esc(t)}${v ? ` <i>${esc(v)}</i>` : ""}</span>`;
        }).join("");
        samplesHtml = `<div class="stack-samples"><span class="chips-label">${esc(fill(sp.label || "", c))}</span><div class="chips">${chips}</div></div>`;
      }
    }
    return `<details class="stack-item"${foldAttr(key)}>
      <summary data-clk="${STACK_OPEN}" data-ctl="ctl.stack_open" data-ctl-state="idle">
        <span class="stack-title">${esc(title)}</span>${sub ? `<span class="muted">${esc(sub)}</span>` : ""}${badge ? `<span class="chip stack-badge">${esc(badge)}${badgeSuffix}</span>` : ""}
      </summary>
      <div class="stack-body">${fields}${samplesHtml}</div>
    </details>`;
  }).join("");
  return `<div class="stack">${bar}${items}</div>`;
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
  else if (kind === "gate") html = secHead(sec, ctx) + gateHtml(sec, ctx);
  else if (kind === "machine") html = secHead(sec, ctx) + clickMachineHtml(sec, ctx);
  else if (kind === "kinds") html = secHead(sec, ctx) + clickKindsHtml(sec, ctx);
  else if (kind === "pages") html = userPagesHtml(sec, ctx);
  else if (kind === "routes") html = userRoutesHtml(sec, ctx);
  else if (kind === "elems") html = userElemsHtml(sec, ctx);
  else if (kind === "map") html = mapHtml(sec, ctx);
  else if (kind === "waterfall") html = waterfallHtml(sec, ctx);
  else if (kind === "table") html = tableHtml(sec, ctx);
  else if (kind === "chat") html = chatHtml(sec, ctx);
  else if (kind === "kv") html = kvHtml(sec, ctx);
  else if (kind === "tree") html = secHead(sec, ctx) + treeHtml(sec, ctx);
  else if (kind === "doc") html = docHtml(sec, ctx);
  else if (kind === "stack") html = stackHtml(sec, ctx);
  else if (kind === "composer") html = composerHtml(sec, ctx);
  else html = emptyHtml({ text: uiText("unknown_kind", kind) });
  // sec.fold 是规格声明的折叠；pages/routes/elems 三个主区块内容过多，默认同样收起。
  const viewKey = "view:" + (((ctx || {}).route || {}).view || "") + ":sec:" + idx;
  let fold = null;
  if (sec.fold) {
    fold = { title: fill((sec.fold || {}).title || sec.heading || "", ctx),
             note: sec.note ? fill(sec.note, ctx) : "" };
  } else if (kind === "pages" || kind === "routes" || kind === "elems") {
    fold = { title: fill(sec.heading || "", ctx), note: sec.note ? fill(sec.note, ctx) : "" };
  }
  if (fold) {
    return `<div class="vsec${sec.list ? " vsec-list" : ""} vsec-fold" data-kind="${esc(kind)}"${marks}>${foldBox(viewKey, fold.title, fold.note, html)}</div>`;
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
  // 手机上是纵向卡片堆叠：折叠块默认摊开，免得只看到一行标题不知道这页是什么。
  // 只摊开"本次渲染未记录过状态"的键；用户手动收起/展开过的，按 foldAttr 持久化态恢复，不覆盖。
  if (getComputedStyle(rail).flexDirection === "column") {
    cards.forEach((c) => c.querySelectorAll(":scope > details, :scope > .orphans > details")
      .forEach((d) => {
        const key = d.dataset.fold;
        if (!key) return;
        if (!FOLDS.has(key)) d.open = true;
      }));
  }
}

function headHtml(spec, ctx) {
  // 页头徽章：已归档/只读这类"整页的态"必须写在标题旁，而不是藏在某个区块里
  const badges = (spec.badges || []).filter((b) => b && condOf(b.when, ctx))
    .map((b) => `<sl-badge variant="${badgeTone(b.tone || "archived")}" class="badge ${esc(b.tone || "archived")}">${esc(fill(b.text || "", ctx))}</sl-badge>`).join("");
  return `<div class="view-head">
      <div style="min-width:0"><h2>${esc(fill(spec.heading || spec.heading_from || "", ctx))}${badges}</h2>
      <div class="desc">${esc(fill(spec.subheading || "", ctx))}</div></div>
      <div class="spacer"></div>
      <div class="actions">${(spec.actions || []).map((a) => buttonHtml(a, ctx, { clk: "head_act" })).join("")}</div>
    </div>`;
}

/* 图容器挂载：每个 .graph-wrap 按自己 data-spec 里的规格挂一张 HiveGraph。
   保活恢复 / 局部刷新重渲染后都要重挂，旧实例由 HiveGraph.mount 销毁重建。 */
function mountGraphs() {
  if (!window.HiveGraph) return;
  document.querySelectorAll("#view-body .graph-wrap").forEach((el) => {
    let spec = null;
    try { spec = JSON.parse(el.dataset.spec || "null"); } catch (e) { spec = null; }
    if (spec) HiveGraph.mount(el, spec);
  });
}

/* 区块分栏：只按 lane 声明分组，不丢内容。
   没有 lane 的区块归 single，按原序整行渲染在双列网格之上（以前这里被整段覆盖丢掉）。 */
function groupSections(sections) {
  const g = { single: [], left: [], right: [] };
  (sections || []).forEach((sec, i) => {
    const item = { sec: sec, i: i };
    if (!sec) return;
    if (sec.lane === "left") g.left.push(item);
    else if (sec.lane === "right") g.right.push(item);
    else g.single.push(item);
  });
  return g;
}

/* 分栏拼装：single 整行在前，再放 left/right 双列；单侧有内容时该列占满整行。 */
function composeBody(rendered) {
  const one = rendered.single.join("");
  if (!rendered.left.length && !rendered.right.length) return one;
  const twoSided = rendered.left.length && rendered.right.length;
  const grid = `<div class="ticket-grid${twoSided ? "" : " solo"}">
      <div class="lane lane-left">${rendered.left.join("")}</div>
      ${twoSided ? `<div class="lane lane-right">${rendered.right.join("")}</div>` : ""}
    </div>`;
  return one + grid;
}

function renderView(spec, ctx) {
  ACTS = new Map();   // 每页一份绑定表：旧页面的表由保活实例自己留着
  const head = headHtml(spec, ctx);
  const g = groupSections(spec.sections);
  const rendered = {
    single: g.single.map((it) => sectionHtml(it.sec, ctx, it.i)),
    left: g.left.map((it) => sectionHtml(it.sec, ctx, it.i)),
    right: g.right.map((it) => sectionHtml(it.sec, ctx, it.i)),
  };
  let body = composeBody(rendered);
  // 内容区单独包一层：桌面纵向排布，手机变成横滑吸附的卡片轨
  $("view-body").innerHTML = head + `<div class="view-scroll">${body}</div>`;
  pruneEmptyCards();
  expandFolds();
  if (typeof mountDecks === "function") mountDecks();
  if (typeof mountGraphs === "function") mountGraphs();
  // 浏览器标题也由外壳词表拼：视图名走规格，品牌名走后端
  const name = String(fill(spec.heading || spec.heading_from || "", ctx) || "").trim();
  if (BRAND.title_view && name) {
    const parts = [name, BRAND.name || ""];
    let idx = 0;
    document.title = String(BRAND.title_view).replace(/\{\}/g, () => (idx++ === 0 ? parts[0] : parts[1]));
  }
  else if (BRAND.title) document.title = BRAND.title;
}
