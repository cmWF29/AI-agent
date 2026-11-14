// ---------------- 侧栏：交付件 ----------------
function openSide() {
  var isTicket = state.view === 'chat' && state.group.indexOf('T-') === 0;
  if (state.view === 'project') state.sideLayer = 'project';
  else if (isTicket && state.sideLayer === 'public') state.sideLayer = 'public';
  else if (isTicket) state.sideLayer = 'ticket';
  else state.sideLayer = (state.group.indexOf('sec-') === 0 && state.project) ? 'project' : 'public';
  show('side'); loadFiles(); updateBackBtn();
}
function loadFiles() {
  var body = $('side-body');
  var isTicket = state.view === 'chat' && state.group.indexOf('T-') === 0;
  var g = findGroup(state.group) || {};
  var project = state.view === 'project' ? state.project
    : (g.project || (state.group.indexOf('sec-') === 0 ? state.group.slice(4) : ''));
  if (!isTicket && state.sideLayer === 'ticket') state.sideLayer = project ? 'project' : 'public';
  if (!project && state.sideLayer === 'project') state.sideLayer = 'public';
  var tabs = '<div class="seg">' +
    (isTicket ? '<button data-layer="ticket" class="' + (state.sideLayer === 'ticket' ? 'on' : '') + '">工单层</button>' : '') +
    (project ? '<button data-layer="project" class="' + (state.sideLayer === 'project' ? 'on' : '') + '">项目层</button>' : '') +
    '<button data-layer="public" class="' + (state.sideLayer === 'public' ? 'on' : '') + '">公共层</button></div>' +
    '<div id="filelist" class="filelist muted small">加载中…</div>';
  body.innerHTML = tabs;
  body.querySelectorAll('.seg button').forEach(function (b) {
    b.onclick = function () { state.sideLayer = b.dataset.layer; loadFiles(); };
  });
  var q = '?layer=' + state.sideLayer + '&project=' + encodeURIComponent(project) +
    '&ticket=' + encodeURIComponent(isTicket ? state.group : '');
  api('/api/artifacts/list' + q).then(function (r) {
    var box = $('filelist');
    if (!(r.items || []).length) { box.className = 'filelist muted small'; box.innerHTML = '<div class="empty">这一层还没有交付件</div>'; return; }
    box.className = 'filelist';
    box.innerHTML = '<div class="muted small">共 ' + r.items.length + ' 个 · ' + fmtBytes(r.bytes) + '</div>' +
      r.items.map(function (f) {
        return '<div class="file-row" data-path="' + esc(f.path) + '"><span class="fname">' + esc(f.path) + '</span>' +
          '<span class="muted small">' + fmtBytes(f.size) + '</span></div>';
      }).join('');
    box.querySelectorAll('.file-row').forEach(function (row) {
      row.onclick = function () { openArtifact(row.dataset.path, project, isTicket, state.sideLayer); };
    });
  }).catch(function (e) { body.innerHTML = '<div class="err">' + esc(e.message) + '</div>'; });
}
function openArtifact(path, project, isTicket, layer) {
  layer = layer || state.sideLayer || 'ticket';
  var ticket = isTicket ? state.group : '';
  var q = '/api/artifacts/file?layer=' + encodeURIComponent(layer) + '&project=' + encodeURIComponent(project) +
    '&ticket=' + encodeURIComponent(ticket) + '&path=' + encodeURIComponent(path);
  api(q).then(function (f) {
    var mime = (/^data:image\/\w+/.test('') ? '' : '') || '';
    var ext = (path.split('.').pop() || '').toLowerCase();
    var isImg = f.encoding === 'base64' && ['png','jpg','jpeg','gif','webp','svg','bmp'].indexOf(ext) >= 0;
    var body;
    if (isImg) {
      var mt = ext === 'svg' ? 'image/svg+xml' : 'image/' + (ext === 'jpg' ? 'jpeg' : ext);
      body = '<div class="artifact-imgwrap"><img class="artifact-img" alt="' + esc(path) + '" src="data:' + mt + ';base64,' + f.text + '"></div>';
    } else if (f.encoding === 'utf-8') {
      body = md(f.text);
    } else {
      body = '<div class="muted">二进制文件（' + esc(fmtBytes(f.size || 0)) + '）</div>';
    }
    body += '<div class="row-btns" style="justify-content:flex-start;margin-top:10px">' +
      '<button class="primary" id="art-download">下载 ' + esc(path.split('/').pop()) + '</button>' +
      '<span class="muted small">layer=' + esc(layer) + ' · ' + esc(fmtBytes(f.size || 0)) + '</span></div>';
    openModal(path, body);
    var btn = $('art-download');
    if (btn) btn.onclick = function () {
      var blob;
      if (f.encoding === 'base64') {
        var raw = atob(f.text || ''), arr = new Uint8Array(raw.length);
        for (var i = 0; i < raw.length; i++) arr[i] = raw.charCodeAt(i);
        blob = new Blob([arr], { type: 'application/octet-stream' });
      } else {
        blob = new Blob([f.text || ''], { type: 'text/plain;charset=utf-8' });
      }
      var url = URL.createObjectURL(blob);
      var a = document.createElement('a'); a.href = url; a.download = path.split('/').pop(); document.body.appendChild(a); a.click(); a.remove();
      setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
    };
  }).catch(function (e) { toast('打不开：' + e.message, 'err'); });
}

// ---------------- 文件浏览 ----------------
function openProjectSource(path) {
  var pid = state.project; if (!pid) return;
  openModal('项目源码 · ' + pid, '<div id="stree" class="muted">加载中…</div>', { root: true });
  browseProjectSource(path || '', pid);
}
function browseProjectSource(path, pid) {
  api('/api/projects/' + encodeURIComponent(pid) + '/source/files?path=' + encodeURIComponent(path)).then(function (r) {
    var box = $('stree'); if (!box) return;
    var up = path ? '<div class="file-row" data-up="1"><span>..</span></div>' : '';
    box.innerHTML = '<div class="muted small">' + esc(r.root || '') + ' / ' + esc(path || '') + '</div>' + up +
      (r.items || []).map(function (f) {
        return '<div class="file-row" data-p="' + esc(f.path) + '" data-t="' + f.type + '">' +
          '<span>' + (f.type === 'dir' ? '📁 ' : '📄 ') + esc(f.name) + '</span>' +
          '<span class="muted small">' + (f.type === 'file' ? fmtBytes(f.size) : '') + '</span></div>';
      }).join('');
    box.querySelectorAll('.file-row').forEach(function (row) {
      row.onclick = function () {
        if (row.dataset.up) { browseProjectSource(path.split('/').slice(0, -1).join('/'), pid); return; }
        if (row.dataset.t === 'dir') browseProjectSource(row.dataset.p, pid);
        else api('/api/projects/' + encodeURIComponent(pid) + '/source/file?path=' + encodeURIComponent(row.dataset.p))
          .then(function (f) { openModal(row.dataset.p, f.encoding === 'utf-8' ? md(f.text) : '<div class="muted">二进制</div>', { back: function () {
            openProjectSource(path);
          } }); })
          .catch(function (e) { toast(e.message, 'err'); });
      };
    });
  }).catch(function (e) { toast(e.message, 'err'); });
}
function openProjectFiles(path) {
  var pid = state.project; if (!pid) return;
  openModal('项目文件 · ' + pid, '<div id="ftree" class="muted">加载中…</div>', { root: true });
  browseProject(path || '', pid);
}
function browseProject(path, pid) {
  api('/api/projects/' + encodeURIComponent(pid) + '/files?path=' + encodeURIComponent(path)).then(function (r) {
    var box = $('ftree'); if (!box) return;
    var up = path ? '<div class="file-row" data-up="1"><span>..</span></div>' : '';
    box.innerHTML = '<div class="muted small">' + esc(r.root || '') + ' / ' + esc(path || '') + '</div>' + up +
      (r.items || []).map(function (f) {
        return '<div class="file-row" data-p="' + esc(f.path) + '" data-t="' + f.type + '">' +
          '<span>' + (f.type === 'dir' ? '📁 ' : '📄 ') + esc(f.name) + '</span>' +
          '<span class="muted small">' + (f.type === 'file' ? fmtBytes(f.size) : '') + '</span></div>';
      }).join('');
    box.querySelectorAll('.file-row').forEach(function (row) {
      row.onclick = function () {
        if (row.dataset.up) { browseProject(path.split('/').slice(0, -1).join('/'), pid); return; }
        if (row.dataset.t === 'dir') browseProject(row.dataset.p, pid);
        else api('/api/projects/' + encodeURIComponent(pid) + '/file?path=' + encodeURIComponent(row.dataset.p))
          .then(function (f) { openModal(row.dataset.p, f.encoding === 'utf-8' ? md(f.text) : '<div class="muted">二进制</div>', { back: function () {
            openProjectFiles(path);
          } }); })
          .catch(function (e) { toast(e.message, 'err'); });
      };
    });
  }).catch(function (e) { toast(e.message, 'err'); });
}
function openSource(opts) {
  opts = opts || {};
  openModal('agent 源码 / 配置（只读）', '<div id="ftree" class="muted">加载中…</div>', { root: true });
  if (!opts.fromRoute) overlayRoute('#/source', 'source');
  browseSource(opts.path || '');
}
function browseSource(path) {
  api('/api/ops/files?path=' + encodeURIComponent(path)).then(function (r) {
    var box = $('ftree'); if (!box) return;
    box.innerHTML = '<div class="muted small">' + esc(r.root || '') + ' / ' + esc(path || '') + '</div>' +
      (path ? '<div class="file-row" data-up="1"><span>..</span></div>' : '') +
      (r.items || []).map(function (f) {
        return '<div class="file-row" data-p="' + esc(f.path) + '" data-t="' + f.type + '">' +
          '<span>' + (f.type === 'dir' ? '📁 ' : '📄 ') + esc(f.name) + '</span>' +
          '<span class="muted small">' + (f.type === 'file' ? fmtBytes(f.size) : '') + '</span></div>';
      }).join('');
    box.querySelectorAll('.file-row').forEach(function (row) {
      row.onclick = function () {
        if (row.dataset.up) { browseSource(path.split('/').slice(0, -1).join('/')); return; }
        if (row.dataset.t === 'dir') browseSource(row.dataset.p);
        else api('/api/ops/file?path=' + encodeURIComponent(row.dataset.p))
          .then(function (f) { openModal(row.dataset.p, md(f.text), { back: function () {
            openSource({ fromRoute: true, path: path });
          } }); })
          .catch(function (e) { toast(e.message, 'err'); });
      };
    });
  }).catch(function (e) { toast(e.message, 'err'); });
}


// ---------------- 交付件/文件模块自己的侧栏入口 ----------------
HiveUI.on('side:open', function (payload) {
  payload = payload || {};
  var kind = payload.kind || '';
  if (payload.project) state.project = payload.project;
  if (kind === 'project-files') return openProjectFiles();
  if (kind === 'project-source') return openProjectSource(payload.path || '');
  if (kind === 'project-artifacts') { state.sideLayer = 'project'; show('side'); loadFiles(); updateBackBtn(); return; }
  if (kind === 'artifacts') {
    state.view = 'chat'; state.group = payload.group || state.group;
    openSide(); return;
  }
  if (kind === 'artifact') {
    state.view = 'chat'; state.group = payload.group || state.group;
    var g = findGroup(state.group) || {};
    return openArtifact(payload.path || '', g.project || state.project,
      (state.group || '').indexOf('T-') === 0, payload.layer || 'ticket');
  }
  openSide();
});
