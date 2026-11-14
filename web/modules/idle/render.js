// ---------------- 空闲判断 ----------------
function loadIdle() {
  var q = state.project ? ('?project=' + encodeURIComponent(state.project)) : '';
  api('/api/idle/status' + q).then(function (r) { state.idle = r; }).catch(function () {});
}
function loadProjectIdle(pid) {
  if (!pid) return;
  api('/api/idle/status?project=' + encodeURIComponent(pid)).then(function (r) {
    var c = r.project_config || r.idle || {};
    state.projectIdle = r;
    if ($('pv-idle-enabled')) $('pv-idle-enabled').checked = !!c.enabled;
    if ($('pv-idle-windows')) $('pv-idle-windows').value = (c.peak_windows || []).join(', ');
    if ($('pv-idle-discount')) $('pv-idle-discount').value = c.offpeak_discount;
    if ($('pv-idle-force')) $('pv-idle-force').checked = !!c.force_peak;
    if ($('pv-idleinfo')) $('pv-idleinfo').textContent = (r.idle && r.idle.peak ? '忙时' : '闲时') +
      ' · 队列 ' + (r.queue || 0) + ' 条 · ' + (r.idle ? r.idle.reason : '');
  }).catch(function () {});
}
function saveProjectIdle() {
  var pid = state.project; if (!pid) return;
  var windows = ($('pv-idle-windows').value || '').split(/[,，\n]+/).map(function (x) { return x.trim(); }).filter(Boolean);
  api('/api/idle/config', { method: 'POST', body: {
    project: pid, enabled: !!$('pv-idle-enabled').checked, peak_windows: windows,
    offpeak_discount: Number($('pv-idle-discount').value || 0.6), force_peak: !!$('pv-idle-force').checked,
  } }).then(function () { toast('本项目忙闲配置已保存'); loadProjectIdle(pid); })
    .catch(function (e) { toast('保存失败：' + e.message, 'err'); });
}
function openIdle() {
  var pid = state.project;
  api('/api/idle/status' + (pid ? ('?project=' + encodeURIComponent(pid)) : '')).then(function (r) {
    var i = r.idle || {};
    var items = (r.queued || []).map(function (q) {
      return '<div class="file-row"><span>' + esc(q.kind) + ' · ' + esc(q.id) + '</span>' +
        '<span class="muted small">' + esc(q.note || '') + '</span></div>';
    }).join('') || '<div class="empty">队列为空</div>';
    openModal('空闲判断 · 本项目队列',
      '<div class="muted small">' + esc((i.reason || '')) + ' · 空闲折扣 ' + (r.discount || '') + ' · 窗口 ' + esc((r.windows || []).join(' / ')) + '</div>' +
      '<div class="filelist">' + items + '</div><div class="row-btns"><button class="primary" id="idle-flush">立即执行本项目队列</button></div>');
    $('idle-flush').onclick = function () {
      api('/api/idle/flush', { method: 'POST', body: { force: true, project: pid } }).then(function (x) {
        toast('已执行 ' + ((x.done || []).length) + ' 条'); closeModal(); loadIdle(); loadProjectIdle(pid); loadGroups();
      }).catch(function (e) { toast(e.message, 'err'); });
    };
  }).catch(function (e) { toast(e.message, 'err'); });
}

