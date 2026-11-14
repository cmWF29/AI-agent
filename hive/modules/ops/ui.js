// ---------------- 固定命令 ----------------
function restartAgent() {
  if (!confirm('重启 agent 进程？（watchdog 会立刻拉起）')) return;
  api('/api/ops/restart', { method: 'POST', body: {} }).then(function () { toast('重启指令已下发'); }).catch(function (e) { toast(e.message, 'err'); });
}
function stopAll() {
  if (!confirm('彻底停止 watchdog + agent？\n之后只能通过 SSH 手动起。')) return;
  api('/api/ops/stop', { method: 'POST', body: {} }).then(function () { toast('停止指令已下发'); }).catch(function (e) { toast(e.message, 'err'); });
}


// ---------------- 运维模块自己的事件绑定 ----------------
$('btn-restart').onclick = restartAgent;
$('btn-stop').onclick = stopAll;

HiveUI.on('panel:open', function (p) { if (p && p.name === 'versions') openVersions(); });
