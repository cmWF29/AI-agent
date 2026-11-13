/* Hive Agent v4 控制台
 * 项目 -> 项目页（改名/工单/秘书/新建工单/文件）
 * 工单群聊：角色发言 + 模块报文（点击看完整 JSON）+ 并行编排（点击看详情）
 * 全站 HTTPS，无“本地节点”、无独立“链路”页。
 */
(function () {
'use strict';

var state = {
  token: localStorage.getItem('hive_token') || '',
  view: 'chat', group: 'secretary', groups: [], projects: [], project: '',
  cursor: 0, seen: {}, liveTimer: null, pollTimer: null,
  sideLayer: 'ticket', flow: null, idle: null,
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
  var blocks = String(src).replace(/\r\n/g, '\n').split(/\n{2,}/), out = [];
  blocks.forEach(function (block) {
    var lines = block.split('\n');
    if (/^```/.test(lines[0])) { out.push('<pre class="code"><code>' + esc(lines.slice(1).join('\n').replace(/```$/, '')) + '</code></pre>'); return; }
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
    var m;
    if ((m = block.match(/^(#{1,4})\s+(.*)$/))) { var lv = m[1].length + 1; out.push('<h' + lv + '>' + inline(m[2]) + '</h' + lv + '>'); return; }
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
function avatar(name) {
  name = name || '?';
  var h = 0; for (var i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) & 0xffffffff;
  var c = PALETTE[Math.abs(h) % PALETTE.length];
  var initials = name.replace(/·/g, '').slice(0, 2);
  return '<span class="avatar" style="background:' + c + '">' + esc(initials) + '</span>';
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
function showLogin() { hide('app'); show('login'); }
function doLogin() {
  var pw = $('password').value; if (!pw) return;
  $('login-err').textContent = '';
  api('/api/auth/login', { method: 'POST', body: { password: pw } }).then(function (r) {
    state.token = r.token; localStorage.setItem('hive_token', r.token); enterApp();
  }).catch(function (e) { $('login-err').textContent = e.status === 401 ? '密码不对' : (e.message || '登录失败'); });
}
function enterApp() { hide('login'); show('app'); loadGroups(true); loadIdle(); startPolling(); }

// ---------------- 侧栏 / 项目 ----------------
function loadGroups(first) {
  return api('/api/web/groups').then(function (r) {
    state.groups = r.items || []; state.projects = r.projects || [];
    renderProjects(); renderRailGroups();
    if (first && !state.groups.length) return;
    if (first) {
      if (state.project && findProject(state.project)) openProject(state.project, true);
      else selectGroup(state.group, true);
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
function renderRailGroups() {
  var box = $('groups'); box.innerHTML = '';
  var g = state.groups.filter(function (x) { return x.kind === 'secretary'; })[0];
  var el = document.createElement('div');
  el.className = 'group-row' + (state.view === 'chat' && state.group === 'secretary' ? ' active' : '');
  el.innerHTML = avatar('秘书') + '<div class="grow"><div class="gt">全局秘书</div><div class="muted small">判断需求、分单</div></div>';
  el.onclick = function () { selectGroup('secretary'); };
  box.appendChild(el);
}

function findProject(id) { for (var i = 0; i < state.projects.length; i++) if (state.projects[i].id === id) return state.projects[i]; return null; }
function findGroup(id) { for (var i = 0; i < state.groups.length; i++) if (state.groups[i].id === id) return state.groups[i]; return null; }

function openProject(pid, silent) {
  state.view = 'project'; state.project = pid;
  hide('chatview'); show('projectview'); hide('side');
  $('rail').classList.remove('open'); $('rail-mask').classList.remove('show');
  renderProjects();
  api('/api/projects/' + encodeURIComponent(pid)).then(function (r) {
    renderProject(r.project || {});
  }).catch(function (e) { toast('项目读取失败：' + e.message, 'err'); });
}
function renderProject(p) {
  $('pv-title').textContent = p.title || p.id;
  $('pv-sub').textContent = 'id=' + p.id + ' · 交付件 ' + (p.artifacts_root || '') + ' · 秘书 ' + (p.secretary || '');
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
        '<span class="status-chip ' + esc(t.status) + '">' + esc(t.status) + '</span>' +
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
function selectGroup(id, silent) {
  state.view = 'chat'; state.group = id; state.cursor = 0; state.seen = {}; state.lastLive = '';
  hide('projectview'); show('chatview'); hide('flow');
  $('messages').innerHTML = '';
  $('rail').classList.remove('open'); $('rail-mask').classList.remove('show');
  renderProjects(); renderRailGroups();
  var g = findGroup(id) || {};
  var isTicket = id.indexOf('T-') === 0;
  var isSec = id.indexOf('sec-') === 0;
  $('chat-title').textContent = isTicket ? (g.title || id) : (isSec ? ('项目秘书·' + id.slice(4)) : '秘书');
  $('chat-sub').textContent = isTicket ? ('工单群 · ' + (g.project || '')) : (isSec ? '项目秘书' : '全局秘书');
  $('chat-tags').innerHTML = '';
  if (isTicket) {
    show('btn-copy-ticket'); $('btn-copy-ticket').textContent = '⧉ ' + id; show('btn-fork-ticket');
    if ((g.status || '') !== 'closed') show('btn-addtag'); else hide('btn-addtag');
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
  if (state.group.indexOf('T-') === 0) url += '&modules=1';
  return api(url).then(function (r) {
    var box = $('messages');
    var atBottom = box.scrollTop + box.clientHeight >= box.scrollHeight - 40;
    var modBuf = [];
    function flushMods() {
      if (!modBuf.length) return;
      var d = document.createElement('details');
      d.className = 'modgroup';
      d.innerHTML = '<summary>执行过程 · ' + modBuf.length + ' 条模块报文（点开看完整内容）</summary>';
      modBuf.forEach(function (x) { d.appendChild(renderModuleMsg(x)); });
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
  el.className = 'msg ' + (mine ? 'mine' : 'other') + (m.type === 'task' ? ' taskmsg' : '');
  var who = m.type === 'task' ? (m.speaker + ' → ' + (m.to || '角色')) : (m.speaker || '?');
  var tools = (m.tools && m.tools.length) ? '<div class="tools">' + m.tools.map(function (t) { return '<span class="toolchip">' + esc(t) + '</span>'; }).join('') + '</div>' : '';
  el.innerHTML = (mine ? '' : avatar(who)) +
    '<div class="bubble"><div class="meta"><span class="who">' + esc(who) + '</span>' +
    '<span class="muted small">' + fmtTime(m.ts) + '</span>' + (m.type === 'task' ? '<span class="tag">派活</span>' : '') + '</div>' +
    '<div class="body">' + (mine ? '<p>' + esc(m.text).replace(/\n/g, '<br>') + '</p>' : md(m.text)) + '</div>' + tools + '</div>' +
    (mine ? avatar('我') : '');
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
      '<span class="blabel">' + esc(b.label) + '</span><span class="muted small">' + esc(b.state || '') + '</span></div>';
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
      var lock = (findGroup(state.group) || {}).status === 'closed';
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
  api('/api/idle/status').then(function (r) {
    state.idle = r;
    var el = $('idle-chip'), i = r.idle || {};
    el.textContent = (i.peak ? '高峰' : '空闲') + (r.queue ? ' · 排队 ' + r.queue : '');
    el.className = 'pill small idle ' + (i.peak ? 'peak' : 'off');
  }).catch(function () {});
}
function openIdle() {
  api('/api/idle/status').then(function (r) {
    var i = r.idle || {};
    var items = (r.queued || []).map(function (q) {
      return '<div class="file-row"><span>' + esc(q.kind) + ' · ' + esc(q.id) + '</span>' +
        '<span class="muted small">' + esc(q.note || '') + '</span></div>';
    }).join('') || '<div class="empty">队列为空</div>';
    openModal('空闲判断 · 需求排队',
      '<div class="muted small">' + esc(i.reason || '') + ' · 空闲折扣 ' + (r.discount || '') + ' · 窗口 ' + esc((r.windows || []).join(' / ')) + '</div>' +
      '<div class="filelist">' + items + '</div><div class="row-btns"><button class="primary" id="idle-flush">立即执行队列</button></div>');
    $('idle-flush').onclick = function () {
      api('/api/idle/flush', { method: 'POST', body: { force: true } }).then(function (x) {
        toast('已执行 ' + ((x.done || []).length) + ' 条'); closeModal(); loadIdle(); loadGroups();
      }).catch(function (e) { toast(e.message, 'err'); });
    };
  }).catch(function (e) { toast(e.message, 'err'); });
}

// ---------------- 侧栏：交付件 ----------------
function openSide() {
  show('side'); loadFiles();
}
function loadFiles() {
  var body = $('side-body');
  var isTicket = state.group.indexOf('T-') === 0;
  var g = findGroup(state.group) || {};
  var project = g.project || (state.group.indexOf('sec-') === 0 ? state.group.slice(4) : state.project);
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
      row.onclick = function () { openArtifact(row.dataset.path, project, isTicket); };
    });
  }).catch(function (e) { body.innerHTML = '<div class="err">' + esc(e.message) + '</div>'; });
}
function openArtifact(path, project, isTicket) {
  var q = '/api/artifacts/file?layer=' + state.sideLayer + '&project=' + encodeURIComponent(project) +
    '&ticket=' + encodeURIComponent(isTicket ? state.group : '') + '&path=' + encodeURIComponent(path);
  api(q).then(function (f) {
    openModal(path, f.encoding === 'utf-8' ? md(f.text) : '<div class="muted">二进制文件</div>');
  }).catch(function (e) { toast('打不开：' + e.message, 'err'); });
}

// ---------------- 文件浏览 ----------------
function openProjectFiles() {
  var pid = state.project; if (!pid) return;
  openModal('项目文件 · ' + pid, '<div id="ftree" class="muted">加载中…</div>');
  browseProject('', pid);
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
          .then(function (f) { openModal(row.dataset.p, f.encoding === 'utf-8' ? md(f.text) : '<div class="muted">二进制</div>'); })
          .catch(function (e) { toast(e.message, 'err'); });
      };
    });
  }).catch(function (e) { toast(e.message, 'err'); });
}
function openSource() {
  openModal('agent 源码 / 配置（只读）', '<div id="ftree" class="muted">加载中…</div>');
  browseSource('');
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
          .then(function (f) { openModal(row.dataset.p, md(f.text)); })
          .catch(function (e) { toast(e.message, 'err'); });
      };
    });
  }).catch(function (e) { toast(e.message, 'err'); });
}

// ---------------- 弹窗 / 库 / 健康 / 版本 ----------------
function openModal(title, html) { $('modal-title').textContent = title; $('modal-body').innerHTML = html; show('modal'); }
function closeModal() { hide('modal'); }

function openLibrary(kind) {
  kind = kind || 'roles';
  var kinds = [['roles', '角色'], ['flows', '流程'], ['skills', '技能']];
  var tabs = '<div class="seg">' + kinds.map(function (k) {
    return '<button data-kind="' + k[0] + '" class="' + (kind === k[0] ? 'on' : '') + '">' + k[1] + '库</button>';
  }).join('') + '</div><div id="libbody" class="libbody"></div>' +
    '<h4>标签库（公共 / 项目）</h4><div id="tagbody" class="muted small">加载中…</div>';
  openModal('可插拔能力库', tabs);
  document.querySelectorAll('#modal-body .seg button').forEach(function (b) { b.onclick = function () { openLibrary(b.dataset.kind); }; });
  api('/api/library/list?kind=' + kind).then(function (r) {
    var box = $('libbody');
    box.innerHTML = (r.items || []).map(function (it, i) {
      var sub = kind === 'roles' ? (it.responsibility || '') : kind === 'flows' ? ((it.checks || []).map(function (c) { return c.must || c; }).join(' · ')) : (it.body || '').slice(0, 80);
      return '<div class="libcard" data-i="' + i + '"><div class="libtitle">' + esc(it.cn || it.name || it.id) +
        (it.builtin ? '<span class="tag">内置</span>' : '') + '</div><div class="muted small">' + esc(it.id) + ' · ' + esc(sub) + '</div></div>';
    }).join('') || '<div class="empty">空</div>';
    box.querySelectorAll('.libcard').forEach(function (c) {
      c.onclick = function () { var it = r.items[Number(c.dataset.i)]; openModal((it.cn || it.id) + ' · ' + kind, '<pre class="raw">' + esc(JSON.stringify(it, null, 2)) + '</pre>'); };
    });
  }).catch(function (e) { $('libbody').innerHTML = '<div class="err">' + esc(e.message) + '</div>'; });
  api('/api/library/tags?project=' + encodeURIComponent(state.project || '')).then(function (t) {
    $('tagbody').innerHTML = '公共: ' + ((t.public || []).join(', ') || '空') + '<br>项目: ' + ((t.project || []).join(', ') || '空');
  }).catch(function () {});
}

function openHealth() {
  openModal('健康自检', '<div id="hbody" class="muted">检查中…</div>');
  Promise.all([api('/api/health/self'), api('/api/artifacts/stats'), api('/api/ops/status').catch(function () { return {}; })])
    .then(function (rs) {
      var h = rs[0] || {}, a = rs[1] || {}, s = rs[2] || {};
      var checks = (h.checks || []).map(function (c) {
        return '<div class="check ' + (c.ok ? 'ok' : 'bad') + '"><span class="dot"></span><div><div>' + esc(c.name) +
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
        '<h4>交付件体积（含所有层）</h4><div class="muted small">合计 ' + fmtBytes(a.total_bytes) + ' · 磁盘余量 ' + fmtBytes(a.disk_free) + '</div>' +
        '<div class="filelist">' + big + '</div>' +
        (a.need_compress ? '<div class="warnbox">交付件偏大，建议压缩归档</div>' : '') +
        '<div class="row-btns"><button class="ghost" id="btn-compress-all">压缩 7 天前工单</button></div>';
      var cb = $('btn-compress-all');
      if (cb) cb.onclick = function () {
        api('/api/artifacts/compress', { method: 'POST', body: { days: 7 } }).then(function (r) { toast('已压缩 ' + (r.compressed || []).length + ' 个'); openHealth(); })
          .catch(function (e) { toast(e.message, 'err'); });
      };
    }).catch(function (e) { $('hbody').innerHTML = '<div class="err">' + esc(e.message) + '</div>'; });
}
function openVersions() {
  openModal('版本管理', '<div id="vbody" class="muted">读取中…</div>');
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
  api('/api/projects/create', { method: 'POST', body: { name: name, title: name } })
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
  if (!confirm('删除项目「' + (p.title || p.id) + '」？\n只清理项目秘书会话；工单、交付件、知识保留。')) return;
  api('/api/projects/' + encodeURIComponent(p.id) + '/delete', { method: 'POST', body: {} })
    .then(function () { toast('项目已删除，证据保留'); state.project = ''; loadGroups(); selectGroup('secretary'); })
    .catch(function (e) { toast(e.message, 'err'); });
}
function compactProjectSecretary() {
  var sid = 'sec-' + state.project;
  api('/api/sessions/' + encodeURIComponent(sid) + '/compact', { method: 'POST', body: {} })
    .then(function (r) { toast('已压缩 ' + sid + '：' + String(r.summary || '').slice(0, 40)); })
    .catch(function (e) { toast('压缩失败：' + e.message, 'err'); });
}
function createTicket() {
  var goal = $('pv-newgoal').value.trim(); if (!goal) { toast('目标不能空', 'warn'); return; }
  var tags = $('pv-newtags').value.split(/[,，\s]+/).filter(Boolean);
  api('/api/tickets/create', { method: 'POST', body: {
    title: $('pv-newtitle').value.trim(), goal: goal, project: state.project, tags: tags,
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
    '<label class="checkline"><input type="checkbox" id="tk-now" /> 立即执行</label>' +
    '<div class="row-btns"><button class="primary" id="tk-create">派给项目经理</button></div>');
  var def = (findGroup(state.group) || {}).project || state.project;
  if (def) $('tk-project').value = def;
  $('tk-create').onclick = function () {
    var g = $('tk-goal').value.trim(); if (!g) { toast('目标不能空', 'warn'); return; }
    api('/api/tickets/create', { method: 'POST', body: { goal: g, project: $('tk-project').value, parent: parent || '',
      tags: $('tk-tags').value.split(/[,，\s]+/).filter(Boolean), force: $('tk-now').checked } })
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
    return;
  }
  var open = force === undefined ? !$('rail').classList.contains('open') : force;
  $('rail').classList.toggle('open', open);
  $('rail-mask').classList.toggle('show', open);
}
$('btn-rail').onclick = function () { toggleRail(); };
$('rail-mask').onclick = function () { toggleRail(false); };
$('btn-files').onclick = openSide;
$('side-close').onclick = function () { hide('side'); };
$('modal-close').onclick = closeModal;
$('idle-chip').onclick = openIdle;
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
$('pv-files').onclick = openProjectFiles;
$('pv-delete').onclick = deleteProject;
$('pv-secretary').onclick = function () { selectGroup('sec-' + state.project); };
$('pv-compact').onclick = compactProjectSecretary;
$('pv-create').onclick = createTicket;
$('pv-artifacts').onclick = function () { state.group = 'sec-' + state.project; state.sideLayer = 'project'; openSide(); };
document.querySelectorAll('.tab').forEach(function (b) {
  b.onclick = function () {
    var tab = b.dataset.tab;
    document.querySelectorAll('.tab').forEach(function (x) { x.classList.toggle('active', x === b); });
    if (tab === 'chat') { closeModal(); hide('side'); }
    else if (tab === 'library') openLibrary('roles');
    else if (tab === 'health') openHealth();
    else if (tab === 'versions') openVersions();
    else openSource();
  };
});
document.querySelectorAll('#side .stab').forEach(function (b) { b.onclick = function () { openSide(); }; });

// ---------------- 启动 ----------------
api('/api/auth/status').then(function (r) {
  if (r.scheme === 'https' && location.protocol !== 'https:') $('login-hint').textContent = '服务已启用 HTTPS，建议用 https:// 访问';
  if (r.authed) enterApp(); else showLogin();
}).catch(function () { showLogin(); });
})();
