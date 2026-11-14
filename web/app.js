/* Hive Agent v4 控制台
 * 项目 -> 项目页（改名/工单/秘书/新建工单/文件）
 * 工单群聊：角色发言 + 模块报文（点击看完整 JSON）+ 并行编排（点击看详情）
 * 全站 HTTPS，无“本地节点”、无独立“链路”页。
 */
(function () {
'use strict';

var state = {
  token: localStorage.getItem('hive_token') || '',
  view: 'project', group: '', groups: [], projects: [], project: '',
  cursor: 0, seen: {}, liveTimer: null, pollTimer: null,
  sideLayer: 'ticket', flow: null, idle: null,
  navDepth: 0, booted: false, modalStack: [],
};

function $(id) { return document.getElementById(id); }
function esc(s) {
  return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}
function toast(msg, kind) {
  var el = $('toast'); el.textContent = msg; el.className = 'toast ' + (kind || '');
  clearTimeout(el._t); el._t = setTimeout(function () { el.className = 'toast hidden'; }, 2800);
}
function hide(id) { var e = $(id); if (e) e.classList.add('hidden'); }
function show(id) { var e = $(id); if (e) e.classList.remove('hidden'); }

// ---------------- 路由 / 返回（PC + 安卓一致） ----------------
// 路由只用 hash，不依赖 History API 的服务端回退：刷新后仍能回到同一个项目/工单。
function enc(v) { return encodeURIComponent(v || ''); }
function dec(v) { try { return decodeURIComponent(v || ''); } catch (e) { return v || ''; } }
function routeOfHash() {
  var raw = String(location.hash || '').replace(/^#\/?/, '');
  var parts = raw.split('/');
  var type = parts[0] || 'project';
  if (type === 'project') {
    if (parts[2] === 'source') return { type: 'overlay', tab: 'source', project: dec(parts[1]),
      path: dec(parts.slice(3).join('/')) };
    if (parts[2] === 'idle') return { type: 'overlay', tab: 'idle', project: dec(parts[1]) };
    return { type: 'project', id: dec(parts[1]) };
  }
  if (type === 'chat') {
    if (parts[2] === 'artifacts') return { type: 'overlay', tab: 'artifacts', group: dec(parts[1]) };
    if (parts[2] === 'artifact') return { type: 'overlay', tab: 'artifact', group: dec(parts[1]),
      path: dec(parts.slice(3).join('/')) };
    if (parts[2] === 'fork') return { type: 'overlay', tab: 'fork', group: dec(parts[1]) };
    return { type: 'chat', id: dec(parts[1] || '') };
  }
  if (type === 'library') return { type: 'overlay', tab: 'library', kind: parts[1] || 'roles' };
  if (type === 'health' || type === 'versions') return { type: 'overlay', tab: type };
  return { type: 'project', id: dec(parts[1] || '') };
}
function hashOfView() {
  if (state.view === 'project') return '#/project/' + enc(state.project);
  return '#/chat/' + enc(state.group || '');
}
function pushHash(hash) {
  if (!hash || location.hash === hash) return;
  try { history.pushState({ hive: hash }, '', hash); state.navDepth += 1; } catch (e) { location.hash = hash; }
}
function replaceHash(hash) {
  if (!hash) return;
  try { history.replaceState({ hive: hash }, '', hash); } catch (e) { /* 老浏览器忽略 */ }
}
function isOverlayHash() {
  var r = routeOfHash(); return r.type === 'overlay';
}
function currentOverlay() {
  var m = $('modal'); return m && !m.classList.contains('hidden') ? $('modal-title').textContent : '';
}
function updateBackBtn() {
  var b = $('btn-back'); if (!b) return;
  var atHome = state.view === 'project' && !state.project;
  var overlay = currentOverlay();
  b.classList.toggle('hidden', atHome && !overlay && $('side').classList.contains('hidden'));
}
function goBack() {
  // 优先级：弹窗（含弹窗栈）-> 交付件侧栏 -> 抽屉 -> 历史栈 -> 层级回退
  if (currentOverlay()) { closeModal(); return; }
  if (!$('side').classList.contains('hidden')) { hide('side'); updateBackBtn(); return; }
  if ($('rail').classList.contains('open')) { toggleRail(false); return; }
  if (state.navDepth > 0) { history.back(); return; }
  var pid = state.view === 'project' ? state.project : ((findGroup(state.group) || {}).project || state.project);
  if (state.view === 'chat' && state.group.indexOf('T-') === 0 && pid) {
    openProject(pid, true, { replace: true }); return;
  }
  if (state.view === 'project') { toast('已经是最外层了', 'warn'); return; }
  if (state.view === 'chat') {
    var pid2 = (findGroup(state.group) || {}).project || state.project;
    if (pid2) openProject(pid2, true, { replace: true });
    return;
  }
  toast('已经是最外层了', 'warn');
}
function setTab(name) {
  document.querySelectorAll('.tab').forEach(function (x) { x.classList.toggle('active', x.dataset.tab === name); });
}

function api(path, opts) {
  opts = opts || {};
  var headers = { 'Accept': 'application/json' };
  if (state.token) headers['X-Auth-Token'] = state.token;
  var init = { method: opts.method || 'GET', headers: headers, credentials: 'same-origin' };
  if (opts.body !== undefined) { headers['Content-Type'] = 'application/json'; init.body = JSON.stringify(opts.body); }
  return fetch(path, init).then(function (r) {
    return r.text().then(function (txt) {
      var body = {};
      try { body = txt ? JSON.parse(txt) : {}; } catch (e) { body = { raw: txt }; }
      if (r.status === 401) { state.token = ''; localStorage.removeItem('hive_token'); showLogin(); throw new Error('未登录'); }
      if (!r.ok) {
        var err = new Error(body.error || body.message || ('HTTP ' + r.status));
        err.code = body.code; err.status = r.status; err.body = body; throw err;
      }
      return body;
    });
  });
}

// ---------------- Markdown ----------------
function inline(s) {
  s = esc(s);
  s = s.replace(/`([^`]+)`/g, '<code>$1</code>');
  s = s.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  s = s.replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<em>$2</em>');
  s = s.replace(/\[([^\]]+)\]\((https?:[^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
  return s;
}
function md(src) {
  if (!src) return '';
  var text = String(src).replace(/\r\n/g, '\n');
  // 先把围栏代码块整体摘出来，避免代码里的空行/竖线被当成普通 Markdown
  var codes = [];
  text = text.replace(/```([^\n]*)\n([\s\S]*?)```/g, function (m, lang, body) {
    codes.push(body.replace(/\n$/, ''));
    return '\n\n@@CODE' + (codes.length - 1) + '@@\n\n';
  });
  // 未闭合的围栏也按代码块处理，直到文件结尾
  text = text.replace(/```([^\n]*)\n([\s\S]*)$/g, function (m, lang, body) {
    codes.push(body.replace(/\n$/, ''));
    return '\n\n@@CODE' + (codes.length - 1) + '@@\n\n';
  });
  var blocks = text.split(/\n{2,}/), out = [];
  blocks.forEach(function (block) {
    var m = block.match(/^@@CODE(\d+)@@$/);
    if (m) { out.push('<pre class="code"><code>' + esc(codes[Number(m[1])] || '') + '</code></pre>'); return; }
    var lines = block.split('\n');
    if (lines.length >= 2 && /\|/.test(lines[0]) && /^\s*\|?[\s:|-]+\|?\s*$/.test(lines[1])) {
      var head = lines[0].replace(/^\s*\|/, '').replace(/\|\s*$/, '').split('|');
      var rows = lines.slice(2);
      var h = '<table class="md-table"><tr>' + head.map(function (c) { return '<th>' + inline(c.trim()) + '</th>'; }).join('') + '</tr>';
      rows.forEach(function (r) {
        var cells = r.replace(/^\s*\|/, '').replace(/\|\s*$/, '').split('|');
        h += '<tr>' + cells.map(function (c) { return '<td>' + inline(c.trim()) + '</td>'; }).join('') + '</tr>';
      });
      out.push(h + '</table>'); return;
    }
    var hd;
    if ((hd = block.match(/^(#{1,4})\s+(.*)$/))) { var lv = hd[1].length + 1; out.push('<h' + lv + '>' + inline(hd[2]) + '</h' + lv + '>'); return; }
    if (/^\s*([-*]|\d+\.)\s+/.test(block)) {
      var ordered = /^\s*\d+\./.test(block);
      var items = lines.filter(function (l) { return /^\s*([-*]|\d+\.)\s+/.test(l); })
        .map(function (l) { return '<li>' + inline(l.replace(/^\s*([-*]|\d+\.)\s+/, '')) + '</li>'; });
      out.push('<' + (ordered ? 'ol' : 'ul') + '>' + items.join('') + '</' + (ordered ? 'ol' : 'ul') + '>'); return;
    }
    if (/^>\s?/.test(block)) { out.push('<blockquote>' + inline(block.replace(/^>\s?/gm, '')) + '</blockquote>'); return; }
    out.push('<p>' + inline(block).replace(/\n/g, '<br>') + '</p>');
  });
  return out.join('');
}

// ---------------- 头像 ----------------
var PALETTE = ['#3b82f6', '#8b5cf6', '#0ea5e9', '#10b981', '#f59e0b', '#ef4444', '#ec4899', '#14b8a6', '#6366f1', '#84cc16'];
var AVATARS = ['🦊', '🐼', '🐧', '🦉', '🐯', '🐸', '🐨', '🦁', '🐺', '🐹', '🐰', '🐵'];
function avatar(name) {
  name = name || '?';
  var h = 0; for (var i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) & 0xffffffff;
  var c = PALETTE[Math.abs(h) % PALETTE.length];
  // 每个发言人一个稳定的卡通头像（不依赖外部图片，CSP 下也能显示）
  var face = name === '我' ? '🙂' : AVATARS[Math.abs(h) % AVATARS.length];
  return '<span class="avatar" style="background:' + c + '">' + esc(face) + '</span>';
}
function fmtTime(ts) {
  if (!ts) return '';
  var d = new Date(ts * 1000);
  return String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0');
}
function fmtBytes(n) {
  if (!n) return '0 B'; var u = ['B', 'KB', 'MB', 'GB'], i = 0;
  while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
  return (n < 10 && i > 0 ? n.toFixed(1) : Math.round(n)) + ' ' + u[i];
}

// ---------------- 登录 ----------------
function showLogin() {
  // 401 后必须停掉轮询，否则后台会每 0.9/5 秒继续 401
  clearInterval(state.pollTimer); clearInterval(state.liveTimer);
  state.pollTimer = null; state.liveTimer = null;
  hide('app'); show('login');
}
function doLogin() {
  var pw = $('password').value; if (!pw) return;
  $('login-err').textContent = '';
  api('/api/auth/login', { method: 'POST', body: { password: pw } }).then(function (r) {
    state.token = r.token; localStorage.setItem('hive_token', r.token); enterApp();
  }).catch(function (e) { $('login-err').textContent = e.status === 401 ? '密码不对' : (e.message || '登录失败'); });
}
function enterApp() {
  hide('login'); show('app'); applyRailPref(); loadGroups(true); loadIdle(); startPolling();
}
function applyRailPref() {
  var collapsed = localStorage.getItem('hive_rail_collapsed') === '1';
  if (window.innerWidth > 900) document.body.classList.toggle('rail-collapsed', collapsed);
}

// ---------------- 侧栏 / 项目 ----------------
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
  api('/api/projects/' + encodeURIComponent(pid)).then(function (r) {
    renderProject(r.project || {});
  }).catch(function (e) { toast('项目读取失败：' + e.message, 'err'); });
}
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

// ---------------- 会话 ----------------
function selectGroup(id, silent, opts) {
  opts = opts || {};
  if (!id || id === 'secretary' || (!findGroup(id) && !(id.indexOf('sec-') === 0 && findProject(id.slice(4))))) {
    toast('会话不存在：' + id, 'warn');
    var pd = state.projects[0]; if (pd) openProject(pd.id, true, { replace: true });
    return;
  }
  var prevGroup = state.group;
  // 从 hash 路由返回同一会话时保留交付件侧栏；切换会话或用户主动点击才关闭
  var keepSide = !!(opts.fromRoute && prevGroup === id);
  state.view = 'chat'; state.group = id; state.cursor = 0; state.seen = {}; state.lastLive = '';
  hide('projectview'); show('chatview'); hide('flow');
  if (!keepSide) hide('side');
  closeModal({ silent: true });
  $('messages').innerHTML = '';
  $('rail').classList.remove('open'); $('rail-mask').classList.remove('show');
  renderProjects(); renderRailGroups(); setTab('');
  if (!opts.fromRoute) {
    var h = '#/chat/' + enc(id);
    if (opts.replace) replaceHash(h); else pushHash(h);
  }
  updateBackBtn();
  var g = findGroup(id) || {};
  var isTicket = id.indexOf('T-') === 0;
  var isSec = id.indexOf('sec-') === 0;
  $('chat-title').textContent = isTicket ? (g.title || id) : ('项目秘书·' + (isSec ? id.slice(4) : ''));
  $('chat-sub').textContent = isTicket ? ('工单群 · ' + (g.project || '') + ' · ' + (g.backend || 'api') +
    (g.kind === 'retrospective' ? ' · 回顾迭代' : '') + (g.trace_enabled ? ' · trace on' : ' · trace off（只有系统事件）')) : '项目秘书';
  $('chat-tags').innerHTML = '';
  if (isTicket) {
    show('btn-copy-ticket'); $('btn-copy-ticket').textContent = '⧉ ' + id; show('btn-fork-ticket');
    if ((g.status || '') !== 'closed' && (g.status || '') !== 'closing') show('btn-addtag'); else hide('btn-addtag');
    loadTags(); loadFlow();
  } else {
    hide('btn-copy-ticket'); hide('btn-fork-ticket'); hide('btn-addtag'); hide('flow');
  }
  $('readonly-tip').classList.add('hidden');
  $('input').disabled = false; $('send').disabled = false;
  loadTimeline(silent); loadLive();
}

function loadTimeline(silent) {
  var url = '/api/web/timeline?group=' + encodeURIComponent(state.group) + '&limit=240';
  return api(url).then(function (r) {
    var box = $('messages');
    var atBottom = box.scrollTop + box.clientHeight >= box.scrollHeight - 40;
    var modBuf = [];
    function flushMods() {
      if (!modBuf.length) return;
      var d = document.createElement('details');
      d.className = 'modgroup';
      d.innerHTML = '<summary>执行过程 · ' + modBuf.length + ' 条模块报文（点开看完整内容）</summary>';
      var earliest = modBuf[0].ts;
      modBuf.forEach(function (x) { d.appendChild(renderModuleMsg(x)); });
      // trace 开关在创建工单时决定；不在群聊里追加“查看更早报文”入口。
      box.appendChild(d); modBuf = [];
    }
    (r.items || []).forEach(function (m) {
      var key = (m.session || '') + '|' + (m.ts || 0) + '|' + (m.kind || '') + '|' + (m.speaker || '') + '|' + String(m.text || '').slice(0, 24);
      if (state.seen[key]) return; state.seen[key] = 1;
      if (m.type === 'module') { modBuf.push(m); return; }
      flushMods();
      box.appendChild(renderMsg(m));
    });
    flushMods();
    if (atBottom || !silent) box.scrollTop = box.scrollHeight;
  }).catch(function () {});
}

function renderMsg(m) {
  if (m.type === 'module') return renderModuleMsg(m);
  var el = document.createElement('div');
  var mine = m.role === 'user' && m.speaker === '我';
  el.className = 'msg ' + (mine ? 'mine' : 'other') + (m.type === 'task' ? ' taskmsg' : '') + (m.type === 'system' ? ' systemmsg' : '');
  var who = m.type === 'task' ? (m.speaker + ' → ' + (m.to || '角色')) : (m.speaker || '?');
  var tools = (m.tools && m.tools.length) ? '<div class="tools">' + m.tools.map(function (t) { return '<span class="toolchip">' + esc(t) + '</span>'; }).join('') + '</div>' : '';
  var arts = (m.artifacts && m.artifacts.length) ? '<div class="msg-arts">' + m.artifacts.map(function (a) {
    return '<button class="artifact-chip" data-art="' + esc(JSON.stringify(a)) + '">📎 ' + esc(a.path || '') + '</button>';
  }).join('') + '</div>' : '';
  el.innerHTML = (mine ? '' : avatar(who)) +
    '<div class="bubble"><div class="meta"><span class="who">' + esc(who) + '</span>' +
    '<span class="muted small">' + fmtTime(m.ts) + '</span>' + (m.type === 'task' ? '<span class="tag">派活</span>' : '') + '</div>' +
    '<div class="body">' + (mine ? '<p>' + esc(m.text).replace(/\n/g, '<br>') + '</p>' : md(m.text)) + '</div>' + tools + arts + '</div>' +
    (mine ? avatar('我') : '');
  el.querySelectorAll('.artifact-chip').forEach(function (b) {
    b.onclick = function () {
      var a = {}; try { a = JSON.parse(b.dataset.art || '{}'); } catch (e) { a = {}; }
      var g = findGroup(state.group) || {};
      state.sideLayer = a.layer || 'ticket';
      openArtifact(a.path || '', g.project || state.project, true, a.layer || 'ticket');
    };
  });
  return el;
}

function renderModuleMsg(m) {
  var el = document.createElement('div');
  el.className = 'msg modulemsg';
  var icon = m.speaker === 'LLM' ? 'λ' : (m.speaker === '工具' ? '⚙' : (m.speaker === '总线' ? '⇄' : (m.speaker === '通信' ? '✉' : '▦')));
  el.innerHTML = '<span class="mod-avatar">' + esc(icon) + '</span>' +
    '<div class="mod-bubble" title="点击查看完整报文">' +
    '<div class="meta"><span class="who">模块·' + esc(m.speaker || '?') + '</span>' +
    '<span class="muted small">' + fmtTime(m.ts) + ' · ' + esc(m.kind || '') + '</span></div>' +
    '<div class="body">' + esc(m.text || '') + '</div></div>';
  el.querySelector('.mod-bubble').onclick = function () {
    openModal('模块报文 · ' + (m.speaker || '') + ' · ' + (m.kind || ''),
      '<div class="muted small">session=' + esc(m.session || '') + '</div><pre class="raw">' +
      esc(JSON.stringify(m.payload || {}, null, 2)) + '</pre>');
  };
  return el;
}

// ---------------- 编排流程（并行 + 点击详情） ----------------
function loadFlow() {
  return api('/api/tickets/' + encodeURIComponent(state.group) + '/flow').then(function (r) {
    state.flow = r; renderFlow(r);
    if (r.readonly) { show('readonly-tip'); $('input').disabled = true; $('send').disabled = true; }
  }).catch(function () {});
}
function renderFlow(f) {
  var box = $('flow'); box.classList.remove('hidden');
  var cur = firstOpen(f.nodes);
  var nodes = (f.nodes || []).map(function (n, i) {
    var cls = 'fn' + (n.done ? ' done' : '') + (i === cur ? ' current' : '');
    return '<div class="' + cls + '" data-i="' + i + '"><span class="fdot"></span><span class="flabel">' + esc(n.label) + '</span></div>';
  }).join('<span class="farrow">›</span>');
  var branches = ((f.parallel_stage || {}).branches || []).map(function (b) {
    return '<div class="branch" data-s="' + esc(b.id) + '"><span class="bdot ' + esc(b.state || '') + '"></span>' +
      '<span class="blabel">' + esc(b.label) + '</span><span class="muted small">' + esc(stateLabel(b.state)) + '</span></div>';
  }).join('');
  box.innerHTML = '<div class="flowline">' + nodes + '</div>' +
    (branches ? '<div class="parallel"><div class="ptitle">PM 并行编排 <span class="muted small">（点角色看任务/状态）</span></div>' +
      '<div class="branches">' + branches + '</div></div>' : '');
  box.querySelectorAll('.fn').forEach(function (el) {
    el.onclick = function () {
      var n = f.nodes[Number(el.dataset.i)];
      openModal(n.label, '<div class="muted small">' + esc(n.key) + ' · ' + (n.done ? '已完成' : '未完成') + '</div>' +
        '<div class="rawbox">' + esc(n.detail || '（无详情）') + '</div>');
    };
  });
  box.querySelectorAll('.branch').forEach(function (el) {
    el.onclick = function () {
      var r = (f.roles || []).filter(function (x) { return x.session === el.dataset.s; })[0] || {};
      openModal('角色 · ' + (r.display || r.role || ''),
        '<div class="muted small">session=' + esc(r.session || '') + ' · 状态=' + esc(r.state || '') + '</div>' +
        '<div class="rawbox"><b>任务</b>\n' + esc(r.task || '') + '\n\n<b>回报</b>\n' + esc(r.reply || '') + '</div>');
    };
  });
}
function firstOpen(nodes) {
  nodes = nodes || []; for (var i = 0; i < nodes.length; i++) if (!nodes[i].done) return i;
  return nodes.length - 1;
}

// ---------------- 标签 ----------------
function loadTags() {
  api('/api/tickets/' + encodeURIComponent(state.group)).then(function (r) {
    var tags = (r.ticket || {}).tags || [];
    $('chat-tags').innerHTML = tags.map(function (t) {
      var st = (r.ticket || {}).status || (findGroup(state.group) || {}).status;
      var lock = st === 'closed' || st === 'closing';
      return '<span class="tagchip">' + esc(t) + (lock ? '' : '<button data-t="' + esc(t) + '">×</button>') + '</span>';
    }).join('') || '<span class="muted small">无标签</span>';
    $('chat-tags').querySelectorAll('button').forEach(function (b) {
      b.onclick = function (e) {
        e.stopPropagation();
        api('/api/tickets/' + encodeURIComponent(state.group) + '/tags', { method: 'POST', body: { remove: [b.dataset.t] } })
          .then(function () { loadTags(); }).catch(function (er) { toast(er.message, 'err'); });
      };
    });
  }).catch(function () {});
}
function addTag() {
  var t = prompt('给工单加标签（如 frontend/backend/comm/docs）');
  if (!t) return;
  api('/api/tickets/' + encodeURIComponent(state.group) + '/tags', { method: 'POST', body: { add: [t] } })
    .then(function () { toast('已加标签'); loadTags(); }).catch(function (e) { toast(e.message, 'err'); });
}

// ---------------- 直播 / 发送 ----------------
function loadLive() {
  api('/api/web/live?group=' + encodeURIComponent(state.group) + '&limit=12').then(function (r) {
    var running = r.running || [];
    if (!running.length) { hide('livebar'); return; }
    var top = running[0], txt = (top.partial || '').slice(-1200);
    if (txt) {
      show('livebar');
      $('live-who').textContent = (top.display || top.session) + ' 正在说…' + (top.step ? '（第 ' + top.step + ' 步）' : '');
      $('live-body').innerHTML = md(txt) + '<span class="caret"></span>';
      $('live-body').scrollTop = $('live-body').scrollHeight;
      $('btn-interrupt').onclick = function () { interrupt(top.session); };
    } else hide('livebar');
  }).catch(function () {});
}
function interrupt(session) {
  if (!confirm('打断 ' + session + ' 当前的这次发言？')) return;
  api('/api/sessions/' + encodeURIComponent(session) + '/interrupt', { method: 'POST', body: {} })
    .then(function () { toast('已发送打断'); hide('livebar'); }).catch(function (e) { toast('打断失败：' + e.message, 'err'); });
}
function send() {
  var input = $('input'), text = input.value.trim();
  if (!text) return;
  input.value = ''; input.style.height = 'auto';
  api('/api/chat/send', { method: 'POST', body: { text: text, group: state.group, force: $('force-now').checked } })
    .then(function (r) {
      if (r.status === 'queued') toast('高峰排队中，空闲时自动发送', 'warn');
      loadTimeline(true); setTimeout(function () { loadTimeline(true); loadLive(); loadIdle(); }, 900);
    })
    .catch(function (e) {
      if (e.status === 410) { show('readonly-tip'); toast('工单已结单，只读；请基于此单新开', 'warn'); }
      else toast('发送失败：' + e.message, 'err');
    });
}

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
function bindProjectSource() {
  var pid = state.project; if (!pid) return;
  var p = findProject(pid) || {};
  var path = prompt('绑定源码目录绝对路径（空=解绑）', p.source_path || '');
  if (path === null) return;
  api('/api/projects/' + encodeURIComponent(pid) + '/source', { method: 'POST', body: { path: path } })
    .then(function (r) { toast(r.bound ? '源码已绑定' : '已解绑源码'); openProject(pid, true); })
    .catch(function (e) { toast('绑定失败：' + e.message, 'err'); });
}
function saveProjectBackend() {
  var pid = state.project; if (!pid) return;
  if ($('pv-backend').value === 'claude-code' && state.backendAvailable === false) {
    toast('claude-code 在本机不可用，不能保存为项目默认后端', 'err'); return;
  }
  api('/api/projects/' + encodeURIComponent(pid) + '/backend', { method: 'POST', body: { backend: $('pv-backend').value } })
    .then(function () { toast('项目默认后端已保存'); openProject(pid, true); })
    .catch(function (e) { toast('保存失败：' + e.message, 'err'); });
}
function openApiConfig() {
  api('/api/ops/config').then(function (r) {
    var cfg = r.config || r || {};
    var llm = cfg.llm || {};
    openModal('API 配置（只读，改配置走 git）', '<div class="rawbox">' +
      esc('provider: ' + (llm.provider || '') + '\nbase_url: ' + (llm.base_url || '') + '\nmodel: ' + (llm.model || '') +
        '\napi_key: ' + (llm.api_key_present ? '已配置（已隐藏）' : '未配置') +
        '\nclaude-code command: ' + (((cfg.agents || {}).claude_code || {}).command || '') +
        '\n\n后端: ' + JSON.stringify(cfg.sessions || {})) +
      '</div><div class="muted small">网页不直接编辑配置；改 config/config.json 后走部署流程。</div>');
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

// ---------------- 弹窗 / 库 / 健康 / 版本 ----------------
function openModal(title, html, opts) {
  opts = opts || {};
  var visible = !$('modal').classList.contains('hidden');
  if (opts.root) state.modalStack = [];
  else if (visible) state.modalStack.push({
    title: $('modal-title').textContent,
    html: $('modal-body').innerHTML,
    back: opts.back || null
  });
  $('modal-title').textContent = title;
  $('modal-body').innerHTML = html;
  show('modal'); updateBackBtn();
}
function closeModal(opts) {
  opts = opts || {};
  if (!opts.silent && state.modalStack.length) {
    var prev = state.modalStack.pop();
    if (prev.back) { prev.back(); }
    else { $('modal-title').textContent = prev.title; $('modal-body').innerHTML = prev.html; show('modal'); }
    updateBackBtn();
    return;
  }
  hide('modal');
  if (!opts.silent) {
    state.modalStack = [];
    // 深链直接打开 #/health 时 navDepth=0，不能 history.back 到浏览器外部
    if (isOverlayHash()) {
      if (state.navDepth > 0) history.back();
      else replaceHash(hashOfView());
    }
  }
  updateBackBtn();
}

function overlayRoute(hash, tab) {
  setTab(tab);
  if (isOverlayHash()) replaceHash(hash); else pushHash(hash);
  updateBackBtn();
}

function openLibrary(kind, opts) {
  opts = opts || {};
  kind = kind || 'roles';
  var kinds = [['roles', '角色'], ['flows', '流程'], ['skills', '技能']];
  var skillbar = kind === 'skills' ? ('<div class="skillbar">' +
    '<div class="muted small">从本地目录或 GitHub tree / raw SKILL.md 安装；装完可拆成“角色+技能+流程”。</div>' +
    '<div class="row-btns" style="justify-content:flex-start;margin-top:6px">' +
    '<input id="skill-src" placeholder="GitHub tree URL / raw SKILL.md / 本地目录">' +
    '<select id="skill-backend"><option value="api">api</option><option value="claude-code">claude-code</option></select>' +
    '<button id="skill-install" class="primary">安装 Skill</button>' +
    '<button id="skill-decompose-last">装好后拆解</button></div>' +
    '<div id="skill-examples" class="muted small"></div></div>') : '';
  var tabs = '<div class="seg">' + kinds.map(function (k) {
    return '<button data-kind="' + k[0] + '" class="' + (kind === k[0] ? 'on' : '') + '">' + k[1] + '库</button>';
  }).join('') + '</div>' + skillbar + '<div id="libbody" class="libbody"></div>' +
    '<h4>标签库（公共 / 项目）</h4><div id="tagbody" class="muted small">加载中…</div>';
  openModal('可插拔能力库', tabs, { root: true });
  if (!opts.fromRoute) overlayRoute('#/library/' + kind, 'library');
  document.querySelectorAll('#modal-body .seg button').forEach(function (b) { b.onclick = function () { openLibrary(b.dataset.kind); }; });
  var libProject = state.project || ((findGroup(state.group) || {}).project || '');
  api('/api/library/tags?project=' + encodeURIComponent(libProject)).then(function (t) {
    $('tagbody').innerHTML = '公共: ' + ((t.public || []).join(', ') || '空') + '<br>项目: ' + ((t.project || []).join(', ') || '空');
  }).catch(function () {});

  function renderSkills(installed) {
    var box = $('libbody'); if (!box) return;
    var items = installed || [];
    box.innerHTML = items.map(function (it, i) {
      var badge = it.decomposed ? '<span class="tag">已拆解</span>' : '<span class="tag">未拆解</span>';
      return '<div class="libcard" data-i="' + i + '"><div class="libtitle">' + esc(it.name || it.id) + badge +
        '</div><div class="muted small">' + esc(it.id) + ' · ' + esc(it.source_type || '') + ' · ' +
        esc((it.assets || []).length) + ' 个资源</div>' +
        '<div class="row-btns" style="justify-content:flex-start;margin-top:6px">' +
        '<button class="mini" data-act="decompose" data-id="' + esc(it.id) + '">' + (it.decomposed ? '重新拆解' : '拆成角色+流程') + '</button>' +
        '<button class="mini" data-act="detail" data-id="' + esc(it.id) + '">详情</button>' +
        '<button class="mini" data-act="remove" data-id="' + esc(it.id) + '">移除</button></div></div>';
    }).join('') || '<div class="empty">还没有安装 Skill。可以从上面的示例一键安装。</div>';
    box.querySelectorAll('button[data-act]').forEach(function (b) {
      b.onclick = function (e) {
        e.stopPropagation();
        var act = b.dataset.act, id = b.dataset.id;
        if (act === 'detail') {
          api('/api/skills/item?id=' + encodeURIComponent(id)).then(function (r) {
            openModal(id + ' · Skill', '<pre class="raw">' + esc(JSON.stringify(r.skill || {}, null, 2)) + '</pre>',
              { back: function () { openLibrary('skills'); } });
          }).catch(function (e2) { toast('读取 Skill 失败：' + e2.message, 'err'); });
        } else if (act === 'decompose') {
          decomposeSkill(id);
        } else if (act === 'remove') {
          if (!confirm('移除 Skill ' + id + '？')) return;
          api('/api/skills/remove', { method: 'POST', body: { id: id } }).then(function () {
            toast('已移除 ' + id); openLibrary('skills');
          }).catch(function (e2) { toast('移除失败：' + e2.message, 'err'); });
        }
      };
    });
  }

  if (kind === 'skills') {
    api('/api/skills/installed').then(function (r) { renderSkills(r.items || []); })
      .catch(function (e) { var b = $('libbody'); if (b) b.innerHTML = '<div class="err">' + esc(e.message) + '</div>'; });
    api('/api/skills/sources').then(function (r) {
      var ex = $('skill-examples'); if (!ex) return;
      ex.innerHTML = '来源: ' + (r.sources || []).map(function (s) { return esc(s.name); }).join(' · ') +
        '<br>示例: ' + (r.examples || []).map(function (x) { return '<button class="mini" data-src="' + esc(x.source) + '">' + esc(x.name) + '</button>'; }).join(' ');
      ex.querySelectorAll('button[data-src]').forEach(function (b) {
        b.onclick = function () { var inp = $('skill-src'); if (inp) inp.value = b.dataset.src; };
      });
    }).catch(function () {});
    var installBtn = $('skill-install');
    if (installBtn) installBtn.onclick = function () {
      var src = ($('skill-src') || {}).value || '';
      if (!src.trim()) { toast('请填来源', 'err'); return; }
      installBtn.disabled = true; installBtn.textContent = '安装中…';
      api('/api/skills/install', { method: 'POST', body: { source: src.trim(), decompose: false, backend: ($('skill-backend') || {}).value || 'api' } })
        .then(function (r) { toast('已安装 ' + (r.skill || {}).id); openLibrary('skills'); })
        .catch(function (e) { toast('安装失败：' + e.message, 'err'); installBtn.disabled = false; installBtn.textContent = '安装 Skill'; });
    };
    var lastBtn = $('skill-decompose-last');
    if (lastBtn) lastBtn.onclick = function () {
      var src = ($('skill-src') || {}).value || '';
      if (!src.trim()) { toast('请先填来源', 'err'); return; }
      lastBtn.disabled = true; lastBtn.textContent = '安装并拆解…';
      api('/api/skills/install', { method: 'POST', body: { source: src.trim(), decompose: true, backend: ($('skill-backend') || {}).value || 'api' } })
        .then(function (r) { toast('已安装并拆解 ' + (r.skill || {}).id); openLibrary('skills'); })
        .catch(function (e) { toast('安装/拆解失败：' + e.message, 'err'); lastBtn.disabled = false; lastBtn.textContent = '装好后拆解'; });
    };
  } else {
    api('/api/library/list?kind=' + kind).then(function (r) {
      var box = $('libbody'); if (!box) return;
      box.innerHTML = (r.items || []).filter(function (it) { return it.installed !== false; }).map(function (it, i) {
        var sub = kind === 'roles' ? (it.responsibility || '') : kind === 'flows' ? ((it.checks || []).map(function (c) { return c.path || c.must || JSON.stringify(c); }).join(' · ')) : (it.body || '').slice(0, 80);
        return '<div class="libcard" data-i="' + i + '"><div class="libtitle">' + esc(it.cn || it.name || it.id) +
          (it.builtin ? '<span class="tag">内置</span>' : '') + (it.backend ? '<span class="tag">' + esc(it.backend) + '</span>' : '') +
          '</div><div class="muted small">' + esc(it.id) + ' · ' + esc(sub) + '</div></div>';
      }).join('') || '<div class="empty">空</div>';
      box.querySelectorAll('.libcard').forEach(function (c) {
        c.onclick = function () {
          var it = r.items.filter(function (x) { return x.installed !== false; })[Number(c.dataset.i)];
          openModal((it.cn || it.id) + ' · ' + kind, '<pre class="raw">' + esc(JSON.stringify(it, null, 2)) + '</pre>',
            { back: function () { openLibrary(kind); } });
        };
      });
    }).catch(function (e) { var b = $('libbody'); if (b) b.innerHTML = '<div class="err">' + esc(e.message) + '</div>'; });
  }
}

function decomposeSkill(id) {
  api('/api/skills/decompose', { method: 'POST', body: { id: id } })
    .then(function (r) {
      if (r.existing) { toast('角色 ' + r.role + ' 已存在，未覆盖'); return; }
      toast('已拆解：' + id + ' -> 角色 ' + r.role);
      openLibrary('skills');
    }).catch(function (e) { toast('拆解失败：' + e.message, 'err'); });
}

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

// ---------------- 固定命令 ----------------
function restartAgent() {
  if (!confirm('重启 agent 进程？（watchdog 会立刻拉起）')) return;
  api('/api/ops/restart', { method: 'POST', body: {} }).then(function () { toast('重启指令已下发'); }).catch(function (e) { toast(e.message, 'err'); });
}
function stopAll() {
  if (!confirm('彻底停止 watchdog + agent？\n之后只能通过 SSH 手动起。')) return;
  api('/api/ops/stop', { method: 'POST', body: {} }).then(function () { toast('停止指令已下发'); }).catch(function (e) { toast(e.message, 'err'); });
}

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
})();
