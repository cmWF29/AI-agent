// ---------------- 会话 ----------------
// 群聊模块自己的渲染模板：外部容器只留 #mount-chat。
var CHAT_HTML = `
<div class="chathead">
  <div class="chathead-main">
    <strong id="chat-title">秘书</strong>
    <button class="chip hidden" id="btn-copy-ticket" title="复制工单号">⧉</button>
    <span id="chat-sub" class="muted small"></span>
    <div id="chat-tags" class="tags"></div>
  </div>
  <div class="spacer"></div>
  <button class="mini" id="btn-addtag" title="加工单标签">＋标签</button>
  <button class="mini" id="btn-fork-ticket" title="基于此单新开">⎇ 派生</button>
  <button class="mini" id="btn-files" title="交付件">📎 交付件</button>
  <button class="mini" id="btn-refresh" title="刷新">⟳ 刷新</button>
</div>

<div id="flow" class="flow hidden"></div>

<div id="messages" class="messages"></div>
<div id="livebar" class="livebar hidden">
  <div class="live-dot"></div>
  <div class="live-text">
    <div class="live-who" id="live-who">角色正在说…</div>
    <div class="live-body" id="live-body"></div>
  </div>
  <div class="live-acts"><button class="mini" id="btn-interrupt" title="打断">■ 打断</button></div>
</div>

<div class="composer">
  <textarea id="input" rows="1" placeholder="给项目秘书/PM 发一句话…（Enter 发送 / Shift+Enter 换行）"></textarea>
  <div class="composer-side">
    <label class="checkline small"><input type="checkbox" id="force-now" /> 立即执行</label>
    <button id="send" class="primary">发送</button>
  </div>
</div>
<div id="readonly-tip" class="readonly-tip hidden">该工单已结单或正在结单，群聊只读 —— 要改结果请「基于此单新开」。</div>
`;
(function mountChatTemplate() {
  var host = $('mount-chat');
  if (host && !host.innerHTML.trim()) host.innerHTML = CHAT_HTML;
})();

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
  // 群聊实例挂载事实：只有该实例通道的订阅者需要响应。
  HiveUI.mount('chat', id, 'mount-chat');
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

