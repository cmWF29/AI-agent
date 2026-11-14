var HEALTH_LABELS = {
  data_writable: '数据目录可写', modules_loaded: '模块齐全', bus: '事件总线可用',
  disk_free: '磁盘余量', artifacts_size: '交付件体积', artifacts_disk_headroom: '交付件占用余量',
  trace: '全链路 trace 落盘', llm_key: '大模型 Key', http_traffic: '网页流量'
};
var FLOW_STATE_LABELS = { done: '已完成', running: '进行中', idle: '等待中', destroyed: '已结束', gone: '已结束', error: '异常' };
function healthLabel(n) {
  if (HEALTH_LABELS[n]) return HEALTH_LABELS[n];
  if (/^api_/.test(n)) return '接口可用：' + n.slice(4).replace(/_/g, '.');
  return n;
}
function stateLabel(s) { return FLOW_STATE_LABELS[s] || s || ''; }
var STATUS_LABELS = { running: '进行中', queued: '排队中', closing: '结单中', closed: '已结单',
  conflict: '有冲突', working: '处理中', blocked: '被拦下', interrupted: '已中断', error: '异常' };
function statusLabel(s) { return STATUS_LABELS[s] || s || ''; }
function openHealth(opts) {
  opts = opts || {};
  openModal('健康自检', '<div id="hbody" class="muted">检查中…</div>', { root: true });
  if (!opts.fromRoute) overlayRoute('#/health', 'health');
  Promise.all([api('/api/health/self'), api('/api/artifacts/stats'), api('/api/ops/status').catch(function () { return {}; }),
    api('/api/health/logs?limit=80').catch(function () { return {}; }),
    api('/api/health/traffic').catch(function () { return {}; })])
    .then(function (rs) {
      var h = rs[0] || {}, a = rs[1] || {}, s = rs[2] || {}, lg = rs[3] || {}, tr = rs[4] || {};
      var traffic = tr.traffic || h.traffic || {};
      var allLogs = (lg.items || []).concat(lg.bus_items || []).sort(function (a, b) {
        return (a.t || 0) - (b.t || 0);
      }).slice(-100);
      var logs = allLogs.map(function (x) {
        return '<div class="logrow"><span class="muted small">' + esc(x.ts || '') + '</span>' +
          '<span class="loglv ' + esc(x.level || '') + '">' + esc(x.level || 'info') + '</span>' +
          '<span class="grow">' + esc(x.event || x.msg || x.message || '') + '</span></div>';
      }).join('') || '<div class="empty">暂无日志</div>';
      var checks = (h.checks || []).map(function (c) {
        return '<div class="check ' + (c.ok ? 'ok' : 'bad') + '"><span class="dot"></span><div><div>' + esc(healthLabel(c.name)) +
          '</div><div class="muted small">' + esc(c.detail || '') + '</div></div></div>';
      }).join('');
      var big = (a.biggest || []).slice(0, 8).map(function (b) {
        return '<div class="file-row"><span>' + esc(b.project + '/' + b.ticket) + (b.compressed ? ' (已压缩)' : '') +
          '</span><span class="muted small">' + fmtBytes(b.bytes) + '</span></div>';
      }).join('');
      $('hbody').innerHTML =
        '<div class="health-top"><span class="pill ' + (h.healthy ? 'good' : 'bad') + '">' + (h.healthy ? '健康' : '有异常') + '</span>' +
        '<span class="muted small">v' + esc(h.version || '') + ' · TLS ' + (h.tls ? 'on' : 'off') + ' · uptime ' + (h.uptime_sec || 0) + 's</span></div>' +
        '<div class="checks">' + checks + '</div>' +
        '<h4>网页流量</h4><div class="traffic">' +
        '<span>请求 <b>' + (traffic.requests || 0) + '</b></span><span>API <b>' + (traffic.api_requests || 0) + '</b></span>' +
        '<span>静态 <b>' + (traffic.static_requests || 0) + '</b></span><span>收 <b>' + fmtBytes(traffic.bytes_in || 0) + '</b></span>' +
        '<span>发 <b>' + fmtBytes(traffic.bytes_out || 0) + '</b></span></div>' +
        '<h4>交付件体积（含所有层）</h4><div class="muted small">合计 ' + fmtBytes(a.total_bytes) + ' · 磁盘余量 ' + fmtBytes(a.disk_free) + '</div>' +
        '<div class="filelist">' + big + '</div>' +
        (a.need_compress ? '<div class="warnbox">交付件偏大，建议压缩归档</div>' : '') +
        '<div class="row-btns"><button class="ghost" id="btn-compress-all">压缩 7 天前工单</button></div>' +
        '<h4>消息链路 / 系统日志</h4><div class="loglist">' + logs + '</div>';
      var cb = $('btn-compress-all');
      if (cb) cb.onclick = function () {
        api('/api/artifacts/compress', { method: 'POST', body: { days: 7 } }).then(function (r) { toast('已压缩 ' + (r.compressed || []).length + ' 个'); openHealth(); })
          .catch(function (e) { toast(e.message, 'err'); });
      };
    }).catch(function (e) { $('hbody').innerHTML = '<div class="err">' + esc(e.message) + '</div>'; });
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

