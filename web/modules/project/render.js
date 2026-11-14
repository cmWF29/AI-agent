// ---------------- 侧栏 / 项目 ----------------
// 项目模块自己的渲染模板：外部容器只留 #mount-project，不预设任何项目字段。
var PROJECT_HTML = `
<div class="pv-head">
  <div>
    <div class="muted small">项目管理</div>
    <h2 id="pv-title">项目</h2>
    <div class="muted small" id="pv-sub"></div>
  </div>
  <div class="row-btns">
    <button class="ghost" id="pv-rename">改名</button>
    <button class="ghost" id="pv-files">项目文件</button>
    <button class="ghost" id="pv-source">项目源码</button>
    <button class="ghost" id="pv-bindsource">绑定源码路径</button>
    <button class="danger-ghost" id="pv-delete">归档 / 删除</button>
  </div>
</div>
<div class="pv-grid">
  <div class="card">
    <div class="card-head"><strong>工单</strong><span class="muted small" id="pv-ticketstat"></span></div>
    <div id="pv-tickets" class="ticketlist"></div>
  </div>
  <div class="card">
    <div class="card-head"><strong>运行模式</strong></div>
    <p class="muted small">项目默认后端：api = 内核 ReAct；claude-code = 已有 Agent CLI。工单可单独覆盖。</p>
    <label class="field">默认后端<select id="pv-backend"><option value="api">api（内核循环）</option><option value="claude-code">claude-code（已有 Agent）</option></select></label>
    <div class="row-btns"><button class="ghost" id="pv-savebackend">保存模式</button><button class="ghost" id="pv-apiconfig">查看 API 配置</button></div>
    <div class="muted small" id="pv-modeinfo"></div>
  </div>
  <div class="card">
    <div class="card-head"><strong>秘书</strong></div>
    <p class="muted small">项目的管家：接需求、判断是否开工单。上下文只属于这个项目。</p>
    <div class="row-btns">
      <button class="primary" id="pv-secretary">进入秘书对话</button>
      <button class="ghost" id="pv-compact">压缩本项目秘书上下文</button>
    </div>
  </div>
  <div class="card">
    <div class="card-head"><strong>新建工单</strong></div>
    <label class="field">标题<input id="pv-newtitle" placeholder="可空，默认取目标前 40 字" /></label>
    <label class="field">目标<textarea id="pv-newgoal" rows="3" placeholder="要做什么、验收标准、边界"></textarea></label>
    <label class="field">标签<input id="pv-newtags" placeholder="frontend,backend,docs（逗号分隔）" /></label>
    <label class="field">后端<select id="pv-newbackend"><option value="">跟随项目</option><option value="api">api</option><option value="claude-code">claude-code</option></select></label>
    <label class="checkline"><input type="checkbox" id="pv-now" /> 立即执行（高峰期也不排队）</label>
    <label class="checkline"><input type="checkbox" id="pv-trace" /> 群聊并入模块报文 trace（默认关闭，创建后不可改）</label>
    <button class="primary" id="pv-create">派给项目经理</button>
  </div>
  <div class="card">
    <div class="card-head"><strong>空闲 / 队列</strong><span class="muted small" id="pv-idleinfo"></span></div>
    <div class="muted small">忙闲配置按项目保存；队列也只属于本项目。</div>
    <label class="checkline"><input type="checkbox" id="pv-idle-enabled" /> 启用忙闲判断</label>
    <label class="field">高峰窗口<input id="pv-idle-windows" placeholder="09:00-12:00, 14:00-18:00" /></label>
    <label class="field">空闲折扣<input id="pv-idle-discount" type="number" min="0" max="1" step="0.05" /></label>
    <label class="checkline"><input type="checkbox" id="pv-idle-force" /> 强制高峰（调试）</label>
    <div class="row-btns"><button class="ghost" id="pv-saveidle">保存忙闲配置</button><button class="ghost" id="pv-idle">本项目空闲队列</button></div>
  </div>
  <div class="card">
    <div class="card-head"><strong>交付件</strong></div>
    <div class="muted small">三层归档：公共层 / 项目层 / 工单层（带工单号与版本）。</div>
    <div class="row-btns"><button class="ghost" id="pv-artifacts">打开项目层交付件</button></div>
  </div>
</div>
`;
(function mountProjectTemplate() {
  var host = $('mount-project');
  if (host && !host.innerHTML.trim()) host.innerHTML = PROJECT_HTML;
})();

function loadGroups(first) {
  return api('/api/web/groups').then(function (r) {
    state.groups = r.items || []; state.projects = r.projects || [];
    renderProjects(); renderRailGroups();
    if (first) {
      if (!state.projects.length) {
        state.view = 'project'; state.project = '';
        hide('chatview'); show('projectview');
        $('pv-title').textContent = '还没有项目';
        $('pv-sub').textContent = '点左侧「+」新建项目，再进入项目秘书/工单。';
        $('pv-tickets').innerHTML = '<div class="empty">暂无项目</div>';
        state.booted = true;
        return;
      }
      applyRoute(routeOfHash(), { initial: true }); state.booted = true;
      if (!location.hash) replaceHash(hashOfView());
    }
  }).catch(function (e) { if (e.message !== '未登录') toast('加载失败：' + e.message, 'err'); });
}
function renderProjects() {
  var box = $('projects'); box.innerHTML = '';
  if (!state.projects.length) box.innerHTML = '<div class="muted small">暂无项目</div>';
  state.projects.forEach(function (p) {
    var g = state.groups.filter(function (x) { return x.project === p.id; });
    var tickets = g.filter(function (x) { return x.kind === 'ticket'; });
    var open = tickets.filter(function (x) { return x.status !== 'closed'; }).length;
    var el = document.createElement('div');
    el.className = 'project-row' + (state.view === 'project' && state.project === p.id ? ' active' : '');
    el.innerHTML = '<span class="pdot"></span><div class="grow"><div class="pname">' + esc(p.title || p.id) + '</div>' +
      '<div class="muted small">' + open + ' 在跑 / ' + tickets.length + ' 工单</div></div>';
    el.onclick = function () { openProject(p.id); };
    box.appendChild(el);
  });
}
function renderRailGroups() { /* 侧栏不再放秘书/全局会话：只从项目页进入项目秘书或工单。 */ }

function findProject(id) { for (var i = 0; i < state.projects.length; i++) if (state.projects[i].id === id) return state.projects[i]; return null; }
function findGroup(id) { for (var i = 0; i < state.groups.length; i++) if (state.groups[i].id === id) return state.groups[i]; return null; }

function applyRoute(r, opts) {
  opts = opts || {};
  if (r.type === 'project') {
    if (r.id && findProject(r.id)) { openProject(r.id, true, { fromRoute: true }); return; }
    var first = state.projects[0];
    if (first) { openProject(first.id, true, { fromRoute: true, replace: true }); return; }
    toast('还没有项目；请先在左侧新建项目', 'warn');
    return;
  }
  if (r.type === 'chat') {
    if (findGroup(r.id)) { selectGroup(r.id, true, { fromRoute: true }); return; }
    if (r.id.indexOf('sec-') === 0 && findProject(r.id.slice(4))) { selectGroup(r.id, true, { fromRoute: true }); return; }
    toast('会话不存在：' + r.id, 'warn');
    var p0 = state.projects[0]; if (p0) openProject(p0.id, true, { replace: true });
    return;
  }
  // 覆盖层（库/健康/版本）：底下保留当前项目/会话，关闭后自然回去
  if (!state.booted) {
    var p1 = state.projects[0];
    if (p1) openProject(p1.id, true, { fromRoute: true });
  }
  setTab(r.tab);
  if (r.tab === 'library') openLibrary(r.kind, { fromRoute: true });
  else if (r.tab === 'health') openHealth({ fromRoute: true });
  else if (r.tab === 'versions') openVersions({ fromRoute: true });
  else if (r.tab === 'source') {
    if (r.project && findProject(r.project)) { state.project = r.project; openProject(r.project, true, { fromRoute: true }); }
    openProjectSource(r.path || '');
  } else if (r.tab === 'idle') {
    if (r.project && findProject(r.project)) { state.project = r.project; openProject(r.project, true, { fromRoute: true }); }
    openIdle();
  } else if (r.tab === 'artifacts') {
    state.view = 'chat'; state.group = r.group || state.group;
    show('side'); loadFiles(); updateBackBtn();
  } else if (r.tab === 'artifact') {
    state.view = 'chat'; state.group = r.group || state.group;
    openArtifact(r.path || '', (findGroup(state.group) || {}).project || state.project,
      (state.group || '').indexOf('T-') === 0, 'ticket');
  } else if (r.tab === 'fork') {
    state.view = 'chat'; state.group = r.group || state.group;
    openFork('基于 ' + state.group + ' 的后续修改：', state.group);
  }
}

function openProject(pid, silent, opts) {
  opts = opts || {};
  if (!findProject(pid)) {
    var pp = state.projects[0];
    if (pp) { pid = pp.id; } else { toast('还没有项目', 'warn'); return; }
  }
  state.view = 'project'; state.project = pid;
  hide('chatview'); show('projectview'); hide('side'); closeModal({ silent: true });
  $('rail').classList.remove('open'); $('rail-mask').classList.remove('show');
  renderProjects(); setTab('');
  if (!opts.fromRoute) {
    var h = '#/project/' + enc(pid);
    if (opts.replace) replaceHash(h); else pushHash(h);
  }
  updateBackBtn();
  loadIdle();
  loadProjectIdle(pid);
  // 项目容器只收到“该挂载了”的事实；项目数据读取与渲染仍由项目模块自己完成。
  HiveUI.mount('project', pid, 'mount-project');
}

HiveUI.on('project:mounted', function (payload) {
  if (payload.projectId !== state.project) return;
  api('/api/projects/' + encodeURIComponent(payload.projectId)).then(function (r) {
    renderProject(r.project || {});
  }).catch(function (e) { toast('项目读取失败：' + e.message, 'err'); });
});
function applyBackendAvailability() {
  var available = state.backendAvailable !== false;
  ['pv-backend', 'pv-newbackend', 'tk-backend'].forEach(function (id) {
    var sel = $(id); if (!sel) return;
    var opt = sel.querySelector('option[value="claude-code"]'); if (!opt) return;
    opt.disabled = !available;
    opt.textContent = available ? 'claude-code（已有 Agent）' : 'claude-code（本机未装 CLI，不可选）';
    if (!available && sel.value === 'claude-code') sel.value = 'api';
  });
}
function renderProject(p) {
  $('pv-title').textContent = p.title || p.id;
  $('pv-sub').textContent = 'id=' + p.id + ' · 后端 ' + (p.backend || '未设置（跟随全局）') +
    ' · 源码 ' + (p.source_path || '未绑定') + ' · 交付件 ' + (p.artifacts_root || '') + ' · 秘书 ' + (p.secretary || '');
  if ($('pv-backend')) $('pv-backend').value = p.backend || 'api';
  if ($('pv-modeinfo')) $('pv-modeinfo').textContent = '源码绑定后可浏览项目代码；Agent 模式由本机 Claude Code CLI 执行。';
  api('/api/agents/backends').then(function (r) {
    var cc = ((r.items || []).filter(function (x) { return x.name === 'claude-code'; })[0]) || {};
    state.backendAvailable = !!cc.available;
    applyBackendAvailability();
    if ($('pv-modeinfo')) $('pv-modeinfo').textContent = '源码 ' + (p.source_path || '未绑定') +
      '；claude-code ' + (cc.available ? '可用' : '不可用（本机未装 CLI，已置灰）') +
      '；全局默认 ' + (r.default || 'api');
  }).catch(function () {});
  var tickets = p.tickets || [];
  $('pv-ticketstat').textContent = tickets.length + ' 个（' + tickets.filter(function (t) { return t.status !== 'closed'; }).length + ' 在跑）';
  var box = $('pv-tickets');
  if (!tickets.length) { box.innerHTML = '<div class="empty">还没有工单，右边新建一个</div>'; }
  else {
    box.innerHTML = tickets.map(function (t) {
      var chips = (t.tags || []).map(function (x) { return '<span class="tagchip">' + esc(x) + '</span>'; }).join('');
      return '<div class="trow" data-id="' + esc(t.id) + '">' +
        '<div class="grow"><div class="tt">' + esc(t.title || t.id) + '</div>' +
        '<div class="muted small"><code>' + esc(t.id) + '</code> ' + chips + '</div></div>' +
        '<span class="status-chip ' + esc(t.status) + '">' + esc(statusLabel(t.status)) + '</span>' +
        '<button class="mini" data-open="1">进入</button>' +
        (t.status === 'closed' ? '<button class="mini danger-ghost" data-del="1">删除</button>' : '') +
        '</div>';
    }).join('');
    box.querySelectorAll('.trow').forEach(function (row) {
      var tid = row.dataset.id;
      row.querySelector('[data-open]').onclick = function (e) { e.stopPropagation(); selectGroup(tid); };
      var del = row.querySelector('[data-del]');
      if (del) del.onclick = function (e) {
        e.stopPropagation();
        if (!confirm('删除工单 ' + tid + '？\n只删记录与工作树；交付件、知识都保留，可作证据。')) return;
        api('/api/tickets/' + encodeURIComponent(tid) + '/delete', { method: 'POST', body: {} })
          .then(function () { toast('工单已删除，证据保留'); loadGroups(); openProject(state.project, true); })
          .catch(function (er) { toast('删除失败：' + er.message, 'err'); });
      };
      row.onclick = function () { selectGroup(tid); };
    });
  }
}


// ---------------- 项目动作 ----------------
function createProject() {
  var name = prompt('项目 id（英文/数字，例如 webapp）'); if (!name) return;
  var src = prompt('可选：绑定源码目录绝对路径（本机/服务器上真实存在的目录；空=不绑定）') || '';
  api('/api/projects/create', { method: 'POST', body: { name: name, title: name, source_path: src } })
    .then(function () { toast('项目已创建'); loadGroups().then(function () { openProject(name); }); })
    .catch(function (e) { toast(e.message, 'err'); });
}
function renameProject() {
  var p = findProject(state.project); if (!p) return;
  var t = prompt('项目名称', p.title || p.id); if (!t) return;
  api('/api/projects/' + encodeURIComponent(p.id) + '/rename', { method: 'POST', body: { title: t } })
    .then(function () { toast('已改名'); loadGroups().then(function () { openProject(p.id, true); }); })
    .catch(function (e) { toast(e.message, 'err'); });
}
function deleteProject() {
  var p = findProject(state.project); if (!p) return;
  api('/api/projects/' + encodeURIComponent(p.id) + '/delete-preview').then(function (r) {
    var open = (r.open_tickets || []).length;
    var warn = open ? '<div class="danger small">还有 ' + open + ' 个未结单工单：' + esc(r.open_tickets.join(', ')) + '。删除会被拒绝，需先结单。</div>' : '';
    openModal('项目生命周期 · ' + (p.title || p.id),
      '<div class="muted small">归档只打标记、保留全部数据；删除才会进入下面的清理选项。</div>' + warn +
      '<div class="filelist"><div class="file-row"><span>工单</span><span class="muted small">' + r.tickets + ' 个（已结单 ' + r.closed_tickets + '）</span></div>' +
      '<div class="file-row"><span>项目层交付件</span><span class="muted small">' + (r.artifacts.exists ? (r.artifacts.bytes + ' B') : '不存在') + '</span></div>' +
      '<div class="file-row"><span>项目层知识</span><span class="muted small">' + (r.knowledge.exists ? (r.knowledge.files + ' 个文件') : '不存在') + '</span></div>' +
      '<div class="file-row"><span>项目 main 工作树</span><span class="muted small">' + (r.main_tree.exists ? '存在' : '不存在') + '</span></div></div>' +
      '<h3>删除时可选级联清理</h3>' +
      '<label class="checkline"><input type="checkbox" id="lc-tickets" /> 删除已结单工单（工作树/记录；其交付件仍保留）</label>' +
      '<label class="checkline"><input type="checkbox" id="lc-artifacts" /> 删除项目层交付件目录</label>' +
      '<label class="checkline"><input type="checkbox" id="lc-knowledge" /> 删除项目层知识目录</label>' +
      '<label class="checkline"><input type="checkbox" id="lc-main" /> 删除项目 main 工作树（含 .git）</label>' +
      '<label class="checkline"><input type="checkbox" id="lc-source" /> 仅解绑外部源码路径（绝不删除外部目录）</label>' +
      '<div class="row-btns"><button class="ghost" id="lc-archive">归档项目</button>' +
      '<button class="danger" id="lc-delete" ' + (open ? 'disabled' : '') + '>删除项目</button></div>');
    $('lc-archive').onclick = function () {
      api('/api/projects/' + encodeURIComponent(p.id) + '/archive', { method: 'POST', body: { archived: true } })
        .then(function () { closeModal(); toast('项目已归档'); loadGroups(); })
        .catch(function (e) { toast(e.message, 'err'); });
    };
    $('lc-delete').onclick = function () {
      if (!confirm('确认删除项目「' + (p.title || p.id) + '」？此操作不可撤销。')) return;
      api('/api/projects/' + encodeURIComponent(p.id) + '/delete', { method: 'POST', body: {
        mode: 'delete', cascade: {
          tickets: $('lc-tickets').checked, artifacts: $('lc-artifacts').checked,
          knowledge: $('lc-knowledge').checked, main_tree: $('lc-main').checked,
          source: $('lc-source').checked,
        },
      } }).then(function () {
        closeModal(); toast('项目已删除'); state.project = ''; loadGroups().then(function () {
          var n = state.projects[0]; if (n) openProject(n.id); else toast('已没有项目，可点左侧 + 新建', 'warn');
        });
      }).catch(function (e) { toast('删除失败：' + e.message, 'err'); });
    };
  }).catch(function (e) { toast(e.message, 'err'); });
}
function compactProjectSecretary() {
  var sid = 'sec-' + state.project;
  api('/api/sessions/' + encodeURIComponent(sid) + '/compact', { method: 'POST', body: {} })
    .then(function (r) { toast('已压缩 ' + sid + '：' + String(r.summary || '').slice(0, 40)); })
    .catch(function (e) { toast('压缩失败：' + e.message, 'err'); });
}
function createTicket() {
  var goal = $('pv-newgoal').value.trim(); if (!goal) { toast('目标不能空', 'warn'); return; }
  if ($('pv-newbackend').value === 'claude-code' && state.backendAvailable === false) {
    toast('claude-code 在本机不可用，请改选 api 或跟随项目', 'err'); return;
  }
  var tags = $('pv-newtags').value.split(/[,，\s]+/).filter(Boolean);
  api('/api/tickets/create', { method: 'POST', body: {
    title: $('pv-newtitle').value.trim(), goal: goal, project: state.project, tags: tags,
    backend: ($('pv-newbackend') || {}).value || '',
    trace_enabled: !!($('pv-trace') || {}).checked,
    force: $('pv-now').checked, when: $('pv-now').checked ? 'now' : 'auto',
  } }).then(function (r) {
    toast(r.ticket.status === 'queued' ? '高峰期已排队，空闲自动开跑' : ('工单已开：' + r.ticket.id));
    $('pv-newgoal').value = ''; $('pv-newtitle').value = ''; $('pv-newtags').value = '';
    loadGroups(); loadIdle();
    if (r.ticket.status !== 'queued') selectGroup(r.ticket.id);
    else openProject(state.project, true);
  }).catch(function (e) { toast('开工单失败：' + e.message, 'err'); });
}
function openFork(goal, parent) {
  var opts = state.projects.map(function (p) { return '<option value="' + esc(p.id) + '">' + esc(p.title || p.id) + '</option>'; }).join('');
  openModal(parent ? '基于 ' + parent + ' 新开工单' : '新建工单',
    '<label class="field">目标<textarea id="tk-goal" rows="4">' + esc(goal || '') + '</textarea></label>' +
    '<label class="field">项目<select id="tk-project">' + opts + '</select></label>' +
    '<label class="field">标签<input id="tk-tags" placeholder="逗号分隔" /></label>' +
    '<label class="field">后端<select id="tk-backend"><option value="">跟随项目</option><option value="api">api</option><option value="claude-code">claude-code</option></select></label>' +
    '<label class="checkline"><input type="checkbox" id="tk-now" /> 立即执行</label>' +
    '<label class="checkline"><input type="checkbox" id="tk-trace" /> 群聊并入模块报文 trace（创建后不可改）</label>' +
    '<div class="row-btns"><button class="primary" id="tk-create">派给项目经理</button></div>');
  var def = (findGroup(state.group) || {}).project || state.project;
  if (def) $('tk-project').value = def;
  applyBackendAvailability();
  $('tk-create').onclick = function () {
    var g = $('tk-goal').value.trim(); if (!g) { toast('目标不能空', 'warn'); return; }
    if ($('tk-backend').value === 'claude-code' && state.backendAvailable === false) {
      toast('claude-code 在本机不可用，请改选 api 或跟随项目', 'err'); return;
    }
    api('/api/tickets/create', { method: 'POST', body: { goal: g, project: $('tk-project').value, parent: parent || '',
      tags: $('tk-tags').value.split(/[,，\s]+/).filter(Boolean), force: $('tk-now').checked,
      backend: ($('tk-backend') || {}).value || '', trace_enabled: !!($('tk-trace') || {}).checked } })
      .then(function (r) { closeModal(); toast('工单已开：' + r.ticket.id); loadGroups().then(function () { if (r.ticket.status !== 'queued') selectGroup(r.ticket.id); }); })
      .catch(function (e) { toast(e.message, 'err'); });
  };
}

