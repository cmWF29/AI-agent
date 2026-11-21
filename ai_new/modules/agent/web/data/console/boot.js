/* boot：事件总线与启动
   只有一条：点到的按钮 -> 动作表 -> 执行器。
*/
/* ---- 点击状态机：全页只有一条入口，规格由后端下发 ----
   状态与迁移、每种可点控件的门禁（allow / enter / exit）都在外壳的 click_machine 里。
   前端只做三件事：解析控件种类 -> 过门禁 -> 按规格迁移。没有第二份状态表。
*/
const AUDIT = /[?&]audit=1/.test(location.search);   // 审计模式：只过门禁与迁移，不真正执行
const UIS = { state: "idle", at: 0, why: "boot", swallowUntil: 0, violations: 0 };
let CLICK_MACHINE = null;

function setClickMachine(spec) {
  CLICK_MACHINE = spec && spec.kinds ? spec : null;
  if (!CLICK_MACHINE) {
    banner("点击状态机规格缺失：页面已锁定点击", "err");   // fail-closed，不许无门禁运行
  }
}
function machineKind(key) {
  if (!CLICK_MACHINE) return null;
  return (CLICK_MACHINE.kinds || []).find((k) => k.key === key) || null;
}
function uiTo(next, why) {
  if (next === UIS.state) { UIS.why = why || ""; return UIS.state; }
  const table = (CLICK_MACHINE && CLICK_MACHINE.transitions) || {};
  if (!table[UIS.state] || table[UIS.state].indexOf(next) < 0) {
    UIS.violations += 1;
    UIS.lastBad = UIS.state + "->" + next + " (" + (why || "") + ")";
    UIS.state = "idle";
    return UIS.state;
  }
  UIS.state = next;
  UIS.why = why || "";
  UIS.at = performance.now();
  return UIS.state;
}
function uiBusy() { return UIS.state === "busy"; }
/* 门禁：控件种类在规格里声明"允许哪些状态点击"，没声明就是漏声明，按违规记。 */
function uiAllowed(kind) {
  if (!CLICK_MACHINE) return false;
  const k = machineKind(kind);
  if (!k) {
    UIS.violations += 1;
    UIS.lastBad = "unknown-kind:" + kind;
    return false;
  }
  return (k.allow || []).indexOf(UIS.state) >= 0;
}
function uiEnter(kind) {
  const k = machineKind(kind);
  if (k && k.enter) uiTo(k.enter, kind);
}
function uiExit(kind) {
  if (UIS.state !== "busy") return;
  const k = machineKind(kind) || {};
  uiTo(k.exit || "idle", kind + ":done");
}
/* 收尾看"这次动作自己的 promise"，包成函数再调用：
   直接传 promise 会在设 busy 之前就把 execute 跑起来，弹窗抢先把状态改成 modal。 */
function uiRun(fn, kind) {
  if (!uiAllowed(kind)) return null;
  uiEnter(kind);
  const done = () => uiExit(kind);
  let p;
  try { p = fn(); } catch (err) { done(); throw err; }
  Promise.resolve(p).then(done, done);
  return p;
}
function uiModal(open) {
  if (!CLICK_MACHINE) return;
  if (open) { if (UIS.state !== "modal") uiTo("modal", "modal:open"); return; }
  if (UIS.state === "modal") uiTo("idle", "modal:close");
}
window.uiSnapshot = () => ({
  state: UIS.state, why: UIS.why, violations: UIS.violations, lastBad: UIS.lastBad || "",
  machine: CLICK_MACHINE ? { states: (CLICK_MACHINE.states || []).map((s) => s.key),
                             kinds: (CLICK_MACHINE.kinds || []).map((k) => k.key) } : null,
});

function consumeSwallow() {
  if (UIS.state !== "swallow") return false;
  if (performance.now() <= UIS.swallowUntil) { uiTo("idle", "swallow:once"); return true; }
  uiTo("idle", "swallow:expired");
  return false;
}

/* 控件种类由渲染层直接声明：每个可点元素自带 data-clk。
   这里只留一张兜底表，给极少数没标的老元素（漏标时点不动比乱跳更糟）。 */
const LEGACY_KINDS = [
  ["deck_toggle", "[data-deck-open]"],
  ["card_act", "[data-act]"],
  ["filter", "[data-filter]"],
  ["card_open", "[data-go]"],
  ["nav", "[data-nav]"],
  ["crumb_up", "[data-crumb]"],
  ["member_chip", "[data-member]"],
  ["fold_text", "[data-expand]"],
];
function resolveKind(target) {
  const el = target && target.closest && target.closest("[data-clk]");
  if (el) return { kind: el.dataset.clk, el };
  for (const pair of LEGACY_KINDS) {
    const hit = target && target.closest && target.closest(pair[1]);
    if (hit) return { kind: pair[0], el: hit };
  }
  return null;
}

/* 动作按钮：所有"有 data-act 的按钮"共用同一段执行逻辑，种类只决定门禁 */
function runAct(el, kind) {
  if (el.disabled) return null;
  const binding = ACTS.get(String(el.dataset.act));
  if (!binding) {   // 绑定表里没有：这次渲染已作废，页面该重取
    UIS.violations += 1; UIS.lastBad = "stale-act:" + el.dataset.act;
    return null;
  }
  if (binding.voice) return uiRun(() => executeVoice(binding, el), kind);
  if (binding.composer && !binding.act.modal) {
    const box = $("view-body").querySelector(".composer textarea");
    const text = (box && box.value || "").trim();
    if (!text) {
      banner(uiText("composer_empty") || binding.act.empty_hint || "请先输入内容", "err");
      return null;
    }
    return uiRun(() => execute(binding, { text }), kind);
  }
  return uiRun(() => execute(binding, {}), kind);
}
function runGo(el, kind) {
  const binding = ACTS.get(String(el.dataset.go));
  if (!binding) { UIS.violations += 1; UIS.lastBad = "stale-go:" + el.dataset.go; return null; }
  return uiRun(() => execute(binding, {}), kind);
}

const CLICK_HANDLERS = {
  drawer_open() { openDrawer(); },
  drawer_scrim() { closeDrawer(); },
  rail_close() { setRail(true); },
  rail_open() { setRail(false); },
  nav(el) { closeDrawer(); return uiRun(() => go({ view: el.dataset.nav }, true), "nav"); },
  crumb_up() { return uiRun(() => go(crumbUp(), true), "crumb_up"); },
  head_act(el) { return runAct(el, "head_act"); },
  card_open(el) { return runGo(el, "card_open"); },
  card_act(el) { return runAct(el, "card_act"); },
  row_open(el) { return runGo(el, "row_open"); },
  row_act(el) { return runAct(el, "row_act"); },
  tree_group(el) {
    const d = el.closest("details.tree-node");
    if (d) d.open = !d.open;
  },
  tree_doc(el) { return runGo(el, "tree_doc"); },
  filter(el) { FILTER = el.dataset.filter; render(); },
  member_chip(el) { return $("popover").hidden ? openMemberCard(el) : closeMemberCard(); },
  popover_close() { closeMemberCard(); },
  fold_text(el) {
    const folded = el.classList.toggle("clamp");
    const t = el.querySelector(".ev-text");
    if (t) t.textContent = folded ? (el.dataset.short || "") : (el.dataset.full || "");
  },
  /* 原生 details/summary 自己会开关，这里不拦默认行为，只让状态机记账 */
  wire_fold() {},
  summary_fold() {},
  raw_fold() {},
  /* 弹窗三个入口在 actions.js 里自己过门禁并执行，这里只登记，不重复执行 */
  modal_ok() {},
  modal_cancel() {},
  modal_backdrop() {},
  /* 堆叠滑动由 pointer 事件驱动；这里登记是为了让规格与页面双向闭合 */
  deck_swipe() {},
  deck_toggle(el) {
    const d = el.closest("[data-deck]");
    if (!d) return;
    d.dataset.open = d.dataset.open === "1" ? "0" : "1";
    deckLayout(d);
  },
  composer_send(el) { return runAct(el, "composer_send"); },
  composer_voice(el) { return runAct(el, "composer_voice"); },
};

function handleClick(e) {
  const hit = resolveKind(e.target);
  if (UIS.state === "swallow") {
    // 吞的是"滑完紧跟着的那一下"；点堆叠展开按钮不是滑动余波，放它过去
    if (hit && hit.kind === "deck_toggle") { uiTo("idle", "swallow:deck-toggle"); }
    else if (consumeSwallow()) { e.stopPropagation(); e.preventDefault(); return; }
  }
  // 弹窗里的事件由弹窗自己管：只放 modal_* 过去（它们自己过门禁），其余一律不理
  if (UIS.state === "modal" && !(hit && hit.kind.indexOf("modal_") === 0)) return;
  if (!hit) {                                 // 点在空白：只负责收浮层
    if (!e.target.closest("#popover") && !$("popover").hidden) {
      if (uiAllowed("popover_close")) CLICK_HANDLERS.popover_close();
    }
    return;
  }
  if (!uiAllowed(hit.kind)) return;           // 门禁拒绝：不猜、不排队
  if (AUDIT) {                                 // 审计：走一遍进入/回落，证明迁移合法
    uiEnter(hit.kind);
    setTimeout(() => {
      const exit = (machineKind(hit.kind) || {}).exit;
      if (exit && UIS.state !== exit) uiTo(exit, "audit:" + hit.kind);
      else if (!exit && UIS.state !== "idle") uiTo("idle", "audit:" + hit.kind);
    }, 60);
    return;
  }
  const fn = CLICK_HANDLERS[hit.kind];
  if (fn) return fn(hit.el, e);
}
document.addEventListener("click", handleClick);

document.addEventListener("scroll", () => closeMemberCard(), true);
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") { closeDrawer(); return; }
  if (e.key !== "Enter" && e.key !== " ") return;
  const card = e.target.closest && e.target.closest("[data-go][role=button]");
  if (card) { e.preventDefault(); card.click(); }
  const ta = e.target;
  if (ta && ta.tagName === "TEXTAREA" && e.key === "Enter" && !e.shiftKey) {
    const box = ta.closest(".composer");
    if (box) {
      const btn = box.querySelector("button.primary");
      if (btn) { e.preventDefault(); btn.click(); }
    }
  }
});

/* ---- 卡片堆叠（deck）：收缩时叠着放，左右滑动换牌；展开时铺成列表 ----
   位置由 --pos 决定（0=最上面那张），拖动只用 --dx 做临时位移，松手后重排。 ---- */
/* 真机触摸拖动后浏览器不会派发 click（pointermove 被 preventDefault 了），
   吞点击的窗口交给上面 UI 状态机的 swallow，这里只记手势本身。 */
let DECK_DRAG = null;

function deckCards(d) { return [...d.querySelectorAll(".deck-stage > .pcard")]; }

function deckMetrics(d) {
  // 位移步长只在样式里写一次（桌面/手机两套），这里读回来算像素，不存第二份数值
  const stage = d.querySelector(".deck-stage");
  const cs = getComputedStyle(stage);
  return {
    ox: parseFloat(cs.getPropertyValue("--ox")) || 9,
    oy: parseFloat(cs.getPropertyValue("--oy")) || 13,
  };
}

function deckLayout(d) {
  const cards = deckCards(d), n = cards.length;
  const stage = d.querySelector(".deck-stage");
  const btn = d.querySelector("[data-deck-open]");
  const posEl = d.querySelector(".deck-pos");
  const open = d.dataset.open === "1";
  if (btn) btn.textContent = open ? uiText("deck_collapse") : uiText("deck_expand", n);
  if (posEl) {
    posEl.style.display = open ? "none" : "";
    posEl.textContent = uiText("deck_pos", (Number(d.dataset.pos) || 0) + 1, n);
  }
  if (!n || !stage) return;
  if (open) {
    stage.style.height = "";
    cards.forEach((c) => {
      c.style.removeProperty("--pos"); c.style.removeProperty("transform");
      delete c.dataset.far; delete c.dataset.front;
    });
    return;
  }
  // 卡片数可能在上一轮渲染后变了：位置先夹到合法范围再写回，否则会停在一张不存在的牌上
  const front = Math.min(Math.max(Number(d.dataset.pos) || 0, 0), n - 1);
  d.dataset.pos = String(front);
  const vis = Math.min(n, 4);
  const m = deckMetrics(d);
  const h = cards[front].offsetHeight;   // 先量高度，再写位移：少一次强制重排
  cards.forEach((c, i) => {
    const p = (i - front + n) % n;
    const far = p >= vis;
    c.style.setProperty("--pos", String(far ? 0 : p));
    c.style.transform = far ? "" : "translate3d(" + (p * m.ox) + "px," + (p * m.oy) + "px,0)";
    if (far) c.dataset.far = "1"; else delete c.dataset.far;
    if (p === 0) c.dataset.front = "1"; else delete c.dataset.front;
  });
  stage.style.height = (h + m.oy * (vis - 1)) + "px";
}

function mountDecks() {
  document.querySelectorAll("#view-body [data-deck]").forEach(deckLayout);
}

document.addEventListener("pointerdown", (e) => {
  if (e.button > 0) return;
  // 上一次手势没收到 pointerup（切后台/被系统吞）会把状态卡在 drag/press，这里就地清掉
  if ((UIS.state === "drag" || UIS.state === "press") && !DECK_DRAG) uiTo("idle", "deck:orphan");
  if (UIS.state !== "idle" && UIS.state !== "swallow") return;   // 动作在飞 / 弹窗开着，手势不接管
  const stage = e.target.closest && e.target.closest(".deck-stage");
  const d = stage && stage.closest("[data-deck]");
  if (!d || d.dataset.open === "1") return;
  if (e.target.closest("button")) return;
  DECK_DRAG = { d, id: e.pointerId, x: e.clientX, y: e.clientY, dx: 0, moved: false, cards: deckCards(d) };
  uiTo("press", "deck:touch");
});
/* 一帧只写一次 transform：触屏的 pointermove 可能比屏幕帧率还密，
   每次都写会让浏览器白算样式；攒到 rAF 里一起写，草稿留在 g.pending。 */
function deckPaint(g) {
  g.raf = 0;
  const front = g.cards[Number(g.d.dataset.pos) || 0];
  if (front) front.style.transform = "translate3d(" + g.dx + "px,0,0)";
}
document.addEventListener("pointermove", (e) => {
  const g = DECK_DRAG;
  if (!g || e.pointerId !== g.id) return;
  const dx = e.clientX - g.x, dy = e.clientY - g.y;
  if (!g.moved) {
    if (Math.abs(dx) < 10 && Math.abs(dy) < 10) return;      // 还没动够阈值，方向未知
    if (Math.abs(dx) <= Math.abs(dy)) {                       // 纵向：这手势归页面滚动
      DECK_DRAG = null;
      uiTo("scroll", "deck:vertical");
      uiTo("idle", "deck:scroll-handoff");
      return;
    }
    g.moved = true;
    uiTo("drag", "deck:horizontal");
    g.d.dataset.dragging = "1";
    const front0 = g.cards[Number(g.d.dataset.pos) || 0];
    if (front0) front0.style.transition = "none";
  }
  g.dx = dx;
  if (!g.raf) g.raf = requestAnimationFrame(() => deckPaint(g));
  if (e.cancelable) e.preventDefault();
}, { passive: false });
function deckRelease(e) {
  const g = DECK_DRAG;
  if (!g) return;
  DECK_DRAG = null;
  if (g.raf) { cancelAnimationFrame(g.raf); g.raf = 0; }
  delete g.d.dataset.dragging;
  const front = g.cards[Number(g.d.dataset.pos) || 0];
  if (front) front.style.removeProperty("transition");
  const live = deckCards(g.d);
  if (g.moved && live.length === g.cards.length && Math.abs(g.dx) >= 56) {
    const n = live.length, cur = Number(g.d.dataset.pos) || 0;
    g.d.dataset.pos = String(((g.dx < 0 ? cur + 1 : cur - 1) + n) % n);
  }
  if (g.moved) {   // 拖动后紧跟的那一下 click 属于松手，不算点击
    if (UIS.state === "drag") uiTo("swallow", "deck:release");
    UIS.swallowUntil = performance.now() + 600;
  } else {
    // 只是按住没滑：press 直接回 idle
    if (UIS.state === "press") uiTo("idle", "deck:release");
  }
  deckLayout(g.d);
}
document.addEventListener("pointerup", deckRelease);
document.addEventListener("pointercancel", deckRelease);
window.addEventListener("resize", mountDecks);

/* ---- 性能自检浮层（?perf=1 或 localStorage.ai_new_perf=1）----
   只报数，不改行为：帧率、最差一帧、50ms 以上长任务数量，方便在真机上定位卡顿。 */
function startPerfProbe() {
  // 登录跳转会丢掉 query：开过一次就记住，?perf=0 关掉
  const ask = new URLSearchParams(location.search).get("perf");
  try {
    if (ask === "1") localStorage.setItem("ai_new_perf", "1");
    else if (ask === "0") localStorage.removeItem("ai_new_perf");
    if (localStorage.getItem("ai_new_perf") !== "1") return;
  } catch (err) { if (ask !== "1") return; }
  const box = document.createElement("div");
  box.className = "perf-probe";
  document.body.appendChild(box);
  let frames = 0, from = performance.now(), worst = 0, last = from, longs = 0;
  try {
    new PerformanceObserver((list) => { longs += list.getEntries().length; })
      .observe({ entryTypes: ["longtask"] });
  } catch (err) { /* 浏览器不支持就只报帧率 */ }
  const tick = (t) => {
    if (t - last > worst) worst = t - last;
    last = t; frames += 1;
    if (t - from >= 500) {
      const fps = Math.round(frames * 1000 / (t - from));
      box.textContent = uiText("perf_probe", fps, Math.round(worst), longs);
      frames = 0; worst = 0; from = t;
    }
    requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
}

function navTarget(view) {
  return viewSpec(view).nav || view;
}
/* 导航完全由后端菜单渲染：手机只用抽屉里的侧栏，页面底部不再常驻底栏。
   加一个视图 = 视图规格里多一行 menu，这里零改动。 */
function renderMenus(menus) {
  const side = $("side-nav");
  if (!side) return;
  // 同组相邻：组内按后端 order 排，组间留一道分隔，跟 App 的分区一致
  const groups = [];
  arr(menus).forEach((m) => {
    const name = m.group || "";
    const last = groups[groups.length - 1];
    if (last && last.name === name) last.items.push(m);
    else groups.push({ name, items: [m] });
  });
  side.innerHTML = groups.map((g) => `<div class="nav-group">${
    g.name ? `<div class="nav-group-title">${esc(g.name)}</div>` : ""}${
    g.items.map((m) => `<button data-clk="nav" data-nav="${esc(m.key)}">${esc(m.label || m.key)}</button>`).join("")
  }</div>`).join("");
}
function highlightNav() {
  const cur = navTarget(state.view);
  document.querySelectorAll("[data-nav]").forEach((b) =>
    b.classList.toggle("on", b.dataset.nav === cur));
}
function openDrawer() {
  $("drawer").classList.add("open");
  $("scrim").classList.add("open");
}
function closeDrawer() {
  $("drawer").classList.remove("open");
  $("scrim").classList.remove("open");
}
/* 桌面侧栏收起：记忆偏好；手机不受影响（样式只作用于宽屏） */
function setRail(on) {
  $("drawer").classList.toggle("collapsed", on);
  document.body.classList.toggle("rail", on);
  try { localStorage.setItem("hive.rail", on ? "1" : "0"); } catch (e) {}
  closeMemberCard();
}
/* 壳层的四个静态按钮不单独绑 onclick：走同一条 [data-clk] 入口，才有门禁与迁移记录 */
try { if (localStorage.getItem("hive.rail") === "1") setRail(true); } catch (e) {}

/* ---- 成员卡浮层：点头像弹显示岗位职责 ---- */
function closeMemberCard() {
  const pop = $("popover");
  if (pop) { pop.hidden = true; pop.innerHTML = ""; }
}
function machineHtml(m) {
  const mc = (m || {}).machine || {};
  const states = mc.states || [];
  if (!states.length) return "";
  const active = mc.active || [];
  const chain = states.map((st) => {
    const cls = [st.id === mc.stage ? "cur" : "", active.indexOf(st.id) >= 0 ? "on" : "", st.terminal ? "term" : ""]
      .filter(Boolean).join(" ");
    return `<span class="st-pill ${cls}" title="${esc(st.desc || st.id)}">${esc(st.cn || st.id)}</span>`;
  }).join(`<span class="st-arrow">→</span>`);
  const cur = states.find((st) => st.id === mc.stage) || {};
  const acts = active.filter((id) => id !== mc.stage)
    .map((id) => (states.find((st) => st.id === id) || {}).cn || id);
  return `<div class="p-row"><span>${esc(uiText("role_flow"))}</span><div>
    <div class="p-flow">${esc((mc.flow || {}).cn || (mc.flow || {}).id || "—")}</div>
    <div class="st-chain">${chain}</div>
    <div class="p-flow">${esc(uiText("role_current"))} ${esc(cur.cn || mc.stage || "—")}${acts.length ? " · " + esc(uiText("role_active")) + " " + esc(acts.join("/")) : ""}</div>
  </div></div>`;
}

function openMemberCard(el) {
  const pop = $("popover");
  const m = (window.RENDER_MEMBERS || [])[Number(el.dataset.member)];
  if (!pop || !m) return;
  pop.innerHTML = `<h4><span class="avatar" style="--av:${avatarColor(m.display || m.role)}">${initial(m.display || m.role)}</span>${esc(m.display || m.role)}</h4>
    <div class="p-role">${esc(m.role || "")} · ${statusText(m.status)}</div>
    ${machineHtml(m)}
    ${(m.todos || {}).total ? `<div class="p-row"><span>${esc(uiText("role_todo"))}</span><div>${(m.todos || {}).done}/${(m.todos || {}).total}${(m.todos || {}).current ? " · " + esc((m.todos || {}).current) : ""}</div></div>` : ""}
    ${m.task ? `<div class="p-row"><span>${esc(uiText("role_task"))}</span><div>${esc(m.task)}</div></div>` : ""}
    ${m.session ? `<div class="p-row"><span>${esc(uiText("role_session"))}</span><div>${esc(m.session)}</div></div>` : ""}`;
  pop.hidden = false;
  const r = el.getBoundingClientRect();
  const w = pop.offsetWidth, h = pop.offsetHeight;
  let left = Math.min(Math.max(8, r.right - w), window.innerWidth - w - 8);
  let top = r.bottom + 8;
  if (top + h > window.innerHeight - 8) top = Math.max(8, r.top - h - 8);
  pop.style.left = left + "px";
  pop.style.top = top + "px";
}
$("logout").onclick = async () => {
  try { await run("auth-logout", { token: token() }); } catch (e) {}
  clearToken(); location.href = "/login.html";
};
window.addEventListener("popstate", () => {
  stashPage();     // 先把当前页滚到哪记下来
  state = parseURL();
  // 返回上一页优先接管保活实例：不重建 DOM、不重新取数、滚动位置原样
  const kept = PAGE_KEEP.get(keepKey(state));
  if (kept && !kept.stale) { restorePage(kept); return; }
  render().catch((err) => banner(gateMessage(err), "err"));
});

startPerfProbe();
boot().catch((err) => banner(uiText("boot_fail", gateMessage(err)) || ("控制台启动失败：" + gateMessage(err)), "err"));
