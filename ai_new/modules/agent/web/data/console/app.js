/* app：基础设施 + 路由（不认识业务，只认传输与视图规格）
   这一层只认传输与渲染，不认识任何业务名词：
   - run()：按名跑一条需求
   - fill()/ref()：把规格里的取值表达式解析成实际数据
   - execute()：唯一的动作出口，动作 = 规格里写着的 demand / view / modal
*/
async function readYaml(resp){return jsyaml.load(await resp.text())||{};}
function yamlBody(o){return jsyaml.dump(o,{flowLevel:Infinity,noRefs:true,sortKeys:false});}
const $ = (id) => document.getElementById(id);

/* ---- 外壳词表：页面上所有"看得见的字"与配色都由后端下发（console-shell），
   这里只留空壳兜底，保证后端没给时页面还能起来，不存第二份业务。 ---- */
let UI = {};                 // 固定文案（空态、按钮、提示）
let BRAND = {};              // 品牌与浏览器标题
let ROLE_COLORS = {};        // 角色 -> 配色
let ROLE_LABELS = {};        // 角色 -> 称呼
let ROLE_PALETTE = [];       // 未登记角色的回退色板
let FIELD_LABELS = {};       // 工具结果字段 -> 显示名
let FIELD_ORDER = [];        // 字段展示顺序
let STATUS_META = { busy: [], offline: [], labels: {} };

function uiText(key, ...args) {
  let s = UI[key];
  if (s == null) return "";
  return String(s).replace(/\{\}/g, () => (args.length ? String(args.shift()) : ""));
}
function roleLabel(role) { return ROLE_LABELS[role] || role || ""; }

function applyShell(shell) {
  shell = shell || {};
  UI = shell.ui || {};
  BRAND = shell.brand || {};
  const roles = shell.roles || {};
  ROLE_COLORS = roles.colors || {};
  ROLE_LABELS = roles.labels || {};
  ROLE_PALETTE = roles.palette || [];
  const fields = shell.fields || {};
  FIELD_LABELS = fields.labels || {};
  FIELD_ORDER = fields.order || [];
  const st = shell.status || {};
  STATUS_META = { busy: st.busy || [], offline: st.offline || [], labels: st.labels || {} };
  // 静态外壳：品牌、标题、固定按钮与 aria 文案
  document.title = BRAND.title || document.title;
  document.querySelectorAll("[data-ui]").forEach((el) => {
    const txt = uiText(el.dataset.ui);
    if (txt) el.textContent = txt;
  });
  document.querySelectorAll("[data-ui-title]").forEach((el) => {
    const txt = uiText(el.dataset.uiTitle);
    if (txt) el.title = txt;
  });
  document.querySelectorAll("[data-ui-aria]").forEach((el) => {
    const txt = uiText(el.dataset.uiAria);
    if (txt) el.setAttribute("aria-label", txt);
  });
  document.querySelectorAll("[data-brand]").forEach((el) => {
    const txt = BRAND[el.dataset.brand];
    if (txt != null) el.textContent = txt;
  });
}
function readCookie(name) {
  const m = document.cookie.match(new RegExp("(?:^|; )" + name + "=([^;]*)"));
  return m ? decodeURIComponent(m[1]) : "";
}
const token = () => localStorage.getItem("ai_new_token") || readCookie("hive_token") || "";
function clearToken() {
  localStorage.removeItem("ai_new_token");
  sessionStorage.removeItem("hive.token");
  document.cookie = "hive_token=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT";
}
function headers() {
  const h = { "Content-Type": "application/yaml" };
  if (token()) h["X-Auth-Token"] = token();
  return h;
}
function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"]/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

// 轻量 Markdown 渲染：先整体转义杜绝原始 HTML 注入，再在安全文本上解析基础语法
// 支持：标题(#/##/###)、加粗、斜体、行内代码、有序/无序列表、链接(http/https/相对路径)、软换行。
function renderMarkdown(text) {
  const raw = String(text == null ? "" : text);
  if (!raw.trim()) return "";
  let s = esc(raw);
  // 抽出行内代码占位保护，避免代码内的 * _ ` 被当作语法解析
  const codes = [];
  s = s.replace(/`([^`]+)`/g, (_, c) => { codes.push(c); return "\u0000" + (codes.length - 1) + "\u0000"; });

  const inline = (t) => t
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<em>$2</em>")
    .replace(/\[([^\]]+)\]\((https?:[^)\s]+|\/[^)\s]*)\)/g,
      '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');

  const lines = s.split(/\r?\n/);
  const out = [];
  let list = null;
  let para = [];
  const closeList = () => { if (list) { out.push(`</${list}>`); list = null; } };
  const flushPara = () => { if (para.length) { out.push(`<p>${para.join("<br>")}</p>`); para = []; } };

  for (const line of lines) {
    let m;
    if (/^\s*#{1,3}\s+/.test(line)) {
      flushPara(); closeList();
      out.push(`<h5>${inline(line.replace(/^\s*#{1,3}\s+/, ""))}</h5>`);
    } else if ((m = line.match(/^\s*[-*]\s+(.*)$/))) {
      flushPara();
      if (list !== "ul") { closeList(); list = "ul"; out.push("<ul>"); }
      out.push(`<li>${inline(m[1])}</li>`);
    } else if ((m = line.match(/^\s*\d+[.)]\s+(.*)$/))) {
      flushPara();
      if (list !== "ol") { closeList(); list = "ol"; out.push("<ol>"); }
      out.push(`<li>${inline(m[1])}</li>`);
    } else if (!line.trim()) {
      flushPara(); closeList();
    } else {
      para.push(inline(line));
    }
  }
  flushPara(); closeList();

  let html = out.join("");
  html = html.replace(/\u0000(\d+)\u0000/g, (_, i) => `<code>${codes[+i]}</code>`);
  return html;
}

async function run(demand, input) {
  let resp, body;
  try {
    resp = await fetch("/api/rpc/demand_engine/run", {
      method: "POST", headers: headers(),
      body: yamlBody({ id: demand, input: input || {} })
    });
    body = await readYaml(resp).catch(() => ({ ok: false, error: uiText("bad_yaml"), code: "bad_yaml" }));
  } catch (e) {
    throw Object.assign(new Error(uiText("net_fail", e.message)), { status: 0, code: "network" });
  }
  if (!body.ok) {
    if (resp.status === 401 || body.code === "unauthorized") { clearToken(); location.href = "/login.html"; return; }
    throw Object.assign(new Error(body.error || ("HTTP " + resp.status)),
      { status: resp.status, code: body.code });
  }
  const inner = (body.result && body.result.result) || {};
  if (inner && inner.ok === false) {
    if (resp.status === 401 || inner.code === "unauthorized") { clearToken(); location.href = "/login.html"; return; }
    throw Object.assign(new Error(inner.error || inner.code || uiText("demand_fail")),
      { status: resp.status, code: inner.code });
  }
  return inner;
}

function banner(msg, kind) {
  const el = $("banner");
  if (!msg) { el.style.display = "none"; el.textContent = ""; el.className = ""; return; }
  el.className = kind === "ok" ? "ok" : (kind === "info" ? "info" : "err");
  el.textContent = msg;
  el.style.display = "block";  // 行内样式优先级最高，隐藏后必须显式改回来
}
function gateMessage(err) {
  if (err && (err.status === 401 || err.code === "unauthorized")) return uiText("gate_expired");
  return (err && err.message) || uiText("gate_fail");
}
function when(ts) {
  if (!ts) return "—";
  const d = typeof ts === "number" ? new Date(ts * 1000) : new Date(ts);
  if (isNaN(d.getTime())) return String(ts);
  return d.toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}


/* ---- 路由与视图 ---- */
let VIEWS = {}, FORMS = {}, state = { view: "" };
let ACTS = [], FILTER = null, modalSubmit = null, MODAL_CTX = null;

function viewSpec(view) { return VIEWS[view] || {}; }
function viewParams(view) { return viewSpec(view).params || []; }
function defaultView() {
  const keys = Object.keys(VIEWS);
  const marked = keys.find((k) => VIEWS[k] && VIEWS[k].default);
  return marked || keys[0] || "";
}
/* URL 只由规格驱动：视图声明 params，前端不认识任何具体视图名。 */
function qsOf(s) {
  const q = new URLSearchParams();
  const ps = viewParams(s.view);
  const isDefault = s.view === defaultView() && !ps.some((p) => s[p]);
  if (!isDefault) q.set("view", s.view);
  for (const p of ps) { const v = s[p]; if (v != null && v !== "") q.set(p, v); }
  const str = q.toString();
  return str ? "/manage.html?" + str : "/manage.html";
}
function parseURL() {
  const q = new URLSearchParams(location.search);
  const v = q.get("view") || "";
  if (v && VIEWS[v]) {
    const s = { view: v };
    for (const p of viewParams(v)) s[p] = q.get(p) || "";
    return s;
  }
  // 旧链接兼容：挑"参数匹配最全"的视图（参数多的优先），不写死视图名。
  let best = null;
  for (const k of Object.keys(VIEWS)) {
    const ps = viewParams(k);
    if (!ps.length) continue;
    const got = ps.filter((p) => q.get(p));
    if (got.length === ps.length && (!best || ps.length > best.n)) best = { k, n: ps.length };
  }
  if (best) {
    const s = { view: best.k };
    for (const p of viewParams(best.k)) s[p] = q.get(p) || "";
    return s;
  }
  return { view: defaultView() };
}
async function go(next, push) {
  state = next;
  if (push) history.pushState(next, "", qsOf(next));
  await render().catch((err) => banner(gateMessage(err), "err"));
}

async function boot() {
  // 视图规格与外壳词表各取一次、并行拿：页面自己不存任何业务字或菜单
  const [items, shell] = await Promise.all([run("views-list", {}), run("console-shell", {})]);
  applyShell(shell);
  for (const it of items) {
    const v = it && it.view;
    if (!v) continue;
    if (v.key) VIEWS[v.key] = v;
    if (v.labels) Object.assign(LABELS, v.labels);
    for (const f of v.forms || []) FORMS[f.id] = f;
  }
  if (!Object.keys(VIEWS).length) throw new Error(uiText("no_views") || "没有任何视图规格，页面无法启动");
  renderMenus((shell && shell.menus && shell.menus.length) ? shell.menus : menusFromViews());
  state = parseURL();
  await render();
}
/* 菜单兜底：console-shell 不可用时，直接按视图规格里的 menu 汇总——
   同一份数据换个读法，不额外存清单。 */
function menusFromViews() {
  const out = [];
  for (const k of Object.keys(VIEWS)) {
    const v = VIEWS[k] || {};
    const m = v.menu;
    if (!m) continue;
    const label = m.label || v.heading || k;
    out.push({ key: m.key || v.nav || v.key || k, label,
               short: m.short || label, order: Number(m.order || 100),
               mobile: m.mobile !== false });
  }
  return out.sort((a, b) => a.order - b.order || (a.key < b.key ? -1 : 1));
}

let POLL = null;   // 视图级低频兜底轮询句柄：只在 SSE 断连时兜底，增量靠 SSE 推送
let LAST_STATUS = "";  // 最近一次会话状态
let ES = null;       // 草稿长连接 EventSource
let ES_KEY = "";     // 当前订阅的会话 key
let LAST_CTX = null; // 最近一次渲染 ctx：供 SSE 局部更新取角色等数据
let LAST_DRAFT_RUNNING = false;

function typing() {
  const ta = document.querySelector("#view-body .composer textarea");
  return !!(ta && ta === document.activeElement && (ta.value || "").trim());
}

function schedulePoll(spec) {
  if (POLL) { clearTimeout(POLL); POLL = null; }
  if (!spec || !spec.poll) return;
  // 增量由 SSE 事件推送；这里只保留低频兜底，覆盖长连接断连/极端场景。
  const interval = Math.max(15000, Number(spec.poll) * 5);
  POLL = setTimeout(async () => {
    if (typing()) { schedulePoll(spec); return; }  // 用户正在写，不抢输入
    try { await render({ keepBanner: true }); } catch (e) {}
  }, interval);
}

function closeStream() {
  if (ES) { try { ES.close(); } catch (e) {} ES = null; }
  ES_KEY = "";
}

function applyDraft(snap) {
  const chat = document.querySelector("#view-body .chat");
  if (!chat) return;
  const roles = (LAST_CTX && LAST_CTX.data && LAST_CTX.data.thread && LAST_CTX.data.thread.members) || [];
  const was = LAST_DRAFT_RUNNING;
  const running = !!(snap && snap.running);
  const txt = String((snap && snap.text) || "");
  LAST_DRAFT_RUNNING = running;
  const existing = chat.querySelector(".draft-bubble");
  if (running && txt.trim()) {
    const html = draftBubbleHtml({ text: txt, running: true }, roles);
    if (existing) existing.outerHTML = html;
    else chat.insertAdjacentHTML("beforeend", html);
  } else {
    if (existing) existing.remove();
    if (was && !running) { render({ keepBanner: true }); }  // 定稿落盘：整页拉新消息
  }
}

function openStream(key) {
  if (!key) { closeStream(); return; }
  if (ES && ES_KEY === key) return;
  closeStream();
  ES_KEY = String(key);
  const q = new URLSearchParams({ key: ES_KEY, token: token() });
  ES = new EventSource("/api/sse/runtime/stream_events?" + q.toString());
  ES.onmessage = (ev) => {
    let snap;
    try { snap = jsyaml.load(ev.data) || {}; } catch (e) { return; }
    applyDraft(snap);
  };
  ES.onerror = () => { /* 浏览器自动重连；低频兜底轮询仍在 */ };
}

function paramRefs(obj, acc) {
  if (typeof obj === "string") {
    const re = /\{([^{}]+)\}/g; let m;
    while ((m = re.exec(obj))) {
      let p = m[1].split("|")[0].trim();
      if (p.startsWith("data.")) p = p.slice(5);
      else if (p.startsWith("cache.")) p = p.slice(6);
      const head = p.split(".")[0];
      if (head) acc.add(head);
    }
  } else if (Array.isArray(obj)) obj.forEach((x) => paramRefs(x, acc));
  else if (obj && typeof obj === "object") Object.values(obj).forEach((x) => paramRefs(x, acc));
}

async function loadData(spec, ctx) {
  // 数据源按依赖分层：参数只引用已就绪数据源的一层并行发起；引用前序结果的下一层再跑。
  const sources = spec.data || [];
  const done = new Set();
  let pending = sources.slice();
  while (pending.length) {
    const ready = [], wait = [];
    for (const src of pending) {
      const refs = new Set();
      paramRefs(src.params || {}, refs);
      if ([...refs].every((a) => done.has(a))) ready.push(src);
      else wait.push(src);
    }
    if (!ready.length) ready.push(wait.shift());  // 环或缺依赖兜底：串行先跑一个
    await Promise.all(ready.map(async (src) => {
      const params = fill(src.params || {}, ctx);
      const res = await run(src.demand, params);
      ctx.data[src.as] = res;
      if (src.cache) ctx.cache[src.cache] = res;
    }));
    ready.forEach((s) => done.add(s.as));
    pending = wait;
  }
}

async function render(opts) {
  const spec = VIEWS[state.view] || VIEWS[defaultView()];
  const ctx = { route: state, data: {}, cache: {}, fields: {}, row: null };
  await loadData(spec, ctx);
  if (!(opts && opts.keepBanner)) banner("");
  const draft = (document.querySelector("#view-body .composer textarea") || {}).value || "";
  renderCrumb(spec, ctx);
  renderView(spec, ctx);
  const ta = document.querySelector("#view-body .composer textarea");
  if (ta && draft) ta.value = draft;   // 轮询重建 DOM 时把用户草稿还回去
  const th = (ctx.data.thread && ctx.data.thread.thread) || {};
  LAST_STATUS = th.status || "";
  LAST_CTX = ctx;
  LAST_DRAFT_RUNNING = !!(ctx.data.draft && ctx.data.draft.running);
  openStream(th.id);
  schedulePoll(spec);
  if (typeof highlightNav === "function") highlightNav();
}

function crumbUp() {
  const spec = viewSpec(state.view);
  if (spec.parent) return resolveView(spec.parent, { route: state, data: {}, cache: {}, fields: {} });
  return { view: defaultView() };
}
function renderCrumb(spec, ctx) {
  // 路径只有一套：根词由词表下发（console.yaml ui.crumb_root），视图只声明"导航名 + 各级"，
  // 所以任何页面第一级都是同一个根，不管从哪进都不会冒出第二个根。
  const root = uiText("crumb_root");
  const parts = (spec.crumb || []).map((x) => fill(x, ctx)).filter(Boolean);
  let trail = parts;
  if (root) trail = [root].concat(parts);
  if (!trail.length) { $("crumb").innerHTML = ""; return; }
  // 末段=当前页（不可点）；倒数第二段=上一级（点了回上级）；更上面的只是层级标识
  $("crumb").innerHTML = trail.map((text, i) => {
    if (i === trail.length - 1) return `<span class="now">${esc(text)}</span>`;
    if (i === trail.length - 2) return `<button data-crumb="1">${esc(text)}</button><span class="sep">/</span>`;
    return `<span class="up">${esc(text)}</span><span class="sep">/</span>`;
  }).join("");
}

/* 网络报文按需回读：视图只带摘要，展开时才去取请求体与响应原文。
   toggle 不冒泡，必须捕获阶段监听。 */
function wireText(w, cap) {
  const cut = (v) => {
    const t = typeof v === "string" ? v : JSON.stringify(v == null ? "" : v, null, 1);
    return cap > 0 && t.length > cap ? t.slice(0, cap) + "\n" + uiText("trunc_note", t.length) : t;
  };
  return "POST " + (w.url || "") + "\n" + uiText("wire_model") + "：" + (w.model || "—")
    + " · " + uiText("wire_stream") + "：" + (w.stream ? uiText("stamp_yes") : uiText("stamp_no")) +
    "\n\n▸ " + uiText("wire_req_body") + "\n" + cut(w.request)
    + "\n\n▸ " + uiText("wire_resp_body") + "\n" + cut(w.response);
}
document.addEventListener("toggle", async (e) => {
  const box = e.target;
  if (!box || !box.classList || !box.classList.contains("wire-box")) return;
  const pre = box.querySelector(".wire-body");
  if (!pre || !box.open) return;
  if (pre.getAttribute("data-loaded")) return;
  pre.textContent = uiText("wire_loading");
  try {
    const demand = box.getAttribute("data-demand") || "";
    if (!demand) { pre.textContent = uiText("wire_no_entry"); return; }
    const out = await run(demand, {
      session: box.getAttribute("data-session") || "",
      seq: Number(box.getAttribute("data-seq") || -1)
    });
    pre.textContent = wireText(out.wire || {}, Number(box.getAttribute("data-chars") || 0));
    pre.setAttribute("data-loaded", "1");
  } catch (err) {
    pre.textContent = uiText("wire_fail", (err && err.message ? err.message : err));
  }
}, true);
