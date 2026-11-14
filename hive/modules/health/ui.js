var HEALTH_LABELS = {
  data_writable: '数据目录可写', modules_loaded: '模块齐全', bus: '事件总线可用',
  disk_free: '磁盘余量', artifacts_size: '交付件体积', artifacts_disk_headroom: '交付件占用余量',
  trace: '全链路 trace 落盘', llm_key: '大模型 Key', http_traffic: '网页流量'
};
function healthLabel(n) {
  if (HEALTH_LABELS[n]) return HEALTH_LABELS[n];
  if (/^api_/.test(n)) return '接口可用：' + n.slice(4).replace(/_/g, '.');
  return n;
}
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
HiveUI.on('panel:open', function (p) { if (p && p.name === 'health') openHealth(p.opts); });
