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
  if (typeof setClickMachine === "function") setClickMachine(shell.click_machine);
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

/* 同层多条需求一次往返：跨公网一条一个 RTT，翻一页发四五条就是四五次等待。
   calls = [{id, input}]；返回按顺序的 [{ok, data, error}]，单条失败不拖垮同批。 */
async function runBatch(calls) {
  let resp, body;
  try {
    resp = await fetch("/api/rpc/demand_engine/batch", {
      method: "POST", headers: headers(),
      body: yamlBody({ calls: calls.map((c) => ({ id: c.id, input: c.input || {} })) })
    });
    body = await readYaml(resp).catch(() => ({ ok: false, error: uiText("bad_yaml"), code: "bad_yaml" }));
  } catch (e) {
    throw Object.assign(new Error(uiText("net_fail", e.message)), { status: 0, code: "network" });
  }
  if (!body.ok) {
    if (resp.status === 401 || body.code === "unauthorized") { clearToken(); location.href = "/login.html"; return []; }
    throw Object.assign(new Error(body.error || ("HTTP " + resp.status)),
      { status: resp.status, code: body.code });
  }
  // /batch 直接回 {items}；/run 会多套一层 result.result，两种形状都认
  const payload = body.result || {};
  const items = payload.items || ((payload.result || {}).items) || [];
  return calls.map((c, i) => {
    const it = items[i] || {};
    const inner = (it.result && it.result.result) || {};
    if (!it.ok) return { ok: false, data: {}, error: it.error || uiText("demand_fail") };
    if (inner && inner.ok === false) return { ok: false, data: {}, error: inner.error || inner.code || uiText("demand_fail") };
    return { ok: true, data: inner || {} };
  });
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
  return d.toLocaleString("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit",
                                     hour: "2-digit", minute: "2-digit" });
}


/* ---- 路由与视图 ---- */
let VIEWS = {}, FORMS = {}, state = { view: "" };
let ACTS = new Map(), ACT_SEQ = 0, FILTER = null, modalSubmit = null, MODAL_CTX = null;

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
function stashPage() {
  // 离开前把当前页的滚动位置与最新 DOM 存回实例：回来时连滚到哪儿都一样
  const p = PAGE_KEEP.get(keepKey(state));
  if (!p) return;
  const scroll = document.querySelector("#view-body .view-scroll");
  if (scroll) p.scroll = scroll.scrollTop;
  const body = $("view-body");
  if (body) p.html = body.innerHTML;
}

async function go(next, push) {
  stashPage();
  state = next;
  if (push) history.pushState(next, "", qsOf(next));
  // reload:true 是"刚写完的东西必须立刻看得见"：不走实例缓存，直接重取这一页
  const key = keepKey(next);
  if (next.reload) PAGE_KEEP.delete(key);
  const kept = PAGE_KEEP.get(key);
  if (kept && !kept.stale) { restorePage(kept); return; }
  await render().catch((err) => banner(gateMessage(err), "err"));
}

async function boot() {
  // 整页一次往返：服务端按视图规格把依赖算完、并发跑完，连外壳与视图清单一起回。
  // 前端只带 URL 上的参数，不知道这一页要几份数据、谁依赖谁。
  const q = new URLSearchParams(location.search);
  const params = {}; q.forEach((v, k) => { if (k !== "view") params[k] = v; });
  let page = {}, shell = {};
  try { page = await resolvePage(q.get("view") || "", params, true); }
  catch (err) { if (err && err.status === 401) return; page = {}; }
  if (page.views && page.views.length) {
    shell = page.shell || {};
    adoptViews(page.views);
  } else {
    // 兜底：视图名不认识或没回清单时，退回"外壳 + 清单"两件一起取
    const [viewsRes, shellRes] = await runBatch([
      { id: "views-list", input: {} }, { id: "console-shell", input: {} }]);
    if (!viewsRes.ok) throw new Error(viewsRes.error || uiText("no_views"));
    shell = shellRes.ok ? shellRes.data : {};
    adoptViews(viewsRes.data);
  }
  applyShell(shell);
  renderMenus((shell && shell.menus && shell.menus.length) ? shell.menus : menusFromViews());
  state = parseURL();
  let pre = page || null;
  if (page && page.view && state.view !== page.view) {
    // 服务端已经退回默认页（链接里的视图不认识）：同一次往返的数据就是这页的，
    // 把地址改成它，直接渲染，不再补第二次取数。
    state = Object.assign({}, state, { view: page.view });
    history.replaceState(state, "", qsOf(state));
  } else if (q.get("view") && !VIEWS[q.get("view")]) {
    history.replaceState(state, "", qsOf(state));   // 地址里的视图不认识：换成真实页，别留死链
  }
  await render({ pre });
  openInvalidate();
}
function adoptViews(items) {
  for (const it of items || []) {
    const v = it && it.view;
    if (!v) continue;
    if (v.key) VIEWS[v.key] = v;
    if (v.labels) Object.assign(LABELS, v.labels);
    for (const f of v.forms || []) FORMS[f.id] = f;
  }
  if (!Object.keys(VIEWS).length) throw new Error(uiText("no_views") || "没有任何视图规格，页面无法启动");
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

/* 整页取数：只报"看哪一页、什么参数"，依赖分层与并发都在服务端按视图规格做。
   前端不再猜哪份数据依赖哪份——那本来就不是前端该有的业务知识。 */
async function resolvePage(view, params, wantShell, only) {
  let resp, body;
  try {
    resp = await fetch("/api/rpc/demand_engine/resolve", {
      method: "POST", headers: headers(),
      body: yamlBody({ view: view || "", params: params || {}, shell: !!wantShell, only: only || [] })
    });
    body = await readYaml(resp).catch(() => ({ ok: false, error: uiText("bad_yaml"), code: "bad_yaml" }));
  } catch (e) {
    throw Object.assign(new Error(uiText("net_fail", e.message)), { status: 0, code: "network" });
  }
  if (!body.ok) {
    if (resp.status === 401 || body.code === "unauthorized") { clearToken(); location.href = "/login.html"; return {}; }
    throw Object.assign(new Error(body.error || ("HTTP " + resp.status)),
      { status: resp.status, code: body.code });
  }
  const p = body.result || {};
  return p.result || p;   // 兼容多套一层
}

/* 局部/整页重渲染会重建滚动容器，浏览器把 scrollTop 归零——表现就是「自己跳到最上面」。
   统一记账：渲染前记住每个可滚容器滚到哪、离底多远；渲染后按同类顺序还回去。
   贴底的（离底 ≤ 48px）继续贴底；用户上滑读历史的回到原位，不被打断。 */
const SCROLL_KEEP = "#view-body .view-scroll, #view-body .chat, #view-body .tbl-wrap, " +
  "#view-body .deck-stage, #view-body .flow-map, #drawer .drawer-body, [data-scroll-keep]";
const SCROLL_BOTTOM = 48;
function scrollKeyOf(el) { return el.tagName + "." + ((el.classList && el.classList[0]) || ""); }
function scrollMarks() {
  const out = [], seen = new Map();
  document.querySelectorAll(SCROLL_KEEP).forEach((el) => {
    if (el.scrollHeight <= el.clientHeight + 1) return;    // 不可滚的不记
    const key = scrollKeyOf(el);
    const nth = seen.get(key) || 0; seen.set(key, nth + 1);
    out.push({ key, nth, top: el.scrollTop, bottom: el.scrollHeight - el.scrollTop - el.clientHeight });
  });
  return out;
}
let SCROLL_USER_AT = 0;    // 用户自己滚动过的时刻：复核时让路，不跟手指抢
["pointerdown", "touchmove", "wheel"].forEach((ev) => {
  document.addEventListener(ev, () => { SCROLL_USER_AT = Date.now(); }, { passive: true, capture: true });
});
function scrollRestore(marks) {
  if (!marks || !marks.length) return;
  const find = () => {
    const seen = new Map(), now = new Map();
    document.querySelectorAll(SCROLL_KEEP).forEach((el) => {
      const key = scrollKeyOf(el);
      const nth = seen.get(key) || 0; seen.set(key, nth + 1);
      now.set(key + "#" + nth, el);
    });
    return now;
  };
  const todo = marks.map((m) => ({ m, done: false, want: null, stick: false }));
  let step = 0;
  const apply = () => {
    const now = find();
    let pending = false;
    for (const it of todo) {
      if (it.done) continue;
      const el = now.get(it.m.key + "#" + it.m.nth);
      if (!el || !el.isConnected) { it.done = true; continue; }
      it.stick = it.m.bottom <= SCROLL_BOTTOM;                 // 本来贴底就继续贴底
      const max = Math.max(0, el.scrollHeight - el.clientHeight);
      // 刚换上的节点常常还没撑开：要么完全不可滚，要么只撑到一半（目标位置放不下）。
      // 这时设 scrollTop 会被吞掉/夹小，留到下一轮再设，最多补 4 次。
      if ((max < it.m.top || !max) && step < 4) { pending = true; continue; }
      // 记「期望值」而不是设置后读回的值：浏览器可能当场把位置挪走，读回就成了错的目标
      it.want = it.stick ? max : Math.min(it.m.top, max);
      el.scrollTop = it.want;
      it.done = true;
    }
    if (pending && step < 4) {
      step += 1;
      setTimeout(apply, [0, 50, 150, 400][step] || 400);
    }
  };
  apply();
  // 浏览器重排会按自己的锚点把位置挪走（实测 106 被挪成 30）：隔一帧复核一次，只纠一次
  const verify = () => {
    if (Date.now() - SCROLL_USER_AT < 300) return;             // 用户正在滑，别插手
    const now = find();
    for (const it of todo) {
      if (it.want == null) continue;
      const el = now.get(it.m.key + "#" + it.m.nth);
      if (!el || !el.isConnected) continue;
      const max = Math.max(0, el.scrollHeight - el.clientHeight);   // 内容可能又长高了，目标跟着重算
      const target = it.stick ? max : Math.min(it.m.top, max);
      if (Math.abs(el.scrollTop - target) > 2) el.scrollTop = target;
    }
  };
  requestAnimationFrame(() => setTimeout(verify, 0));
  setTimeout(verify, 160);
}

async function render(opts) {
  const spec = VIEWS[state.view] || VIEWS[defaultView()];
  const ctx = { route: state, data: {}, cache: {}, fields: {}, row: null };
  // 缺必填参数的页面（比如直接开 /?view=knowledge-doc）不发请求：
  // 请求必然失败、页面只剩空壳，看起来就是"卡住不动"
  const missing = (spec.require || []).filter((k) => !state[k]);
  if (missing.length) {
    renderCrumb(spec, { route: state, data: {}, cache: {}, fields: {}, row: null });
    $("view-body").innerHTML = `<div class="view-scroll"><div class="vsec"><div class="empty">${esc(spec.empty_hint || uiText("need_param"))}</div></div></div>`;
    openStream("");
    return;
  }
  const pre = opts && opts.pre;
  if (pre && pre.data) {
    ctx.data = pre.data || {};
    ctx.cache = pre.cache || {};
  } else {
    const page = await resolvePage(state.view, state, false);
    ctx.data = page.data || {};
    ctx.cache = page.cache || {};
    if ((page.missing || []).length) {
      $("view-body").innerHTML = `<div class="view-scroll"><div class="vsec"><div class="empty">${esc(spec.empty_hint || uiText("need_param"))}</div></div></div>`;
      return;
    }
  }
  if (!(opts && opts.keepBanner)) banner("");
  const draft = (document.querySelector("#view-body .composer textarea") || {}).value || "";
  renderCrumb(spec, ctx);
  const marks = scrollMarks();          // 整页重渲染前记账（15s 兜底轮询走的就是这条）
  // 堆叠牌位也是用户意图：重渲染前记账（展开态/当前在第几张），渲染后按原状恢复
  const deckStates = [...$("view-body").querySelectorAll("[data-deck]")]
    .map((d) => ({ open: d.dataset.open, pos: d.dataset.pos }));
  renderView(spec, ctx);
  if (typeof stampCtl === "function") stampCtl(document.querySelector("#view-body"));
  scrollRestore(marks);
  // 堆叠牌位也是用户意图：重渲染前记账（展开态/当前在第几张），渲染后按原状恢复
  [...$("view-body").querySelectorAll("[data-deck]")].forEach((d, i) => {
    const s = deckStates[i];
    if (!s) return;
    if (s.open === "1") d.dataset.open = "1";
    if (s.pos && s.pos !== "0" && Number(s.pos) < d.querySelectorAll(".deck-stage > .pcard").length) {
      d.dataset.pos = s.pos;
      if (typeof deckLayout === "function") deckLayout(d);
    }
  });
  const ta = document.querySelector("#view-body .composer textarea");
  if (ta && draft) ta.value = draft;   // 轮询重建 DOM 时把用户草稿还回去
  const th = (ctx.data.thread && ctx.data.thread.thread) || {};
  LAST_STATUS = th.status || "";
  LAST_CTX = ctx;
  LAST_DRAFT_RUNNING = !!(ctx.data.draft && ctx.data.draft.running);
  openStream(th.id);
  schedulePoll(spec);
  if (typeof highlightNav === "function") highlightNav();
  keepPage(ctx);
}

/* ---- 页面保活：每页留一个实例，离开不销毁，回来直接接管 ---- */
const PAGE_KEEP = new Map();
const KEEP_MAX = 8;
function keepKey(s) { return qsOf(s || state); }
function keepPage(ctx) {
  const body = $("view-body");
  if (!body) return;
  const scroll = document.querySelector("#view-body .view-scroll");
  const key = keepKey(state);
  PAGE_KEEP.delete(key);
  PAGE_KEEP.set(key, {
    view: state.view, params: Object.assign({}, state),
    html: body.innerHTML, crumb: $("crumb").innerHTML,
    scroll: scroll ? scroll.scrollTop : 0, marks: scrollMarks(), ctx, acts: ACTS
  });
  while (PAGE_KEEP.size > KEEP_MAX) PAGE_KEEP.delete(PAGE_KEEP.keys().next().value);
}
function restorePage(k) {
  DECK_DRAG = null;                       // 上一页没收尾的手势不能带进来
  if (typeof uiTo === "function") uiTo("idle", "keep:restore");
  $("crumb").innerHTML = k.crumb || "";
  $("view-body").innerHTML = k.html;
  const scroll = document.querySelector("#view-body .view-scroll");
  if (scroll && k.scroll) scroll.scrollTop = k.scroll;
  scrollRestore(k.marks);                  // 聊天内部容器也要回到原位置，不只是整页
  LAST_CTX = k.ctx;
  ACTS = k.acts || new Map();   // 接管这一页自己的绑定表，按钮才点得动
  const th = (k.ctx.data.thread && k.ctx.data.thread.thread) || {};
  LAST_STATUS = th.status || "";
  LAST_DRAFT_RUNNING = !!(k.ctx.data.draft && k.ctx.data.draft.running);
  openStream(th.id);
  schedulePoll(viewSpec(k.view));
  if (typeof mountDecks === "function") mountDecks();
  if (typeof highlightNav === "function") highlightNav();
  banner("");
}

/* ---- 后端失效：只重取受影响的那份数据，只换吃它的那些区块 ---- */
let INV = null, INV_SEQ = 0, INV_TIMER = null, INV_BUSY = false, INV_AT = 0;
const INV_PENDING = new Set();
const INV_AGAIN = new Set();
const INV_MIN_GAP = 1000;   // 同一页面最短补取间隔：写链路抖动不该变成请求风暴
function openInvalidate() {
  if (INV) return;
  const q = new URLSearchParams({ key: "console.invalidate", token: token() });
  try { INV = new EventSource("/api/sse/runtime/stream_events?" + q.toString()); } catch (e) { INV = null; return; }
  INV.onmessage = (ev) => {
    let snap, msg;
    try { snap = jsyaml.load(ev.data) || {}; } catch (e) { return; }
    const rawText = String(snap.text || "");
    try { msg = JSON.parse(rawText); }            // 引擎推的是单行 JSON
    catch (e) { try { msg = jsyaml.load(rawText) || {}; } catch (e2) { return; } }
    const items = (msg.items || []).filter((x) => Number(x.seq || 0) > INV_SEQ);
    if (!items.length) return;
    INV_SEQ = Math.max.apply(null, items.map((x) => Number(x.seq || 0)));
    for (const it of items) for (const hit of (it.items || [])) hitInvalidate(hit);
  };
  INV.onerror = () => { /* 断线自动重连；保活页仍在，不会白屏 */ };
}
function hitInvalidate(hit) {
  if (!hit || !hit.view) return;
  if (hit.view !== state.view) {
    for (const p of PAGE_KEEP.values()) if (p.view === hit.view) p.stale = true;
    return;
  }
  if (hit.as) INV_PENDING.add(String(hit.as));
  if (INV_TIMER) clearTimeout(INV_TIMER);
  // 写链路会连发很多帧（同一份数据反复变），按 MIN_GAP 收口成一次补取，末帧数据一定取到
  const wait = Math.max(180, INV_MIN_GAP - (Date.now() - INV_AT));
  INV_TIMER = setTimeout(() => {
    const pend = [...INV_PENDING]; INV_PENDING.clear();
    refreshAs(pend);
  }, wait);
}
async function refreshAs(list) {
  if (!list || !list.length) return;
  if (INV_BUSY) { list.forEach((a) => INV_AGAIN.add(a)); return; }
  INV_BUSY = true;
  const spec = viewSpec(state.view);
  let page;
  try { page = await resolvePage(state.view, state, false, list); } catch (e) { page = null; }
  if (!page || !page.data) return doneRefresh();
  const ctx = LAST_CTX || { route: state, data: {}, cache: {}, fields: {}, row: null };
  Object.assign(ctx.data, page.data);
  Object.assign(ctx.cache, page.cache || {});
  LAST_CTX = ctx;
  const head = document.querySelector("#view-body .view-head");
  if (head) {
    const t = document.createElement("div");
    t.innerHTML = headHtml(spec, ctx);
    if (t.firstElementChild) head.replaceWith(t.firstElementChild);
  }
  renderCrumb(spec, ctx);
  const marks = scrollMarks();          // 失效补取会换掉区块（聊天滚动容器就在区块里）
  // 堆叠牌位也是用户意图：区块重渲染前记账，换完按原状恢复（启用/禁用后不跳回第一张）
  const deckStates = [...$("view-body").querySelectorAll("[data-deck]")]
    .map((d) => ({ open: d.dataset.open, pos: d.dataset.pos }));
  for (const as of list) {
    document.querySelectorAll('#view-body .vsec[data-as="' + as + '"]').forEach((node) => {
      const idx = Number(node.getAttribute("data-sec") || 0);
      const sec = (spec.sections || [])[idx];
      if (!sec) return;
      const t = document.createElement("div");
      t.innerHTML = sectionHtml(sec, ctx, idx);
      if (t.firstElementChild) node.replaceWith(t.firstElementChild);
    });
  }
  scrollRestore(marks);
  if (typeof mountDecks === "function") mountDecks();
  [...$("view-body").querySelectorAll("[data-deck]")].forEach((d, i) => {
    const s = deckStates[i];
    if (!s) return;
    if (s.open === "1") d.dataset.open = "1";
    if (s.pos && s.pos !== "0" && Number(s.pos) < d.querySelectorAll(".deck-stage > .pcard").length) {
      d.dataset.pos = s.pos;
      if (typeof deckLayout === "function") deckLayout(d);
    }
  });
  if (typeof expandFolds === "function") expandFolds();
  pruneActs();
  keepPage(ctx);
  doneRefresh();
}
/* 局部刷新替换了区块，旧区块的 id 会留在表里：按 DOM 反查删掉，表不会越用越大 */
function pruneActs() {
  if (typeof ACTS === "undefined" || !ACTS || !ACTS.forEach) return;
  const alive = new Set();
  document.querySelectorAll("#view-body [data-act], #view-body [data-go]").forEach((n) => {
    if (n.dataset.act) alive.add(n.dataset.act);
    if (n.dataset.go) alive.add(n.dataset.go);
  });
  for (const id of Array.from(ACTS.keys())) if (!alive.has(id)) ACTS.delete(id);
}
function doneRefresh() {
  INV_BUSY = false;
  INV_AT = Date.now();
  if (!INV_AGAIN.size) return;
  const more = [...INV_AGAIN]; INV_AGAIN.clear();
  const wait = Math.max(60, INV_MIN_GAP - (Date.now() - INV_AT));
  setTimeout(() => refreshAs(more), wait);   // 刷新期间又到的失效，补跑一次
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
    if (i === trail.length - 2) return `<button data-crumb="1" data-clk="crumb_up" data-ctl="ctl.crumb_up" data-ctl-state="idle">${esc(text)}</button><span class="sep">/</span>`;
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
