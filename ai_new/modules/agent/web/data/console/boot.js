/* boot：事件总线与启动
   只有一条：点到的按钮 -> 动作表 -> 执行器。
*/
document.addEventListener("click", (e) => {
  // 刚刚是滑动换牌，不是点卡片：吃掉这一次点击
  if (DECK_SUPPRESS) { DECK_SUPPRESS = false; e.stopPropagation(); e.preventDefault(); return; }
  const deckBtn = e.target.closest("[data-deck-open]");
  if (deckBtn) {
    const d = deckBtn.closest("[data-deck]");
    d.dataset.open = d.dataset.open === "1" ? "0" : "1";
    deckLayout(d);
    return;
  }
  const btn = e.target.closest("[data-act]");
  if (btn && !btn.disabled) {
    const binding = ACTS[Number(btn.dataset.act)];
    if (!binding) return;
    if (binding.voice) return executeVoice(binding, btn);
    if (binding.composer && !binding.act.modal) {
      const box = $("view-body").querySelector(".composer textarea");
      const text = (box && box.value || "").trim();
      if (!text) {
        banner(uiText("composer_empty") || binding.act.empty_hint || "请先输入内容", "err");
        return;
      }
      return execute(binding, { text });
    }
    return execute(binding, {});
  }
  const filterBtn = e.target.closest("[data-filter]");
  if (filterBtn) { FILTER = filterBtn.dataset.filter; return render(); }
  const goEl = e.target.closest("[data-go]");
  if (goEl) {
    const binding = ACTS[Number(goEl.dataset.go)];
    if (binding) return execute(binding, {});
  }
  const navEl = e.target.closest("[data-nav]");
  if (navEl) { closeDrawer(); return go({ view: navEl.dataset.nav }, true); }
  if (e.target.closest("[data-crumb]")) return go(crumbUp(), true);
  const memberEl = e.target.closest("[data-member]");
  if (memberEl) {
    e.stopPropagation();
    if ($("popover").hidden) return openMemberCard(memberEl);
    return closeMemberCard();
  }
  const foldEl = e.target.closest("[data-expand]");
  if (foldEl) {
    const folded = foldEl.classList.toggle("clamp");
    const t = foldEl.querySelector(".ev-text");
    if (t) t.textContent = folded ? (foldEl.dataset.short || "") : (foldEl.dataset.full || "");
    return;
  }
  if (!e.target.closest("#popover")) closeMemberCard();
});
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
let DECK_SUPPRESS = false;   // 拖动结束的那一下点击不算点击
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
  const front = Number(d.dataset.pos) || 0;
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
  if (DECK_SUPPRESS || e.button > 0) return;
  const stage = e.target.closest && e.target.closest(".deck-stage");
  const d = stage && stage.closest("[data-deck]");
  if (!d || d.dataset.open === "1") return;
  if (e.target.closest("button")) return;
  DECK_DRAG = { d, id: e.pointerId, x: e.clientX, y: e.clientY, dx: 0, moved: false, cards: deckCards(d) };
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
    if (Math.abs(dx) < 10) return;
    if (Math.abs(dx) <= Math.abs(dy)) { DECK_DRAG = null; return; }  // 纵向手势还给页面滚动
    g.moved = true;
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
  if (g.moved && Math.abs(g.dx) >= 56) {
    const n = g.cards.length, cur = Number(g.d.dataset.pos) || 0;
    g.d.dataset.pos = String(((g.dx < 0 ? cur + 1 : cur - 1) + n) % n);
  }
  DECK_SUPPRESS = !!g.moved;
  deckLayout(g.d);
}
document.addEventListener("pointerup", deckRelease);
document.addEventListener("pointercancel", deckRelease);
window.addEventListener("resize", mountDecks);

/* ---- 性能自检浮层（?perf=1 或 localStorage.ai_new_perf=1）----
   只报数，不改行为：帧率、最差一帧、50ms 以上长任务数量，方便在真机上定位卡顿。 */
function startPerfProbe() {
  if (!(new URLSearchParams(location.search).get("perf") === "1"
      || localStorage.getItem("ai_new_perf") === "1")) return;
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
  if (side) {
    side.innerHTML = arr(menus).map((m) =>
      `<button data-nav="${esc(m.key)}">${esc(m.label || m.key)}</button>`).join("");
  }
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
$("menu-btn").onclick = openDrawer;
$("scrim").onclick = closeDrawer;
$("side-collapse").onclick = () => setRail(true);
$("rail-open").onclick = () => setRail(false);
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
  state = parseURL();
  render().catch((err) => banner(gateMessage(err), "err"));
});

startPerfProbe();
boot().catch((err) => banner(uiText("boot_fail", gateMessage(err)) || ("控制台启动失败：" + gateMessage(err)), "err"));
