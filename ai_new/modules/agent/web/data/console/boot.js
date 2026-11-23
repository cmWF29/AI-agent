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
/* 控件级状态机：每个按钮自带 data-ctl，data-ctl-state 走 idle→busy→done→idle。
   页面级 click_machine 管"这一下能不能点"，控件状态管"这个按钮自己现在是什么态"。 */
function ctlMark(el, st) {
  if (el && el.dataset && el.dataset.ctl) el.dataset.ctlState = st;
}
function uiRun(fn, kind, el) {
  if (!uiAllowed(kind)) return null;
  uiEnter(kind);
  ctlMark(el, "busy");
  const done = () => { uiExit(kind); ctlMark(el, "done");
    setTimeout(() => { if (el && el.isConnected) ctlMark(el, "idle"); }, 240); };
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
  // 没声明控件状态机的按钮一律点不动：漏声明本身就是缺陷，不能静默放过
  if (!el.dataset.ctl) { UIS.violations += 1; UIS.lastBad = "no-ctl:" + String(el.dataset.act || ""); return null; }
  const binding = ACTS.get(String(el.dataset.act));
  if (!binding) {   // 绑定表里没有：这次渲染已作废，页面该重取
    UIS.violations += 1; UIS.lastBad = "stale-act:" + el.dataset.act;
    return null;
  }
  if (binding.voice) return uiRun(() => executeVoice(binding, el), kind, el);
  // 打开弹窗不是一次“忙等”动作：openForm 自己把界面切到 modal 态。
  // 若仍套 uiRun，execute 立即返回后 done() 会把状态打回 idle，弹窗里的确定键就全部点不动。
  if (binding.act.modal) return execute(binding, {});
  if (binding.composer) {
    const box = $("view-body").querySelector(".composer textarea");
    const text = (box && box.value || "").trim();
    if (!text) {
      banner(uiText("composer_empty") || binding.act.empty_hint || "请先输入内容", "err");
      return null;
    }
    return uiRun(() => execute(binding, { text }), kind, el);
  }
  return uiRun(() => execute(binding, {}), kind, el);
}
function runGo(el, kind) {
  const binding = ACTS.get(String(el.dataset.go));
  if (!binding) { UIS.violations += 1; UIS.lastBad = "stale-go:" + el.dataset.go; return null; }
  return uiRun(() => execute(binding, {}), kind, el);
}

/* 折叠是用户的意图：展开/收起写进 sessionStorage，重渲染与整页刷新都按原状恢复 */
document.addEventListener("toggle", (e) => {
  const d = e.target;
  if (d && d.dataset && d.dataset.fold && typeof foldSet === "function") foldSet(d.dataset.fold, d.open);
}, true);

const CLICK_HANDLERS = {
  drawer_open() { openDrawer(); },
  nav_group(el) {
    if (el.dataset.navBack) { $("drawer").classList.remove("group-open"); return; }
    NAV_GROUP = el.dataset.group || "";
    $("drawer").classList.add("group-open");
    renderNavPanels();
  },
  tab_config() {
    NAV_CONFIG_OPEN = !NAV_CONFIG_OPEN;
    renderTabConfig(NAV_MENUS);
    $("tab-config-btn").classList.toggle("on", NAV_CONFIG_OPEN);
  },
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
  tree_group(el, e) {
    // summary 的原生默认动作也会翻一次开关：不拦默认就是两次相抵，永远收不回去
    if (e && e.cancelable) e.preventDefault();
    const d = el.closest("details.tree-node");
    if (d) d.open = !d.open;
  },
  tree_doc(el) { return runGo(el, "tree_doc"); },
  filter(el) { FILTER = el.dataset.filter; render(); },
  member_chip(el) { return $("popover").hidden ? openMemberCard(el) : closeMemberCard(); },
  popover_close() { closeMemberCard(); },
  section_fold(el, e) {
    if (e && e.cancelable) e.preventDefault();   // 同 tree_group：拦原生翻转，避免两次相抵
    const d = el.closest("details");
    if (d) d.open = !d.open;
  },
  logout() {
    return uiRun(async () => { try { await run("auth-logout", { token: token() }); } catch (e) {}
      clearToken(); location.href = "/login.html"; }, "logout");
  },
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
  dag_zoom(el) {
    // 缩放只作用于图容器内部：不动整页布局，也不重取数据。
    // graph-wrap 是卡片内与工具栏并列的兄弟节点，从卡片壳里反查容器。
    const card = el.closest(".flow-card");
    const wrap = card && card.querySelector(".graph-wrap");
    if (!wrap || !window.HiveGraph) return;
    const mode = el.dataset.graph || "in";
    if (mode === "fit") HiveGraph.fit(wrap);
    else HiveGraph.zoomBy(wrap, mode);
  },
  /* stack 条目：纯本地展开/收起，折叠态写 sessionStorage（foldSet）；
     不取数、不换页。代表链路 chips 走 stack_link 另一条出口。 */
  stack_open(el, e) {
    if (e && e.cancelable) e.preventDefault();
    const d = el.closest("details.stack-item");
    if (d) d.open = !d.open;
  },
  /* stack 代表链路 chips：点开进链路详情，与卡片跳转同一条出口 */
  stack_link(el) { return runGo(el, "stack_link"); },
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
      const btn = box.querySelector("sl-button.primary, [data-clk='composer_send']");
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
      c.style.removeProperty("--pos"); c.style.removeProperty("transform"); c.style.removeProperty("height");
      delete c.dataset.far; delete c.dataset.front;
    });
    return;
  }
  // 卡片数可能在上一轮渲染后变了：位置先夹到合法范围再写回，否则会停在一张不存在的牌上
  const front = Math.min(Math.max(Number(d.dataset.pos) || 0, 0), n - 1);
  d.dataset.pos = String(front);
  const vis = Math.min(n, 4);
  const m = deckMetrics(d);
  // 每张牌都还带着上一轮写死的 height：直接量量到的是旧前卡的高度，
  // 新前卡比它高就会整段溢出卡外。先全部还原自然高度，量完再统一写回。
  cards.forEach((c) => c.style.removeProperty("height"));
  const h = cards[front].offsetHeight;   // 先量高度，再写位移：少一次强制重排
  // 所有牌统一成前卡的高度：后层内容不画、宽度又少 8px，不管就会比前卡矮一截，
  // 叠起来后完全被前卡盖住，看不出"下面还有牌"
  cards.forEach((c) => { c.style.height = h + "px"; });
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
  if (e.target.closest("button, sl-button")) return;
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
/* 导航完全由后端菜单渲染：桌面侧栏与移动底栏都读同一份 shell.menus。
   侧栏是两级：一级分组（工作/资产/系统）→ 点进去才展开该组的二级页面。
   底栏是用户可配置的快捷入口：只存视图 key 到 localStorage，不复制业务菜单。 */
const TAB_LIMIT = 5;
let NAV_MENUS = [];
let NAV_GROUP = "";
let NAV_CONFIG_OPEN = false;

/* 菜单项 -> 视图规格：按 label 与 parent 对上；侧栏与底栏共用同一份解析 */
function viewByMenuKey(m) {
  for (const k of Object.keys(VIEWS)) {
    const v = VIEWS[k] || {};
    const cfg = v.menu || {};
    const label = cfg.label || v.heading || k;
    if (label === m.label && (cfg.parent || "") === (m.parent || "")) return v;
  }
  return null;
}
function menuNavKey(m) {
  const v = viewByMenuKey(m);
  return (v && v.key) || m.key;
}
function menuGroup(m) { return m.group || ""; }
function navGroupList(menus) {
  const groups = [];
  arr(menus).forEach((m) => {
    const name = menuGroup(m);
    let g = groups.find((x) => x.name === name);
    if (!g) { g = { name, order: Number(m.group_order == null ? 99 : m.group_order), items: [] }; groups.push(g); }
    g.items.push(m);
  });
  groups.sort((a, b) => a.order - b.order || (a.name < b.name ? -1 : 1));
  return groups;
}
function currentViewKey() {
  const q = new URLSearchParams(location.search).get("view");
  const v = q || (typeof state !== "undefined" ? state.view : "");
  return (v && typeof VIEWS !== "undefined" && VIEWS[v]) ? v : "projects";
}
function currentMenu(menus) {
  const cur = currentViewKey();
  const spec = (typeof viewSpec === "function" ? viewSpec(cur) : null) || {};
  const want = spec.nav || spec.key || cur;
  return arr(menus).find((m) => menuNavKey(m) === want || m.key === want) || null;
}
function readTabKeys() {
  try {
    const v = JSON.parse(localStorage.getItem("hive.tabs") || "null");
    if (Array.isArray(v)) return v.map(String).filter(Boolean);
  } catch (e) {}
  return null;
}
function saveTabKeys(keys) {
  try { localStorage.setItem("hive.tabs", JSON.stringify(keys)); } catch (e) {}
}
function defaultTabKeys(menus) {
  const byDecl = arr(menus).filter((m) => Number(m.tab_order) > 0)
    .sort((a, b) => Number(a.tab_order) - Number(b.tab_order) || (a.key < b.key ? -1 : 1))
    .map((m) => m.key);
  if (byDecl.length) return byDecl.slice(0, TAB_LIMIT);
  return arr(menus).filter((m) => m.mobile !== false).slice(0, 3).map((m) => m.key);
}
function activeTabKeys(menus) {
  const pool = arr(menus).filter((m) => m.mobile !== false);
  const saved = readTabKeys();
  if (!saved) return defaultTabKeys(menus);
  const valid = saved.filter((k) => pool.some((m) => m.key === k)).slice(0, TAB_LIMIT);
  return valid.length ? valid : defaultTabKeys(menus);
}
/* 底栏图标：只取 vendored 图标子集；子集没有的用圆形首字块，不引外链/字体 */
const TAB_ICON_BY_KEY = { projects: "folder2", tickets: "send", knowledge: "book", user: "person-circle",
  artifacts: "book", logs: "book", timers: "send", nodes: "folder2", cloud: "book", positions: "person-circle" };
function tabIcon(m) {
  const name = TAB_ICON_BY_KEY[m.key] || "";
  if (name) return `<span class="tab-ico"><sl-icon name="${esc(name)}"></sl-icon></span>`;
  const ch = [...String(m.label || m.key || "?")][0] || "?";
  const ph = /[a-zA-Z]/.test(ch) ? ch.toUpperCase() : ch;
  return `<span class="tab-ico"><span class="ico-ph">${esc(ph)}</span></span>`;
}
function renderTabbar(menus) {
  const bar = $("tabbar");
  if (!bar) return;
  const pool = arr(menus).filter((m) => m.mobile !== false);
  let tabs = activeTabKeys(menus).map((k) => pool.find((m) => m.key === k)).filter(Boolean);
  if (!tabs.length) tabs = defaultTabKeys(menus).map((k) => pool.find((m) => m.key === k)).filter(Boolean);
  const btn = (m) => {
    const navKey = menuNavKey(m);
    const label = m.short || m.label || m.key;
    return `<sl-button class="tab" variant="text" data-clk="nav" data-nav="${esc(navKey)}" data-ctl="ctl.nav.${esc(ctlSlug(label))}" data-ctl-state="idle">${tabIcon(m)}<span class="tab-label">${esc(label)}</span></sl-button>`;
  };
  bar.setAttribute("aria-label", uiText("tabbar") || "");
  bar.innerHTML = tabs.map(btn).join("");
  if (typeof stampCtl === "function") stampCtl(bar);
}
function renderTabConfig(menus) {
  const box = $("tab-config");
  if (!box) return;
  box.hidden = !NAV_CONFIG_OPEN;
  if (box.hidden) return;
  const pool = arr(menus).filter((m) => m.mobile !== false);
  const keys = activeTabKeys(menus);
  box.innerHTML = `<div class="tcfg-head"><b>${esc(uiText("tab_config") || "底栏入口")}</b><span class="muted">${esc(uiText("tab_config_note") || "最多 5 个；侧栏始终保留全部入口")}</span></div>
    <div class="tcfg-list">${pool.map((m) => `<label class="tcfg-row">
      <sl-checkbox data-tab-key="${esc(m.key)}"${keys.indexOf(m.key) >= 0 ? " checked" : ""}>${esc(m.label || m.key)}</sl-checkbox>
      <span class="muted">${esc(m.group || "")}</span></label>`).join("")}</div>`;
  box.querySelectorAll("sl-checkbox").forEach((el) => {
    el.addEventListener("sl-change", () => toggleTab(el.dataset.tabKey, el.checked));
  });
}
function toggleTab(key, on) {
  let keys = activeTabKeys(NAV_MENUS);
  if (on) {
    if (keys.length >= TAB_LIMIT) { banner(uiText("tab_config_full") || "底栏最多 5 个入口", "err"); renderTabConfig(NAV_MENUS); return; }
    if (keys.indexOf(key) < 0) keys = keys.concat([key]);
  } else {
    if (keys.length <= 1) { banner(uiText("tab_config_min") || "底栏至少保留 1 个入口", "err"); renderTabConfig(NAV_MENUS); return; }
    keys = keys.filter((k) => k !== key);
  }
  saveTabKeys(keys);
  renderMenus(NAV_MENUS);
}
function renderMenus(menus) {
  NAV_MENUS = arr(menus);
  renderTabbar(NAV_MENUS);
  renderTabConfig(NAV_MENUS);
  const groups = navGroupList(NAV_MENUS);
  const curMenu = currentMenu(NAV_MENUS);
  if (!NAV_GROUP || !groups.some((g) => g.name === NAV_GROUP)) {
    const g = groups.find((x) => x.items.indexOf(curMenu) >= 0);
    NAV_GROUP = (g && g.name) || (groups[0] || {}).name || "";
  }
  renderNavPanels();
  highlightNav();
}

function renderNavPanels() {
  const side = $("side-nav");
  if (!side) return;
  const groups = navGroupList(NAV_MENUS);
  const groupButton = (g) => {
    const icon = ({ "工作": "folder2", "资产": "book", "系统": "check-lg" })[g.name] || "";
    const ch = [...String(g.name || "?")][0] || "?";
    const ico = icon ? `<sl-icon name="${esc(icon)}"></sl-icon>` : `<span class="ico-ph">${esc(ch)}</span>`;
    return `<sl-button variant="text" class="nav-group-btn${g.name === NAV_GROUP ? " on" : ""}" data-clk="nav_group" data-group="${esc(g.name)}" data-ctl="ctl.nav_group.${esc(ctlSlug(g.name))}" data-ctl-state="idle"><span class="nav-group-ico">${ico}</span><span class="nav-group-label">${esc(g.name)}</span></sl-button>`;
  };
  const navButton = (m) => {
    const navKey = menuNavKey(m);
    return `<sl-button variant="text" class="nav-leaf" data-clk="nav" data-nav="${esc(navKey)}" data-ctl="ctl.nav.${esc(ctlSlug(m.label || m.key))}" data-ctl-state="idle">${esc(m.label || m.key)}</sl-button>`;
  };
  const group = groups.find((g) => g.name === NAV_GROUP) || { name: "", items: [] };
  // 侧栏是完整导航：底栏只是快捷入口，不再把已选进底栏的页面从侧栏抽走。
  const leaves = group.items;
  side.innerHTML = `<div class="nav-primary">${groups.map(groupButton).join("")}</div>
    <div class="nav-secondary">
      <sl-button variant="text" class="nav-back" data-clk="nav_group" data-nav-back="1" data-ctl="ctl.nav_group.返回" data-ctl-state="idle">← ${esc(uiText("nav_all") || "全部分组")}</sl-button>
      <div class="nav-sec-head"><span>${esc(group.name)}</span><em>${leaves.length}</em></div>
      <div class="nav-items">${leaves.length ? leaves.map(navButton).join("") : `<div class="nav-empty">${esc(uiText("nav_all_pinned") || "这一组都已收进底栏，可在「底栏配置」里调整")}</div>`}</div>
    </div>`;
  if (typeof stampCtl === "function") stampCtl(side);
  applyNavGroup();
}

function applyNavGroup() {
  const side = $("side-nav");
  if (!side) return;
  side.querySelectorAll(".nav-group-btn").forEach((b) => b.classList.toggle("on", b.dataset.group === NAV_GROUP));
  const sec = side.querySelector(".nav-sec-head>span");
  if (sec) sec.textContent = NAV_GROUP;
}
function highlightNav() {
  const spec = (typeof viewSpec === "function" ? viewSpec(currentViewKey()) : {}) || {};
  const cur = spec.nav || spec.key || currentViewKey();
  document.querySelectorAll("[data-nav]").forEach((b) =>
    b.classList.toggle("on", b.dataset.nav === cur));
  const curMenu = currentMenu(NAV_MENUS);
  const g = curMenu && curMenu.group;
  // 深链直接打开资产/系统页时，一级分组和二级列表必须一起切过去，不能只换高亮。
  if (g && g !== NAV_GROUP) { NAV_GROUP = g; renderNavPanels(); }
}
function openDrawer() {
  $("drawer").classList.add("open");
  $("scrim").classList.add("open");
}
function closeDrawer() {
  $("drawer").classList.remove("open");
  $("scrim").classList.remove("open");
  $("drawer").classList.remove("group-open");
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
