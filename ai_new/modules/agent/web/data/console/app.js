/* app：基础设施 + 路由（不认识业务，只认传输与视图规格）
   这一层只认传输与渲染，不认识任何业务名词：
   - run()：按名跑一条需求
   - fill()/ref()：把规格里的取值表达式解析成实际数据
   - execute()：唯一的动作出口，动作 = 规格里写着的 demand / view / modal
*/
async function readYaml(resp){return jsyaml.load(await resp.text())||{};}
function yamlBody(o){return jsyaml.dump(o,{flowLevel:Infinity,noRefs:true,sortKeys:false});}
const $ = (id) => document.getElementById(id);
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
    body = await readYaml(resp).catch(() => ({ ok: false, error: "响应不是 YAML", code: "bad_yaml" }));
  } catch (e) {
    throw Object.assign(new Error("网络请求失败：" + e.message), { status: 0, code: "network" });
  }
  if (!body.ok) {
    if (resp.status === 401 || body.code === "unauthorized") { clearToken(); location.href = "/login.html"; return; }
    throw Object.assign(new Error(body.error || ("HTTP " + resp.status)),
      { status: resp.status, code: body.code });
  }
  const inner = (body.result && body.result.result) || {};
  if (inner && inner.ok === false) {
    if (resp.status === 401 || inner.code === "unauthorized") { clearToken(); location.href = "/login.html"; return; }
    throw Object.assign(new Error(inner.error || inner.code || "需求失败"),
      { status: resp.status, code: inner.code });
  }
  return inner;
}

function banner(msg, kind) {
  const el = $("banner");
  if (!msg) { el.style.display = "none"; el.textContent = ""; el.className = ""; return; }
  el.className = kind === "ok" ? "ok" : "err";
  el.textContent = msg;
  el.style.display = "block";  // 行内样式优先级最高，隐藏后必须显式改回来
}
function gateMessage(err) {
  if (err && (err.status === 401 || err.code === "unauthorized")) return "登录已失效（401），请重新登录。";
  return (err && err.message) || "操作失败";
}
function when(ts) {
  if (!ts) return "—";
  const d = typeof ts === "number" ? new Date(ts * 1000) : new Date(ts);
  if (isNaN(d.getTime())) return String(ts);
  return d.toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}


/* ---- 路由与视图 ---- */
let VIEWS = {}, FORMS = {}, state = { view: "projects" };
let ACTS = [], FILTER = null, modalSubmit = null, MODAL_CTX = null;

function qsOf(s) {
  const q = new URLSearchParams();
  if (s.view === "tools") q.set("view", "tools");
  else if (s.view === "skills") q.set("view", "skills");
  else if (s.view === "ext-tools") q.set("view", "ext-tools");
  else if (s.view === "positions") q.set("view", "positions");
  else if (s.view === "position") { q.set("view", "position"); q.set("position", s.position || ""); }
  else if (s.ticket) { q.set("project", s.project || ""); q.set("ticket", s.ticket); }
  else if (s.project) q.set("project", s.project);
  const str = q.toString();
  return str ? "/manage.html?" + str : "/manage.html";
}
function parseURL() {
  const q = new URLSearchParams(location.search);
  if (q.get("view") === "tools") return { view: "tools" };
  if (q.get("view") === "skills") return { view: "skills" };
  if (q.get("view") === "ext-tools") return { view: "ext-tools" };
  if (q.get("view") === "positions") return { view: "positions" };
  if (q.get("view") === "position") return { view: "position", position: q.get("position") || "" };
  const p = q.get("project") || "";
  const t = q.get("ticket") || "";
  if (t) return { view: "ticket", project: p, ticket: t };
  if (p) return { view: "project", project: p };
  return { view: "projects" };
}
async function go(next, push) {
  state = next;
  if (push) history.pushState(next, "", qsOf(next));
  await render().catch((err) => banner(gateMessage(err), "err"));
}

async function boot() {
  const items = arr(await run("views-list", {}));
  for (const it of items) {
    const v = it && it.view;
    if (!v) continue;
    if (v.key) VIEWS[v.key] = v;
    for (const f of v.forms || []) FORMS[f.id] = f;
  }
  if (!VIEWS.projects) throw new Error("没有 projects 视图规格，页面无法启动");
  state = parseURL();
  await render();
}

let POLL = null;   // 视图级轮询句柄：只有声明了 poll 的视图才自刷新
let LAST_STATUS = "";  // 最近一次会话状态：忙碌时高频轮询，空闲/结单后拉长间隔

function typing() {
  const ta = document.querySelector("#view-body .composer textarea");
  return !!(ta && ta === document.activeElement && (ta.value || "").trim());
}

function schedulePoll(spec) {
  if (POLL) { clearTimeout(POLL); POLL = null; }
  if (!spec || !spec.poll) return;
  const busy = ["running", "queued", "doing"].includes(LAST_STATUS);
  const interval = busy ? Number(spec.poll) : Math.max(8000, Number(spec.poll) * 5);
  POLL = setTimeout(async () => {
    if (typing()) { schedulePoll(spec); return; }  // 用户正在写，不抢输入
    try { await render({ keepBanner: true }); } catch (e) {}
  }, interval);
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
  const spec = VIEWS[state.view] || VIEWS.projects;
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
  schedulePoll(spec);
}

function crumbUp() {
  if (state.view === "ticket") return { view: "project", project: state.project || "" };
  return { view: "projects" };
}
function renderCrumb(spec, ctx) {
  const parts = (spec.crumb || []).map((x) => fill(x, ctx)).filter(Boolean);
  if (!parts.length) { $("crumb").innerHTML = ""; return; }
  $("crumb").innerHTML = parts.map((text, i) => {
    const last = i === parts.length - 1;
    if (last) return `<span class="now">${esc(text)}</span>`;
    return `<button data-crumb="1">${esc(text)}</button><span class="sep">/</span>`;
  }).join("");
}
