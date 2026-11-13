/* Hive Agent v3 控制台
 * 群聊（本地层秘书 / 项目秘书 / 工单群）+ 生命周期流程图 + 三层交付件
 * + 角色/流程/技能库 + 健康自检 + 版本回退 + 全链路透明
 * 只用原生 JS，不引外网 CDN（VPS 上外网不稳）。
 */
(function () {
'use strict';

// ---------------- 基础 ----------------
var state = {
  token: localStorage.getItem('hive_token') || '',
  group: 'secretary',
  groups: [],
  projects: [],
  instance: null,
  cursor: 0,
  seen: {},
  liveTimer: null,
  pollTimer: null,
  sideTab: 'files',
  sideLayer: 'ticket',
  lastLive: '',
  flow: null,
};

function $(id) { return document.getElementById(id); }
function esc(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}
function toast(msg, kind) {
  var el = $('toast');
  el.textContent = msg;
  el.className = 'toast ' + (kind || '');
  clearTimeout(el._t);
  el._t = setTimeout(function () { el.className = 'toast hidden'; }, 2600);
}
function hide(id) { var e = $(id); if (e) e.classList.add('hidden'); }
function show(id) { var e = $(id); if (e) e.classList.remove('hidden'); }

function api(path, opts) {
  opts = opts || {};
  var headers = { 'Accept': 'application/json' };
  if (state.token) headers['X-Auth-Token'] = state.token;
  var init = { method: opts.method || 'GET', headers: headers, credentials: 'same-origin' };
  if (opts.body !== undefined) {
    headers['Content-Type'] = 'application/json';
    init.body = JSON.stringify(opts.body);
  }
  return fetch(path, init).then(function (r) {
    return r.text().then(function (txt) {
      var body = {};
      try { body = txt ? JSON.parse(txt) : {}; } catch (e) { body = { raw: txt }; }
      if (r.status === 401) {
        state.token = '';
        localStorage.removeItem('hive_token');
        showLogin();
        throw new Error('未登录');
      }
      if (!r.ok) {
        var err = new Error(body.error || body.message || ('HTTP ' + r.status));
        err.code = body.code;
        err.status = r.status;
        err.body = body;
        throw err;
      }
      return body;
    });
  });
}

// ---------------- 迷你 Markdown ----------------
function md(src) {
  if (!src) return '';
  var blocks = String(src).replace(/\r\n/g, '\n').split(/\n{2,}/);
  var out = [];
  blocks.forEach(function (block) {
    var lines = block.split('\n');
    if (/^```/.test(lines[0])) {
      out.push('<pre class="code"><code>' + esc(lines.slice(1).join('\n').replace(/```$/, '')) + '</code></pre>');
      return;
    }
    if (lines.length >= 2 && /\|/.test(lines[0]) && /^\s*\|?[\s:|-]+\|?\s*$/.test(lines[1])) {
      var head = lines[0].replace(/^\s*\|/, '').replace(/\|\s*$/, '').split('|');
      var rows = lines.slice(2);
      var h = '<table class="md-table"><tr>' + head.map(function (c) { return '<th>' + inline(c.trim()) + '</th>'; }).join('') + '</tr>';
      rows.forEach(function (r) {
        var cells = r.replace(/^\s*\|/, '').replace(/\|\s*$/, '').split('|');
        h += '<tr>' + cells.map(function (c) { return '<td>' + inline(c.trim()) + '</td>'; }).join('') + '</tr>';
      });
      out.push(h + '</table>');
      return;
    }
    var m;
    if ((m = block.match(/^(#{1,4})\s+(.*)$/))) {
      var lv = m[1].length + 1;
      out.push('<h' + lv + '>' + inline(m[2]) + '</h' + lv + '>');
      return;
    }
    if (/^\s*([-*]|\d+\.)\s+/.test(block)) {
      var ordered = /^\s*\d+\./.test(block);
      var items = lines.filter(function (l) { return /^\s*([-*]|\d+\.)\s+/.test(l); })
        .map(function (l) { return '<li>' + inline(l.replace(/^\s*([-*]|\d+\.)\s+/, '')) + '</li>'; });
      out.push('<' + (ordered ? 'ol' : 'ul') + '>' + items.join('') + '</' + (ordered ? 'ol' : 'ul') + '>');
      return;
    }
    if (/^>\s?/.test(block)) {
      out.push('<blockquote>' + inline(block.replace(/^>\s?/gm, '')) + '</blockquote>');
      return;
    }
    out.push('<p>' + inline(block).replace(/\n/g, '<br>') + '</p>');
  });
  return out.join('');
}
function inline(s) {
  s = esc(s);
  s = s.replace(/`([^`]+)`/g, '<code>$1</code>');
  s = s.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  s = s.replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<em>$2</em>');
  s = s.replace(/\[([^\]]+)\]\((https?:[^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
  return s;
}

// ---------------- 头像（名字哈希 → 颜色 + 首字） ----------------
var PALETTE = ['#3b82f6', '#8b5cf6', '#0ea5e9', '#10b981', '#f59e0b', '#ef4444', '#ec4899', '#14b8a6', '#6366f1', '#84cc16'];
function avatar(name) {
  name = name || '?';
  var h = 0;
  for (var i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) & 0xffffffff;
  var c = PALETTE[Math.abs(h) % PALETTE.length];
  var initials = name.replace(/·/g, '').slice(0, 1);
  if (/^[A-Za-z]/.test(name)) initials = name.slice(0, 2).toUpperCase();
  return '<span class="avatar" style="background:' + c + '">' + esc(initials) + '</span>';
}
function fmtTime(ts) {
  if (!ts) return '';
  var d = new Date(ts * 1000);
  var hh = String(d.getHours()).padStart(2, '0');
  var mm = String(d.getMinutes()).padStart(2, '0');
  return hh + ':' + mm;
}
function fmtBytes(n) {
  if (!n) return '0 B';
  var u = ['B', 'KB', 'MB', 'GB'];
  var i = 0;
  while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
  return (n < 10 && i > 0 ? n.toFixed(1) : Math.round(n)) + ' ' + u[i];
}

// ---------------- 登录 ----------------
function showLogin() {
  hide('app');
  show('login');
}
function doLogin() {
  var pw = $('password').value;
  if (!pw) return;
  $('login-err').textContent = '';
  api('/api/auth/login', { method: 'POST', body: { password: pw } }).then(function (r) {
    state.token = r.token;
    localStorage.setItem('hive_token', r.token);
    enterApp();
  }).catch(function (e) {
    $('login-err').textContent = e.status === 401 ? '密码不对' : (e.message || '登录失败');
  });
}
function enterApp() {
  hide('login');
  show('app');
  loadGroups(true);
  startPolling();
}

// ---------------- 群列表 / 项目 ----------------
function loadGroups(first) {
  return api('/api/web/groups').then(function (r) {
    state.groups = r.items || [];
    state.projects = r.projects || [];
    state.instance = r.instance || state.instance;
    renderLayer();
    renderProjects();
    renderGroups();
    if (first) selectGroup(state.group, true);
  }).catch(function (e) {
    if (e.message !== '未登录') toast('群列表加载失败：' + e.message, 'err');
  });
}
function renderLayer() {
  var i = state.instance || {};
  $('instance-pill').textContent = i.title || '本地节点';
  $('layer-id').textContent = i.id || '';
  $('layer-title').textContent = i.title || '本地节点';
  $('layer-sub').textContent = 'layer=' + (i.layer || 'local') + ' · ' + (i.scheme || 'http');
}
function renderProjects() {
  var box = $('projects');
  box.innerHTML = '';
  if (!state.projects.length) { box.innerHTML = '<div class="muted small">暂无项目</div>'; }
  state.projects.forEach(function (p) {
    var row = document.createElement('div');
    row.className = 'project-row';
    row.innerHTML = '<span class="pname">' + esc(p.title || p.id) + '</span>' +
      '<span class="muted small">' + (p.open_tickets || 0) + '/' + (p.ticket_count || 0) + '</span>' +
      '<button class="mini danger-ghost" title="删除项目">🗑</button>';
    row.querySelector('button').onclick = function (ev) {
      ev.stopPropagation();
      deleteProject(p);
    };
    row.onclick = function () { selectGroup('sec-' + p.id); };
    box.appendChild(row);
  });
}
function renderGroups() {
  var box = $('groups');
  box.innerHTML = '';
  state.groups.forEach(function (g) {
    if (g.kind === 'project_secretary') return;
    var el = document.createElement('div');
    el.className = 'group-row' + (g.id === state.group ? ' active' : '');
    var extra = '';
    if (g.kind === 'ticket') {
      extra = '<span class="status-chip ' + esc(g.status) + '">' + esc(g.status) + '</span>';
    } else {
      extra = '<span class="muted small">' + (g.messages || 0) + ' 条</span>';
    }
    el.innerHTML = avatar(g.display || g.title) +
      '<div class="grow"><div class="gt">' + esc(g.title || g.id) + '</div>' +
      '<div class="muted small gid">' + esc(g.id) + (g.project ? ' · ' + esc(g.project) : '') + '</div></div>' + extra;
    el.onclick = function () { selectGroup(g.id); };
    box.appendChild(el);
  });
  var ps = state.groups.filter(function (g) { return g.kind === 'project_secretary'; });
  if (ps.length) {
    var block = document.createElement('div');
    block.className = 'rail-sub';
    block.innerHTML = '<div class="rail-title small">项目秘书</div>';
    ps.forEach(function (g) {
      var el = document.createElement('div');
      el.className = 'group-row' + (g.id === state.group ? ' active' : '');
      el.innerHTML = avatar(g.title) + '<div class="grow"><div class="gt">' + esc(g.title) + '</div>' +
        '<div class="muted small">' + (g.open_tickets || 0) + ' 个在跑工单</div></div>';
      el.onclick = function () { selectGroup(g.id); };
      block.appendChild(el);
    });
    box.appendChild(block);
  }
}

function deleteProject(p) {
  if (!confirm('删除项目「' + (p.title || p.id) + '」？\n只清理它的项目秘书会话；工单、交付件、知识都会保留（证据不删）。')) return;
  api('/api/projects/' + encodeURIComponent(p.id) + '/delete', { method: 'POST', body: {} })
    .then(function () { toast('项目已删除，证据保留'); loadGroups(); })
    .catch(function (e) { toast('删除失败：' + e.message, 'err'); });
}

// ---------------- 会话切换 ----------------
function selectGroup(id, silent) {
  state.group = id;
  state.cursor = 0;
  state.lastLive = '';
  $('messages').innerHTML = '';
  renderGroups();
  var g = findGroup(id);
  $('chat-title').textContent = g ? (g.title || g.id) : id;
  $('chat-sub').textContent = g ? ((g.kind === 'ticket' ? '工单群 · ' + g.project : (g.kind === 'project_secretary' ? '项目秘书' : '本地层秘书'))) : '';
  var isTicket = id.indexOf('T-') === 0;
  if (isTicket) {
    show('btn-copy-ticket');
    $('btn-copy-ticket').textContent = '⧉ ' + id;
    show('btn-fork-ticket');
  } else {
    hide('btn-copy-ticket');
    hide('btn-fork-ticket');
    hide('flow');
  }
  $('readonly-tip').classList.add('hidden');
  $('input').disabled = false;
  $('send').disabled = false;
  if (isTicket) loadFlow();
  loadTimeline(silent);
  loadLive();
  hide('livebar');
}

function findGroup(id) {
  for (var i = 0; i < state.groups.length; i++) if (state.groups[i].id === id) return state.groups[i];
  return null;
}

function loadTimeline(silent) {
  return api('/api/web/timeline?group=' + encodeURIComponent(state.group) + '&limit=200').then(function (r) {
    var box = $('messages');
    var atBottom = box.scrollTop + box.clientHeight >= box.scrollHeight - 40;
    (r.items || []).forEach(function (m) {
      var key = (m.session || '') + '|' + (m.ts || 0) + '|' + (m.speaker || '') + '|' + (m.text || '').slice(0, 24);
      if (state.seen[key]) return;
      state.seen[key] = 1;
      box.appendChild(renderMsg(m));
    });
    state.cursor = Math.max(state.cursor, Number(r.cursor || 0));
    if (atBottom || !silent) box.scrollTop = box.scrollHeight;
  }).catch(function () {});
}

function renderMsg(m) {
  var el = document.createElement('div');
  var mine = m.role === 'user' && m.speaker === '我';
  el.className = 'msg ' + (mine ? 'mine' : 'other') + (m.type === 'task' ? ' taskmsg' : '');
  var who = m.type === 'task' ? (m.speaker + ' → ' + (m.to || '角色')) : (m.speaker || '?');
  var tools = (m.tools && m.tools.length) ? '<div class="tools">' + m.tools.map(function (t) { return '<span class="toolchip">' + esc(t) + '</span>'; }).join('') + '</div>' : '';
  var body = mine ? '<p>' + esc(m.text).replace(/\n/g, '<br>') + '</p>' : md(m.text);
  el.innerHTML =
    (mine ? '' : avatar(who)) +
    '<div class="bubble">' +
      '<div class="meta"><span class="who">' + esc(who) + '</span>' +
      '<span class="muted small">' + fmtTime(m.ts) + '</span>' +
      (m.type === 'task' ? '<span class="tag">派活</span>' : '') + '</div>' +
      '<div class="body">' + body + '</div>' + tools +
    '</div>' +
    (mine ? avatar('我') : '');
  return el;
}

// ---------------- 生命周期流程图 ----------------
function loadFlow() {
  return api('/api/tickets/' + encodeURIComponent(state.group) + '/flow').then(function (r) {
    state.flow = r;
    renderFlow(r);
    if (r.readonly) {
      $('readonly-tip').classList.remove('hidden');
      $('input').disabled = true;
      $('send').disabled = true;
    }
  }).catch(function () {});
}
function renderFlow(f) {
  var box = $('flow');
  box.classList.remove('hidden');
  var cur = firstOpen(f.nodes);
  var nodes = (f.nodes || []).map(function (n, i) {
    var cls = 'fn' + (n.done ? ' done' : '') + (i === cur ? ' current' : '');
    return '<div class="' + cls + '" title="' + esc(n.detail || '') + '">' +
      '<span class="fdot"></span><span class="flabel">' + esc(n.label) + '</span></div>';
  }).join('<span class="farrow">›</span>');
  var roles = (f.roles || []).map(function (r) {
    var st = r.status || r.state || '';
    return '<span class="rolechip ' + esc(st) + '">' + esc(r.display || r.role) +
      '<span class="muted small"> ' + esc(st) + '</span></span>';
  }).join('');
  box.innerHTML = '<div class="flowline">' + nodes + '</div>' +
    (roles ? '<div class="roleline">' + roles + '</div>' : '');
}
function firstOpen(nodes) {
  nodes = nodes || [];
  for (var i = 0; i < nodes.length; i++) if (!nodes[i].done) return i;
  return nodes.length - 1;
}

// ---------------- 直播（流式 + 打断） ----------------
function loadLive() {
  api('/api/web/live?group=' + encodeURIComponent(state.group) + '&limit=12').then(function (r) {
    var running = r.running || [];
    if (!running.length) { hide('livebar'); return; }
    var top = running[0];
    var txt = (top.partial || '').slice(-1200);
    if (txt) {
      show('livebar');
      $('live-who').textContent = (top.display || top.session) + ' 正在说…' + (top.step ? '（第 ' + top.step + ' 步）' : '');
      $('live-body').innerHTML = md(txt) + '<span class="caret"></span>';
      $('live-body').scrollTop = $('live-body').scrollHeight;
      $('btn-interrupt').onclick = function () { interrupt(top.session); };
      $('btn-open-trace').classList.remove('hidden');
      $('btn-open-trace').onclick = function () { openSide('trace', top.session); };
    } else {
      hide('livebar');
    }
  }).catch(function () {});
}
function interrupt(session) {
  if (!confirm('打断 ' + session + ' 当前的这次发言？')) return;
  api('/api/sessions/' + encodeURIComponent(session) + '/interrupt', { method: 'POST', body: {} })
    .then(function () { toast('已发送打断'); hide('livebar'); })
    .catch(function (e) { toast('打断失败：' + e.message, 'err'); });
}

// ---------------- 发送 ----------------
function send() {
  var input = $('input');
  var text = input.value.trim();
  if (!text) return;
  input.value = '';
  input.style.height = 'auto';
  api('/api/chat/send', { method: 'POST', body: { text: text, group: state.group } })
    .then(function () {
      loadTimeline(true);
      setTimeout(function () { loadTimeline(true); loadLive(); }, 900);
    })
    .catch(function (e) {
      if (e.status === 410) {
        $('readonly-tip').classList.remove('hidden');
        toast('工单已结单，只读；请基于此单新开', 'warn');
      } else {
        toast('发送失败：' + e.message, 'err');
      }
    });
}

function startPolling() {
  clearInterval(state.pollTimer);
  clearInterval(state.liveTimer);
  state.pollTimer = setInterval(function () {
    loadTimeline(true);
    if (document.visibilityState === 'visible') loadGroups(false);
  }, 5000);
  state.liveTimer = setInterval(function () {
    if (document.visibilityState === 'visible') loadLive();
  }, 900);
}

// ---------------- 侧栏：交付件 / 链路 ----------------
function openSide(tab, session) {
  state.sideTab = tab || 'files';
  show('side');
  document.querySelectorAll('.stab').forEach(function (b) {
    b.classList.toggle('active', b.dataset.side === state.sideTab);
  });
  if (state.sideTab === 'files') loadFiles();
  else loadTrace(session || '');
}
function loadFiles() {
  var body = $('side-body');
  var isTicket = state.group.indexOf('T-') === 0;
  var g = findGroup(state.group) || {};
  var project = g.project || (state.group.indexOf('sec-') === 0 ? state.group.slice(4) : '');
  var tabs = '<div class="seg">' +
    (isTicket ? '<button data-layer="ticket" class="' + (state.sideLayer === 'ticket' ? 'on' : '') + '">工单层</button>' : '') +
    (project ? '<button data-layer="project" class="' + (state.sideLayer === 'project' ? 'on' : '') + '">项目层</button>' : '') +
    '<button data-layer="public" class="' + (state.sideLayer === 'public' ? 'on' : '') + '">公共层</button></div>';
  body.innerHTML = tabs + '<div id="filelist" class="filelist muted small">加载中…</div>';
  body.querySelectorAll('.seg button').forEach(function (b) {
    b.onclick = function () { state.sideLayer = b.dataset.layer; loadFiles(); };
  });
  var q = '?layer=' + state.sideLayer + '&project=' + encodeURIComponent(project) +
    '&ticket=' + encodeURIComponent(isTicket ? state.group : '');
  api('/api/artifacts/list' + q).then(function (r) {
    var box = $('filelist');
    if (!(r.items || []).length) { box.innerHTML = '<div class="empty">这一层还没有交付件</div>'; return; }
    box.className = 'filelist';
    box.innerHTML = '<div class="muted small">共 ' + r.items.length + ' 个文件 · ' + fmtBytes(r.bytes) + '</div>' +
      r.items.map(function (f) {
        return '<div class="file-row" data-path="' + esc(f.path) + '">' +
          '<span class="fname">' + esc(f.path) + '</span>' +
          '<span class="muted small">' + fmtBytes(f.size) + '</span></div>';
      }).join('');
    box.querySelectorAll('.file-row').forEach(function (row) {
      row.onclick = function () { openFile(row.dataset.path, project, isTicket); };
    });
  }).catch(function (e) { body.innerHTML = '<div class="err">' + esc(e.message) + '</div>'; });
}
function openFile(path, project, isTicket) {
  var q = '/api/artifacts/file?layer=' + state.sideLayer + '&project=' + encodeURIComponent(project) +
    '&ticket=' + encodeURIComponent(isTicket ? state.group : '') + '&path=' + encodeURIComponent(path);
  api(q).then(function (f) {
    openModal(path, f.encoding === 'utf-8' ? md(f.text) : '<div class="muted">二进制文件（base64 已省略）</div>');
  }).catch(function (e) { toast('打不开：' + e.message, 'err'); });
}

function loadTrace(session) {
  var body = $('side-body');
  body.innerHTML = '<div class="seg">' +
    '<button data-kind="" class="on">全部</button>' +
    '<button data-kind="llm">LLM</button>' +
    '<button data-kind="tool">工具</button>' +
    '<button data-kind="api">模块</button>' +
    '<button data-kind="bus">总线</button></div>' +
    '<div class="muted small" id="tracestat"></div><div id="tracelist"></div>';
  var kind = '';
  body.querySelectorAll('.seg button').forEach(function (b) {
    b.onclick = function () {
      body.querySelectorAll('.seg button').forEach(function (x) { x.classList.remove('on'); });
      b.classList.add('on');
      kind = b.dataset.kind;
      fetchTrace(kind, session);
    };
  });
  fetchTrace('', session);
}
function fetchTrace(kind, session) {
  var q = '/api/trace/recent?limit=150' + (session ? '&session=' + encodeURIComponent(session) : '') +
    (kind ? '&kind=' + kind : '');
  api(q).then(function (r) {
    var list = $('tracelist');
    var stats = r.stats || {};
    if ($('tracestat')) $('tracestat').textContent = '内存 ' + ((stats.counters && stats.counters.ring) || stats.files || 0) + ' · 文件 ' + (stats.files || 0) + ' 个 / ' + fmtBytes(stats.bytes);
    list.innerHTML = (r.items || []).map(function (it, idx) {
      var data = JSON.stringify(it.data || {}, null, 2);
      return '<div class="trace-row" data-idx="' + idx + '">' +
        '<div class="trace-head"><span class="kind ' + esc(it.kind.split('.')[0]) + '">' + esc(it.kind) + '</span>' +
        '<span class="muted small">' + esc(it.session || '') + '</span></div>' +
        '<div class="trace-sum">' + esc(summaryOf(it)) + '</div>' +
        '<pre class="trace-json hidden">' + esc(data.slice(0, 4000)) + '</pre></div>';
    }).join('') || '<div class="empty">还没有记录</div>';
    list.querySelectorAll('.trace-row').forEach(function (row) {
      row.querySelector('.trace-head').onclick = function () {
        row.querySelector('.trace-json').classList.toggle('hidden');
      };
    });
  }).catch(function (e) { $('side-body').innerHTML = '<div class="err">' + esc(e.message) + '</div>'; });
}
function summaryOf(it) {
  var d = it.data || {};
  if (it.kind === 'llm.request') return '→ ' + (d.model || '') + ' · ' + (d.message_count || (d.messages || []).length) + ' 条消息 · tools=' + ((d.tools || []).length);
  if (it.kind === 'llm.response') return '← ' + (d.content ? d.content.slice(0, 60) : '') + (d.tool_calls && d.tool_calls.length ? ' [tool_calls ' + d.tool_calls.length + ']' : '');
  if (it.kind === 'tool.call') return (d.tool || '') + ' ' + String(d.args || '').slice(0, 80);
  if (it.kind === 'tool.result') return (d.tool || '') + ' 返回 ' + (d.chars || 0) + ' 字（' + (d.mode || '') + '）';
  if (it.kind === 'api.call') return (d.caller || d.from || '?') + ' → ' + (d.route || '') + ' ' + (d.ms || 0) + 'ms';
  if (it.kind === 'bus.event') return (d.topic || '');
  return it.kind;
}

// ---------------- 弹窗 ----------------
function openModal(title, html) {
  $('modal-title').textContent = title;
  $('modal-body').innerHTML = html;
  show('modal');
}
function closeModal() { hide('modal'); }

function openLibrary(kind) {
  kind = kind || 'roles';
  var kinds = [['roles', '角色'], ['flows', '流程'], ['skills', '技能']];
  var tabs = '<div class="seg">' + kinds.map(function (k) {
    return '<button data-kind="' + k[0] + '" class="' + (kind === k[0] ? 'on' : '') + '">' + k[1] + '库</button>';
  }).join('') + '</div><div id="libbody" class="libbody"></div>';
  openModal('可插拔能力库', tabs);
  document.querySelectorAll('#modal-body .seg button').forEach(function (b) {
    b.onclick = function () { openLibrary(b.dataset.kind); };
  });
  api('/api/library/list?kind=' + kind).then(function (r) {
    var box = $('libbody');
    box.innerHTML = (r.items || []).map(function (it, i) {
      var sub = kind === 'roles' ? (it.responsibility || '') :
        kind === 'flows' ? ((it.checks || []).map(function (c) { return c.must || c; }).join(' · ')) :
          (it.body || '').slice(0, 80);
      return '<div class="libcard" data-i="' + i + '"><div class="libtitle">' + esc(it.cn || it.name || it.id) +
        (it.builtin ? '<span class="tag">内置</span>' : '') + '</div>' +
        '<div class="muted small">' + esc(it.id) + ' · ' + esc(sub) + '</div></div>';
    }).join('') || '<div class="empty">空</div>';
    box.querySelectorAll('.libcard').forEach(function (c) {
      c.onclick = function () {
        var it = r.items[Number(c.dataset.i)];
        openModal((it.cn || it.id) + ' · ' + kind, '<pre class="raw">' + esc(JSON.stringify(it, null, 2)) + '</pre>');
      };
    });
  }).catch(function (e) { $('libbody').innerHTML = '<div class="err">' + esc(e.message) + '</div>'; });
}

function openHealth() {
  openModal('健康自检', '<div id="hbody" class="muted">检查中…</div>');
  Promise.all([
    api('/api/health/self'),
    api('/api/artifacts/stats'),
    api('/api/ops/status').catch(function () { return {}; })
  ]).then(function (rs) {
    var h = rs[0] || {}, a = rs[1] || {}, s = rs[2] || {};
    var checks = (h.checks || []).map(function (c) {
      return '<div class="check ' + (c.ok ? 'ok' : 'bad') + '"><span class="dot"></span>' +
        '<div><div>' + esc(c.name) + '</div><div class="muted small">' + esc(c.detail || '') + '</div></div></div>';
    }).join('');
    var big = (a.biggest || []).slice(0, 6).map(function (b) {
      return '<div class="file-row"><span>' + esc(b.project + '/' + b.ticket) + (b.compressed ? ' (已压缩)' : '') +
        '</span><span class="muted small">' + fmtBytes(b.bytes) + '</span></div>';
    }).join('');
    $('hbody').innerHTML =
      '<div class="health-top"><span class="pill ' + (h.healthy ? 'good' : 'bad') + '">' + (h.healthy ? '健康' : '有异常') + '</span>' +
      '<span class="muted small">v' + esc(h.version || '') + ' · TLS ' + (h.tls ? 'on' : 'off') + ' · uptime ' + (h.uptime_sec || 0) + 's</span></div>' +
      '<div class="checks">' + checks + '</div>' +
      '<h4>交付件体积</h4><div class="muted small">合计 ' + fmtBytes(a.total_bytes) + ' · 磁盘余量 ' + fmtBytes(a.disk_free) + '</div>' +
      '<div class="filelist">' + big + '</div>' +
      (a.need_compress ? '<div class="warnbox">交付件偏大，建议压缩归档（工单结单后自动可压）</div>' : '') +
      '<div class="row-btns"><button class="ghost" id="btn-compress-all">压缩 7 天前工单</button></div>';
    var cb = $('btn-compress-all');
    if (cb) cb.onclick = function () {
      api('/api/artifacts/compress', { method: 'POST', body: { days: 7 } }).then(function (r) {
        toast('已压缩 ' + (r.compressed || []).length + ' 个工单');
        openHealth();
      }).catch(function (e) { toast(e.message, 'err'); });
    };
  }).catch(function (e) { $('hbody').innerHTML = '<div class="err">' + esc(e.message) + '</div>'; });
}

function openVersions() {
  openModal('版本管理', '<div id="vbody" class="muted">读取中…</div>');
  api('/api/ops/versions').then(function (v) {
    var g = v.git || {};
    if (!g.available) {
      $('vbody').innerHTML = '<div class="muted">这个部署目录不是 git 仓库，无法回退。</div>';
      return;
    }
    $('vbody').innerHTML = '<div class="muted small">当前 ' + esc(v.version || '') +
      ' · HEAD ' + esc(g.head || '') + (g.dirty ? ' · 工作区有改动' : '') + '</div>' +
      '<div class="commitlist">' + (g.commits || []).map(function (c) {
        return '<div class="commit ' + (c.current ? 'cur' : '') + '">' +
          '<div class="grow"><div><code>' + esc(c.short) + '</code> ' + esc(c.subject || '') + '</div>' +
          '<div class="muted small">' + esc(c.date || '') + (c.current ? ' · 当前运行' : '') + '</div></div>' +
          (c.current ? '' : '<button class="mini" data-t="' + esc(c.short) + '">回退</button>') + '</div>';
      }).join('') + '</div>';
    $('vbody').querySelectorAll('button[data-t]').forEach(function (b) {
      b.onclick = function () { rollback(b.dataset.t); };
    });
  }).catch(function (e) { $('vbody').innerHTML = '<div class="err">' + esc(e.message) + '</div>'; });
}
function rollback(t) {
  if (!confirm('回退到 ' + t + '？\nwatchdog 会自动建 autosave 分支保住当前代码，再切过去重启。')) return;
  api('/api/ops/rollback', { method: 'POST', body: { target: t } })
    .then(function () { toast('已下发回退指令，watchdog 几秒内切换'); })
    .catch(function (e) { toast('回退失败：' + e.message, 'err'); });
}

function openTicketModal(goal, parent) {
  var opts = state.projects.map(function (p) {
    return '<option value="' + esc(p.id) + '">' + esc(p.title || p.id) + '</option>';
  }).join('');
  var g = findGroup(state.group) || {};
  var def = parent ? (g.project || '') : (g.project || (state.projects[0] || {}).id || '');
  openModal(parent ? '基于 ' + parent + ' 新开工单' : '新建工单',
    '<label class="field">目标<textarea id="tk-goal" rows="4" placeholder="要做什么、验收标准是什么">' + esc(goal || '') + '</textarea></label>' +
    '<label class="field">项目<select id="tk-project">' + (opts || '<option value="default">default</option>') + '</select></label>' +
    (parent ? '<label class="field">前序工单<input id="tk-parent" value="' + esc(parent) + '" readonly></label>' : '') +
    '<div class="row-btns"><button class="primary" id="tk-create">派给项目经理</button></div>');
  if (def) $('tk-project').value = def;
  $('tk-create').onclick = function () {
    var goalText = $('tk-goal').value.trim();
    if (!goalText) { toast('目标不能空', 'warn'); return; }
    api('/api/tickets/create', { method: 'POST', body: {
      goal: goalText, project: $('tk-project').value, parent: parent || ''
    } }).then(function (r) {
      closeModal();
      toast('工单已开：' + r.ticket.id);
      loadGroups().then(function () { selectGroup(r.ticket.id); });
    }).catch(function (e) { toast('开工单失败：' + e.message, 'err'); });
  };
}

// ---------------- 固定命令 ----------------
function restartAgent() {
  if (!confirm('重启 agent 进程？（watchdog 会立刻拉起）')) return;
  api('/api/ops/restart', { method: 'POST', body: {} })
    .then(function () { toast('重启指令已下发'); }).catch(function (e) { toast(e.message, 'err'); });
}
function stopAll() {
  if (!confirm('彻底停止 watchdog + agent？\n之后只能通过 SSH 手动起。')) return;
  api('/api/ops/stop', { method: 'POST', body: {} })
    .then(function () { toast('停止指令已下发'); }).catch(function (e) { toast(e.message, 'err'); });
}
function compactSecretary() {
  var sid = state.group.indexOf('sec-') === 0 ? state.group : 'secretary';
  api('/api/sessions/' + encodeURIComponent(sid) + '/compact', { method: 'POST', body: {} })
    .then(function (r) { toast('已压缩：' + String(r.summary || '').slice(0, 60)); loadTimeline(true); })
    .catch(function (e) { toast(e.message, 'err'); });
}

// ---------------- 事件绑定 ----------------
$('login-btn').onclick = doLogin;
$('password').addEventListener('keydown', function (e) { if (e.key === 'Enter') doLogin(); });
$('send').onclick = send;
$('input').addEventListener('keydown', function (e) {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
});
$('input').addEventListener('input', function () {
  this.style.height = 'auto';
  this.style.height = Math.min(140, this.scrollHeight) + 'px';
});
$('btn-rail').onclick = function () { $('rail').classList.toggle('open'); };
$('btn-files').onclick = function () { openSide('files'); };
$('side-close').onclick = function () { hide('side'); };
$('modal-close').onclick = closeModal;
$('btn-newticket').onclick = function () { openTicketModal(''); };
$('btn-fork-ticket').onclick = function () {
  openTicketModal('基于 ' + state.group + ' 的后续修改：', state.group);
};
$('btn-copy-ticket').onclick = function () {
  var id = state.group;
  var done = function () { toast('已复制 ' + id); };
  if (navigator.clipboard) navigator.clipboard.writeText(id).then(done).catch(function () { prompt('复制工单号', id); });
  else prompt('复制工单号', id);
};
$('btn-refresh').onclick = function () {
  state.seen = {};
  $('messages').innerHTML = '';
  loadTimeline(); loadLive();
  if (state.group.indexOf('T-') === 0) loadFlow();
};
$('btn-restart').onclick = restartAgent;
$('btn-stop').onclick = stopAll;
$('btn-compact').onclick = compactSecretary;
$('btn-newproject').onclick = function () {
  var name = prompt('项目 id（英文/数字，例如 webapp）');
  if (!name) return;
  api('/api/projects/create', { method: 'POST', body: { name: name, title: name } })
    .then(function () { toast('项目已创建'); loadGroups(); })
    .catch(function (e) { toast(e.message, 'err'); });
};
document.querySelectorAll('.tab').forEach(function (b) {
  b.onclick = function () {
    var tab = b.dataset.tab;
    document.querySelectorAll('.tab').forEach(function (x) { x.classList.toggle('active', x === b); });
    if (tab === 'chat') { closeModal(); hide('side'); }
    else if (tab === 'library') openLibrary('roles');
    else if (tab === 'health') openHealth();
    else if (tab === 'versions') openVersions();
    else openSide('trace');
  };
});
document.querySelectorAll('.stab').forEach(function (b) {
  b.onclick = function () {
    document.querySelectorAll('.stab').forEach(function (x) { x.classList.toggle('active', x === b); });
    openSide(b.dataset.side);
  };
});

// ---------------- 启动 ----------------
api('/api/auth/status').then(function (r) {
  if (r.scheme && r.scheme === 'https' && location.protocol !== 'https:') {
    $('login-hint').textContent = '服务已启用 HTTPS，建议用 https:// 访问';
  }
  if (r.authed) enterApp(); else showLogin();
}).catch(function () { showLogin(); });
})();
