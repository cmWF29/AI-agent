// ---------------- 知识库：总结层，和交付件分开 ----------------
// 交付件在 artifacts 侧栏看文件；这里只看“结论/项目地图/约定/踩坑”。
function openKnowledge(opts) {
  opts = opts || {};
  var g = findGroup(state.group) || {};
  var project = opts.project || state.project || g.project || '';
  var ticket = (state.group || '').indexOf('T-') === 0 ? state.group : '';
  var layer = opts.layer || (ticket ? 'ticket' : (project ? 'project' : 'public'));
  var tabs = '<div class="seg">' +
    (ticket ? '<button data-layer="ticket" class="' + (layer === 'ticket' ? 'on' : '') + '">工单知识</button>' : '') +
    (project ? '<button data-layer="project" class="' + (layer === 'project' ? 'on' : '') + '">项目知识</button>' : '') +
    '<button data-layer="public" class="' + (layer === 'public' ? 'on' : '') + '">公共知识</button></div>' +
    '<div class="muted small">知识是总结（结论、地图、约定、踩坑）；交付件是落盘文件。先读知识，再按任务读代码。</div>' +
    '<div id="kn-body" class="muted small" style="margin-top:8px">加载中…</div>' +
    '<div id="kn-view" class="hidden" style="margin-top:10px"></div>';
  openModal('知识库 · ' + (project || '公共'), tabs, { root: true });
  if (!opts.fromRoute) overlayRoute('#/knowledge', 'knowledge');

  function list() {
    var box = $('kn-body'); if (!box) return;
    box.className = 'muted small'; box.innerHTML = '加载中…';
    var q = '?layer=' + layer + '&project=' + encodeURIComponent(project) + '&ticket=' + encodeURIComponent(ticket);
    api('/api/knowledge/list' + q).then(function (r) {
      if (!(r.items || []).length) { box.innerHTML = '<div class="empty">这一层还没有知识文档</div>'; return; }
      box.className = 'filelist';
      box.innerHTML = '<div class="muted small">' + r.items.length + ' 篇 · ' + esc(r.dir) + '</div>' +
        r.items.map(function (it) {
          return '<div class="file-row" data-name="' + esc(it.name) + '"><span class="fname">' + esc(it.name) + '</span>' +
            '<span class="muted small">' + esc(fmtBytes(it.chars)) + ' · ' + esc(it.mtime || '') + '</span></div>';
        }).join('');
      box.querySelectorAll('.file-row').forEach(function (row) {
        row.onclick = function () { read(row.dataset.name); };
      });
    }).catch(function (e) { box.innerHTML = '<div class="err">' + esc(e.message) + '</div>'; });
  }

  function read(name) {
    var q = '?layer=' + layer + '&project=' + encodeURIComponent(project) +
      '&ticket=' + encodeURIComponent(ticket) + '&name=' + encodeURIComponent(name);
    api('/api/knowledge/read' + q).then(function (r) {
      var view = $('kn-view'); if (!view) return;
      view.classList.remove('hidden');
      view.innerHTML = '<h4>' + esc(name) + '</h4>' + md(r.content || '');
    }).catch(function (e) { toast('读取失败：' + e.message, 'err'); });
  }

  document.querySelectorAll('#modal-body .seg button').forEach(function (b) {
    b.onclick = function () {
      layer = b.dataset.layer;
      document.querySelectorAll('#modal-body .seg button').forEach(function (x) {
        x.classList.toggle('on', x.dataset.layer === layer);
      });
      list();
      var view = $('kn-view'); if (view) view.classList.add('hidden');
    };
  });
  list();
}

HiveUI.on('panel:open', function (p) { if (p && p.name === 'knowledge') openKnowledge(p.opts); });
