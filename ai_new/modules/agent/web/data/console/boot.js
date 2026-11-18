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
  if (navEl) return go({ view: navEl.dataset.nav }, true);
  if (e.target.closest("[data-crumb]")) return go(crumbUp(), true);
});
document.addEventListener("keydown", (e) => {
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
$("logout").onclick = async () => {
  try { await run("auth-logout", { token: token() }); } catch (e) {}
  clearToken(); location.href = "/login.html";
};
window.addEventListener("popstate", () => {
  state = parseURL();
  render().catch((err) => banner(gateMessage(err), "err"));
});

boot().catch((err) => banner("控制台启动失败：" + gateMessage(err) + "（检查 views-list 与视图规格）", "err"));
