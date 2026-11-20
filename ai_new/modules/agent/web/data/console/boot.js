/* boot：事件总线与启动
   只有一条：点到的按钮 -> 动作表 -> 执行器。
*/
document.addEventListener("click", (e) => {
  const btn = e.target.closest("[data-act]");
  if (btn && !btn.disabled) {
    const binding = ACTS[Number(btn.dataset.act)];
    if (!binding) return;
    if (binding.voice) return executeVoice(binding, btn);
    if (binding.composer && !binding.act.modal) {
      const box = $("view-body").querySelector(".composer textarea");
      const text = (box && box.value || "").trim();
      if (!text) {
        banner(binding.act.empty_hint || "请先输入内容，再点这个按钮", "err");
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

function navTarget(view) {
  if (view === "project" || view === "ticket") return "projects";
  if (view === "position") return "positions";
  if (view === "knowledge-doc") return "knowledge";
  return view;
}
function highlightNav() {
  const cur = navTarget(state.view);
  document.querySelectorAll("#side-nav [data-nav]").forEach((b) =>
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
  const acts = active.map((id) => (states.find((st) => st.id === id) || {}).cn || id);
  return `<div class="p-row"><span>流程</span><div>
    <div class="p-flow">${esc((mc.flow || {}).cn || (mc.flow || {}).id || "—")}</div>
    <div class="st-chain">${chain}</div>
    <div class="p-flow">当前 ${esc(cur.cn || mc.stage || "—")}${acts.length ? " · 活跃 " + esc(acts.join("/")) : ""}</div>
  </div></div>`;
}

function openMemberCard(el) {
  const pop = $("popover");
  const m = (window.RENDER_MEMBERS || [])[Number(el.dataset.member)];
  if (!pop || !m) return;
  pop.innerHTML = `<h4><span class="avatar" style="--av:${avatarColor(m.display || m.role)}">${initial(m.display || m.role)}</span>${esc(m.display || m.role)}</h4>
    <div class="p-role">${esc(m.role || "")} · ${statusText(m.status)}</div>
    ${machineHtml(m)}
    ${(m.todos || {}).total ? `<div class="p-row"><span>待办</span><div>${(m.todos || {}).done}/${(m.todos || {}).total}${(m.todos || {}).current ? " · " + esc((m.todos || {}).current) : ""}</div></div>` : ""}
    ${m.task ? `<div class="p-row"><span>任务</span><div>${esc(m.task)}</div></div>` : ""}
    ${m.session ? `<div class="p-row"><span>会话</span><div>${esc(m.session)}</div></div>` : ""}`;
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

boot().catch((err) => banner("控制台启动失败：" + gateMessage(err) + "（检查 views-list 与视图规格）", "err"));
