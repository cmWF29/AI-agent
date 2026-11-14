// ---------------- 轮询：宿主只发心跳，各模块自己决定是否刷新 ----------------
function startPolling() {
  clearInterval(state.pollTimer); clearInterval(state.liveTimer);
  state.pollTimer = setInterval(function () {
    HiveUI.emit('app:tick', { visible: document.visibilityState === 'visible' });
  }, 5000);
  state.liveTimer = setInterval(function () {
    HiveUI.emit('app:live', { visible: document.visibilityState === 'visible' });
  }, 900);
}

// ---------------- 事件 ----------------
$('login-btn').onclick = doLogin;
$('password').addEventListener('keydown', function (e) { if (e.key === 'Enter') doLogin(); });
function toggleRail(force) {
  if (window.innerWidth > 900) {
    var hide = force === undefined ? !document.body.classList.contains('rail-collapsed') : !force;
    document.body.classList.toggle('rail-collapsed', hide);
    localStorage.setItem('hive_rail_collapsed', hide ? '1' : '0');
    updateBackBtn();
    return;
  }
  var open = force === undefined ? !$('rail').classList.contains('open') : force;
  $('rail').classList.toggle('open', open);
  $('rail-mask').classList.toggle('show', open);
  updateBackBtn();
}
$('btn-rail').onclick = function () { toggleRail(); };
$('btn-back').onclick = goBack;
$('rail-mask').onclick = function () { toggleRail(false); };
$('side-close').onclick = function () { hide('side'); updateBackBtn(); };
$('modal-close').onclick = function () { closeModal(); };
document.querySelectorAll('.tab').forEach(function (b) {
  b.onclick = function () {
    var tab = b.dataset.tab;
    setTab(tab);
    HiveUI.emit('panel:open', { name: tab });
  };
});
document.querySelectorAll('#side .stab').forEach(function (b) { b.onclick = function () { HiveUI.emit('side:open', {}); }; });
document.addEventListener('keydown', function (e) {
  if (e.key === 'Escape') { goBack(); }
});
window.addEventListener('popstate', function () {
  state.navDepth = Math.max(0, state.navDepth - 1);
  applyRoute(routeOfHash(), { fromRoute: true });
});
// 地址栏直接改 hash / 外部分享链不会触发 popstate；补一个 hashchange，避免旧弹窗盖在新路由上
window.addEventListener('hashchange', function () {
  if (!state.booted) return;
  applyRoute(routeOfHash(), { fromRoute: true });
});

// ---------------- 启动 ----------------
api('/api/auth/status').then(function (r) {
  if (r.scheme === 'https' && location.protocol !== 'https:') $('login-hint').textContent = '服务已启用 HTTPS，建议用 https:// 访问';
  if (r.authed) enterApp(); else showLogin();
}).catch(function () { showLogin(); });
