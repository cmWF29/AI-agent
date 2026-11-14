/* Hive Agent v4 控制台
 * 项目 -> 项目页（改名/工单/秘书/新建工单/文件）
 * 工单群聊：角色发言 + 模块报文（点击看完整 JSON）+ 并行编排（点击看详情）
 * 全站 HTTPS，无“本地节点”、无独立“链路”页。
 */

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
function findProject(id) { for (var i = 0; i < state.projects.length; i++) if (state.projects[i].id === id) return state.projects[i]; return null; }
function findGroup(id) { for (var i = 0; i < state.groups.length; i++) if (state.groups[i].id === id) return state.groups[i]; return null; }
var FLOW_STATE_LABELS = { done: '已完成', running: '进行中', idle: '等待中', destroyed: '已结束', gone: '已结束', error: '异常' };
var STATUS_LABELS = { running: '进行中', queued: '排队中', closing: '结单中', closed: '已结单',
  conflict: '有冲突', working: '处理中', blocked: '被拦下', interrupted: '已中断', error: '异常' };
function stateLabel(s) { return FLOW_STATE_LABELS[s] || s || ''; }
function statusLabel(s) { return STATUS_LABELS[s] || s || ''; }
function overlayRoute(hash, tab) {
  setTab(tab);
  if (isOverlayHash()) replaceHash(hash); else pushHash(hash);
  updateBackBtn();
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
  if (type === 'knowledge') return { type: 'overlay', tab: 'knowledge' };
  if (type === 'health' || type === 'versions') return { type: 'overlay', tab: type };
  if (type === 'rules') return { type: 'overlay', tab: 'rules' };
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
    HiveUI.emit('project:open', { id: pid, silent: true, opts: { replace: true } }); return;
  }
  if (state.view === 'project') { toast('已经是最外层了', 'warn'); return; }
  if (state.view === 'chat') {
    var pid2 = (findGroup(state.group) || {}).project || state.project;
    if (pid2) HiveUI.emit('project:open', { id: pid2, silent: true, opts: { replace: true } });
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
  hide('login'); show('app'); applyRailPref(); HiveUI.emit('app:ready', {}); startPolling();
}
function applyRailPref() {
  var collapsed = localStorage.getItem('hive_rail_collapsed') === '1';
  if (window.innerWidth > 900) document.body.classList.toggle('rail-collapsed', collapsed);
}

