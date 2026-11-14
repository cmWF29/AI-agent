// ---------------- 轮询 ----------------
function startPolling() {
  clearInterval(state.pollTimer); clearInterval(state.liveTimer);
  state.pollTimer = setInterval(function () {
    if (state.view === 'chat') loadTimeline(true);
    if (document.visibilityState === 'visible') { loadGroups(false); loadIdle(); }
  }, 5000);
  state.liveTimer = setInterval(function () {
    if (document.visibilityState === 'visible' && state.view === 'chat') loadLive();
  }, 900);
}

// ---------------- 事件 ----------------
$('login-btn').onclick = doLogin;
$('password').addEventListener('keydown', function (e) { if (e.key === 'Enter') doLogin(); });
$('send').onclick = send;
$('input').addEventListener('keydown', function (e) { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); } });
$('input').addEventListener('input', function () { this.style.height = 'auto'; this.style.height = Math.min(140, this.scrollHeight) + 'px'; });
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
$('btn-files').onclick = openSide;
$('side-close').onclick = function () { hide('side'); updateBackBtn(); };
$('modal-close').onclick = function () { closeModal(); };
$('btn-addtag').onclick = addTag;
$('btn-fork-ticket').onclick = function () { openFork('基于 ' + state.group + ' 的后续修改：', state.group); };
$('btn-copy-ticket').onclick = function () {
  var id = state.group, done = function () { toast('已复制 ' + id); };
  if (navigator.clipboard) navigator.clipboard.writeText(id).then(done).catch(function () { prompt('复制工单号', id); });
  else prompt('复制工单号', id);
};
$('btn-refresh').onclick = function () { state.seen = {}; $('messages').innerHTML = ''; loadTimeline(); loadLive(); if (state.group.indexOf('T-') === 0) loadFlow(); };
$('btn-restart').onclick = restartAgent;
$('btn-stop').onclick = stopAll;
$('btn-newproject').onclick = createProject;
$('pv-rename').onclick = renameProject;
$('pv-files').onclick = function () { openProjectFiles(); };
$('pv-source').onclick = function () { openProjectSource(); };
$('pv-bindsource').onclick = bindProjectSource;
$('pv-savebackend').onclick = saveProjectBackend;
$('pv-apiconfig').onclick = openApiConfig;
$('pv-idle').onclick = openIdle;
$('pv-saveidle').onclick = saveProjectIdle;
$('pv-delete').onclick = deleteProject;
$('pv-secretary').onclick = function () { selectGroup('sec-' + state.project); };
$('pv-compact').onclick = compactProjectSecretary;
$('pv-create').onclick = createTicket;
$('pv-artifacts').onclick = function () { state.sideLayer = 'project'; show('side'); loadFiles(); updateBackBtn(); };
document.querySelectorAll('.tab').forEach(function (b) {
  b.onclick = function () {
    var tab = b.dataset.tab;
    setTab(tab);
    if (tab === 'library') openLibrary('roles');
    else if (tab === 'health') openHealth();
    else if (tab === 'versions') openVersions();
  };
});
document.querySelectorAll('#side .stab').forEach(function (b) { b.onclick = function () { openSide(); }; });
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
