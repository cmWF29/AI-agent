// ---------------- 固定命令 ----------------
function restartAgent() {
  if (!confirm('重启 agent 进程？（watchdog 会立刻拉起）')) return;
  api('/api/ops/restart', { method: 'POST', body: {} }).then(function () { toast('重启指令已下发'); }).catch(function (e) { toast(e.message, 'err'); });
}
function stopAll() {
  if (!confirm('彻底停止 watchdog + agent？\n之后只能通过 SSH 手动起。')) return;
  api('/api/ops/stop', { method: 'POST', body: {} }).then(function () { toast('停止指令已下发'); }).catch(function (e) { toast(e.message, 'err'); });
}
function openVersions(opts) {
  opts = opts || {};
  openModal('版本管理', '<div id="vbody" class="muted">读取中…</div>', { root: true });
  if (!opts.fromRoute) overlayRoute('#/versions', 'versions');
  api('/api/ops/versions').then(function (v) {
    var g = v.git || {};
    if (!g.available) { $('vbody').innerHTML = '<div class="muted">部署目录不是 git 仓库。</div>'; return; }
    $('vbody').innerHTML = '<div class="muted small">当前 ' + esc(v.version || '') + ' · HEAD ' + esc(g.head || '') +
      (g.dirty ? ' · 工作区有改动' : '') + '</div><div class="commitlist">' +
      (g.commits || []).map(function (c) {
        return '<div class="commit ' + (c.current ? 'cur' : '') + '"><div class="grow"><div><code>' + esc(c.short) + '</code> ' + esc(c.subject || '') +
          '</div><div class="muted small">' + esc(c.date || '') + (c.current ? ' · 当前运行' : '') + '</div></div>' +
          (c.current ? '' : '<button class="mini" data-t="' + esc(c.short) + '">回退</button>') + '</div>';
      }).join('') + '</div>';
    $('vbody').querySelectorAll('button[data-t]').forEach(function (b) { b.onclick = function () { rollback(b.dataset.t); }; });
  }).catch(function (e) { $('vbody').innerHTML = '<div class="err">' + esc(e.message) + '</div>'; });
}
function rollback(t) {
  if (!confirm('回退到 ' + t + '？\nwatchdog 会先建 autosave 分支保住当前代码，再切过去重启。')) return;
  api('/api/ops/rollback', { method: 'POST', body: { target: t } }).then(function () { toast('已下发回退指令'); })
    .catch(function (e) { toast('回退失败：' + e.message, 'err'); });
}


// ---------------- 运维模块自己的事件绑定 ----------------
$('btn-restart').onclick = restartAgent;
$('btn-stop').onclick = stopAll;

HiveUI.on('panel:open', function (p) { if (p && p.name === 'versions') openVersions(p.opts); });
