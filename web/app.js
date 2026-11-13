const $ = (id) => document.getElementById(id);
const POLL_MS = 1400;
const LIVE_MS = 2600;

const state = {
  group: 'secretary',
  groups: [],
  projects: [],
  busy: false,
  live: null,
  cursor: 0,
  seen: 0,
};

/* ---------------- 基础 ---------------- */
async function api(path, options = {}) {
  const res = await fetch(path, {
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  if (res.status === 401) { showLogin(); throw new Error('unauthorized'); }
  let data = {};
  try { data = await res.json(); } catch (e) { data = { ok: false, error: 'bad json' }; }
  if (data.ok === false) throw new Error(data.error || '请求失败');
  return data;
}

function toast(text, ms = 3200) {
  const el = $('toast');
  el.textContent = text;
  el.classList.remove('hidden');
  clearTimeout(el._t);
  el._t = setTimeout(() => el.classList.add('hidden'), ms);
}

function esc(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function tok(u) {
  if (!u || !u.total_tokens) return '本进程还没跑过模型调用';
  const k = (n) => (n >= 1000 ? (n / 1000).toFixed(1) + 'k' : String(n));
  return `${k(u.prompt_tokens)} in / ${k(u.completion_tokens)} out · ${u.calls} 次` + (u.errors ? ` · ${u.errors} 失败` : '');
}

function fmtTime(ts) {
  if (!ts) return '';
  const d = new Date(ts * 1000);
  return d.toLocaleTimeString().slice(0, 5);
}

function showLogin() { $('login').classList.remove('hidden'); $('app').classList.add('hidden'); }
function showApp() { $('login').classList.add('hidden'); $('app').classList.remove('hidden'); }

/* ---------------- 群聊列表 ---------------- */
async function refreshGroups() {
  const data = await api('/api/web/groups');
  state.groups = data.items || [];
  state.projects = data.projects || [];
  renderGroups();
  renderProjects(data.default_project || '');
  const g = state.groups.find((x) => x.id === state.group);
  if (!g && state.groups.length) state.group = state.groups[0].id;
  renderChatHead();
}

function renderGroups() {
  const box = $('groups');
  box.innerHTML = '';
  const open = state.groups.filter((g) => g.open);
  const closed = state.groups.filter((g) => !g.open);
  const mk = (g) => {
    const el = document.createElement('button');
    el.className = 'group-item' + (g.id === state.group ? ' active' : '') + (g.open ? '' : ' dim');
    const badge = g.kind === 'secretary' ? '秘' : '工';
    const status = g.kind === 'secretary' ? (g.state || '') : (g.status || '');
    el.innerHTML = `<span class="badge">${badge}</span>
      <span class="g-main"><span class="g-title">${esc(g.title || g.id)}</span>
      <span class="g-sub">${esc(g.id)} · ${esc(status)}${g.project ? ' · ' + esc(g.project) : ''}</span></span>`;
    el.onclick = () => selectGroup(g.id);
    box.appendChild(el);
  };
  open.forEach(mk);
  if (closed.length) {
    const h = document.createElement('div');
    h.className = 'group-sep';
    h.textContent = '历史工单（' + closed.length + '）';
    box.appendChild(h);
    closed.slice(0, 30).forEach(mk);
  }
}

function renderProjects(defaultProject) {
  const sel = $('project-select');
  const cur = sel.value || defaultProject;
  sel.innerHTML = '';
  state.projects.forEach((p) => {
    const o = document.createElement('option');
    o.value = p.id;
    o.textContent = p.title && p.title !== p.id ? p.title + ' (' + p.id + ')' : p.id;
    sel.appendChild(o);
  });
  if (cur) sel.value = cur;
}

function renderChatHead() {
  const g = state.groups.find((x) => x.id === state.group);
  if (!g) { $('chat-title').textContent = '秘书'; $('chat-sub').textContent = ''; return; }
  $('chat-title').textContent = g.title || g.id;
  let sub = g.kind === 'secretary' ? '常驻秘书 · 只发作业，不亲自干活'
    : `${g.id} · ${g.status}${g.pm ? ' · PM ' + g.pm : ''}${g.roles ? ' · 角色 ' + g.roles : ''}`;
  $('chat-sub').textContent = sub;
  $('input').placeholder = g.kind === 'secretary'
    ? '给秘书发一句话（任何实质任务它都会开成工单）…'
    : '在这个工单群里说一句（会发给该工单的 PM）…';
  $('btn-files').style.display = g.kind === 'ticket' ? '' : 'none';
}

async function selectGroup(id) {
  state.group = id;
  state.cursor = 0;
  $('messages').innerHTML = '';
  $('side').classList.add('hidden');
  $('rail').classList.remove('open');       // 手机上选完群，抽屉收起来
  renderGroups();
  renderChatHead();
  await loadTimeline(true);
  if (id.startsWith('T-')) loadFiles();
}

/* ---------------- 时间线 ---------------- */
async function loadTimeline(reset = false) {
  let data;
  try {
    data = await api(`/api/web/timeline?group=${encodeURIComponent(state.group)}&limit=120`);
  } catch (e) {
    if (e.message !== 'unauthorized') return;
    throw e;
  }
  const items = data.items || [];
  if (reset) {
    $('messages').innerHTML = '';
    state.seen = 0;
  }
  // 只追加新消息，避免每次轮询重绘（流式体验）
  const fresh = items.slice(state.seen);
  state.seen = items.length;
  state.cursor = data.cursor || state.cursor;
  fresh.forEach(renderItem);
  if (fresh.length) scrollBottom();
  if (!items.length && reset) {
    $('messages').innerHTML = '<div class="empty">这里还没有消息。' +
      (state.group === 'secretary'
        ? '给秘书发一句话试试：“看一下这台服务器的磁盘，出个简报”。'
        : '工单刚创建，PM 正在编排角色。') + '</div>';
  }
}

function renderItem(m) {
  const box = $('messages');
  const role = m.role || 'assistant';
  if (role === 'event' || m.kind === 'event') {
    const el = document.createElement('div');
    el.className = 'sys-line';
    el.textContent = `— ${m.speaker || '系统'}：${(m.text || '').slice(0, 200)} —`;
    box.appendChild(el);
    return;
  }
  if (role === 'system') return;
  if (role === 'tool') {
    const el = document.createElement('details');
    el.className = 'tool-line';
    const name = (m.tool_names && m.tool_names[0]) || 'tool';
    el.innerHTML = `<summary>⚙ ${esc(name)} 的返回（${(m.text || '').length} 字）</summary>
      <div class="tool-body">${esc((m.text || '').slice(0, 900))}</div>`;
    box.appendChild(el);
    return;
  }
  const mine = role === 'user';
  if (!mine && !(m.text || '').trim()) return;   // 只调工具、没说话的回合不画空气泡
  const row = document.createElement('div');
  row.className = 'row-msg ' + (mine ? 'mine' : 'other');
  const name = mine ? '我' : (m.speaker || 'agent');
  const chips = (m.tool_names || []).map((t) => `<span class="chip">⚙ ${esc(t)}</span>`).join('');
  row.innerHTML = `<div class="who">${esc(name)} <span class="t">${fmtTime(m.ts)}</span></div>
    <div class="bubble">${esc(m.text || '').replace(/\n/g, '<br>')}</div>
    ${chips ? '<div class="chips">' + chips + '</div>' : ''}`;
  box.appendChild(row);
}

function scrollBottom() {
  const box = $('messages');
  box.scrollTop = box.scrollHeight;
}

/* ---------------- 发送 ---------------- */
async function send() {
  const text = $('input').value.trim();
  if (!text || state.busy) return;
  $('input').value = '';
  autosize();
  state.busy = true;
  $('send').disabled = true;
  const g = state.groups.find((x) => x.id === state.group);
  if (g && g.kind === 'secretary') {
    $('messages').querySelectorAll('.empty').forEach((e) => e.remove());
    renderItem({ role: 'user', speaker: '我', text, ts: Date.now() / 1000 });
    scrollBottom();
  }
  const typing = addTyping();
  try {
    const { job_id } = await api('/api/chat/send', {
      method: 'POST', body: JSON.stringify({ text, group: state.group }),
    });
    await pollJob(job_id);
  } catch (e) {
    toast('发送失败：' + e.message);
  } finally {
    typing.remove();
    state.busy = false;
    $('send').disabled = false;
    state.seen = 0;
    await loadTimeline(true).catch(() => {});
    refreshGroups().catch(() => {});
  }
}

function addTyping() {
  const el = document.createElement('div');
  el.className = 'sys-line typing';
  el.textContent = '正在处理…';
  $('messages').appendChild(el);
  scrollBottom();
  return el;
}

async function pollJob(jobId) {
  const started = Date.now();
  for (;;) {
    await new Promise((r) => setTimeout(r, POLL_MS));
    let job;
    try {
      job = (await api('/api/chat/job/' + jobId)).job;
    } catch (e) { return; }
    if (job.status === 'running') {
      const t = $('messages').querySelector('.typing');
      if (t) t.textContent = `正在处理… ${Math.round((Date.now() - started) / 1000)}s`;
      continue;
    }
    if (job.status === 'error') toast('任务失败：' + (job.error || '未知'));
    return;
  }
}

/* ---------------- 面板 ---------------- */
function openModal(title) {
  $('modal-title').textContent = title;
  $('modal-body').innerHTML = '';
  $('modal').classList.remove('hidden');
}

async function showHealth() {
  openModal('健康自检');
  const body = $('modal-body');
  body.innerHTML = '<div class="muted">检查中…</div>';
  try {
    const [self, st] = await Promise.all([api('/api/health/self'), api('/api/ops/status')]);
    const rows = (self.checks || []).map((c) => `
      <tr class="${c.ok ? 'ok' : 'bad'}">
        <td>${c.ok ? '✔' : '✖'}</td>
        <td>${esc(c.name)}${c.critical ? ' <span class="tag">critical</span>' : ''}</td>
        <td>${esc(c.detail || '')}</td>
      </tr>`).join('');
    const wd = st.watchdog || {};
    body.innerHTML = `
      <div class="kv">
        <div><span>状态</span><b class="${self.healthy ? 'good' : 'bad'}">${self.healthy ? '健康' : '异常'}</b></div>
        <div><span>版本</span><b>${esc(st.version)}</b></div>
        <div><span>pid / uptime</span><b>${st.pid} / ${st.uptime_sec}s</b></div>
        <div><span>watchdog</span><b class="${wd.alive ? 'good' : 'bad'}">${wd.alive ? '在线' : '离线'}</b></div>
        <div><span>心跳</span><b>${wd.heartbeat_age_sec != null ? wd.heartbeat_age_sec + 's 前' : '-'}</b></div>
        <div><span>模型</span><b>${esc(st.llm.model)} ${st.llm.has_key ? '' : '(无 Key)'}</b></div>
        <div><span>会话 / 工单</span><b>${st.sessions} / ${st.tickets}</b></div>
        <div><span>tokens</span><b>${tok(st.llm.usage)}</b></div>
      </div>
      <table class="checks">${rows}</table>
      <div class="muted small">刷新页面可重新检查；watchdog 每 10 秒自检一次。</div>`;
  } catch (e) {
    body.innerHTML = '<div class="bad">读取失败：' + esc(e.message) + '</div>';
  }
}

async function showVersions() {
  openModal('版本管理');
  const body = $('modal-body');
  body.innerHTML = '<div class="muted">读取中…</div>';
  try {
    const v = await api('/api/ops/versions');
    const git = v.git || {};
    if (!git.available) {
      body.innerHTML = '<div class="bad">git 不可用：' + esc(git.error || '') + '</div>';
      return;
    }
    const commits = (git.commits || []).map((c) => `
      <div class="ver ${c.current ? 'cur' : ''}">
        <div class="ver-main">
          <code>${esc(c.short)}</code>
          <span class="ver-sub">${esc(c.subject)}</span>
        </div>
        <div class="ver-meta">${esc(c.author)} · ${esc(c.date)}${c.current ? ' · 当前版本' : ''}</div>
        ${c.current ? '' : `<button class="mini rollback" data-target="${esc(c.short)}">回退到此版本</button>`}
      </div>`).join('');
    body.innerHTML = `
      <div class="kv">
        <div><span>当前 HEAD</span><b>${esc(git.head)}</b></div>
        <div><span>工作区</span><b class="${git.dirty ? 'bad' : 'good'}">${git.dirty ? '有未提交改动（回退前会自动存档）' : '干净'}</b></div>
        <div><span>自动存档分支</span><b>${esc((git.autosave_branches || []).join(', ') || '无')}</b></div>
      </div>
      <div class="vers">${commits}</div>
      <div class="muted small">回退 = 先把你当前的改动提交到 autosave/&lt;时间戳&gt; 分支（不丢），再 reset 到目标版本，然后重启 agent。</div>`;
    body.querySelectorAll('.rollback').forEach((b) => {
      b.onclick = () => doRollback(b.dataset.target);
    });
  } catch (e) {
    body.innerHTML = '<div class="bad">读取失败：' + esc(e.message) + '</div>';
  }
}

async function doRollback(target) {
  if (!confirm(`确认回退到 ${target}？当前改动会先存到 autosave/ 分支，不会丢。`)) return;
  try {
    const r = await api('/api/ops/rollback', { method: 'POST', body: JSON.stringify({ target }) });
    toast(r.note || '已请求回退', 5000);
    $('modal').classList.add('hidden');
  } catch (e) { toast('失败：' + e.message); }
}

async function showEvents() {
  openModal('最近事件');
  try {
    const data = await api('/api/obs/events?limit=80');
    const lines = (data.items || []).map((e) =>
      `<div class="ev"><span class="t">${new Date((e.t || 0) * 1000).toLocaleTimeString()}</span>
       <code>${esc(e.topic)}</code>
       <span class="muted">${esc(JSON.stringify(e.payload || {}).slice(0, 160))}</span></div>`).join('');
    $('modal-body').innerHTML = lines || '<div class="muted">暂无事件</div>';
  } catch (e) { $('modal-body').innerHTML = '<div class="bad">' + esc(e.message) + '</div>'; }
}

/* ---------------- 交付件 ---------------- */
async function loadFiles() {
  if (!state.group.startsWith('T-')) return;
  const side = $('side');
  try {
    const data = await api(`/api/tickets/${state.group}/files`);
    $('side-title').textContent = `交付件（${data.total}）`;
    const body = $('side-body');
    if (!data.items.length) {
      body.innerHTML = '<div class="muted">还没有产出文件。角色交付后会出现在这里。</div>';
      return;
    }
    body.innerHTML = data.items.map((f) =>
      `<button class="file" data-path="${esc(f.path)}"><span>${esc(f.path)}</span>
       <span class="muted">${f.size}B</span></button>`).join('');
    body.querySelectorAll('.file').forEach((b) => {
      b.onclick = () => openFile(b.dataset.path);
    });
  } catch (e) {
    $('side-body').innerHTML = '<div class="bad">' + esc(e.message) + '</div>';
  }
}

async function openFile(path) {
  openModal(path);
  try {
    const f = await api(`/api/tickets/${state.group}/file?path=${encodeURIComponent(path)}`);
    const body = $('modal-body');
    if (f.encoding === 'base64') {
      const ext = (path.split('.').pop() || '').toLowerCase();
      if (['png', 'jpg', 'jpeg', 'gif', 'webp'].includes(ext)) {
        body.innerHTML = `<img class="preview" src="data:image/${ext};base64,${f.text}" alt="">`;
      } else {
        body.innerHTML = `<div class="muted">二进制文件（${f.size}B），无法预览。</div>`;
      }
    } else {
      body.innerHTML = `<pre class="code">${esc(f.text)}</pre>
        ${f.truncated ? '<div class="muted small">（文件较大，仅显示前 ' + Math.round(f.text.length) + ' 字符）</div>' : ''}`;
    }
  } catch (e) { $('modal-body').innerHTML = '<div class="bad">' + esc(e.message) + '</div>'; }
}

/* ---------------- 固定命令 ---------------- */
async function newTicket() {
  const goal = prompt('工单目标（写清验收标准与边界）：');
  if (!goal) return;
  const project = $('project-select').value || '';
  try {
    const r = await api('/api/tickets/create', { method: 'POST', body: JSON.stringify({ goal, project }) });
    toast('工单 ' + r.ticket.id + ' 已派给 PM');
    await refreshGroups();
    selectGroup(r.ticket.id);
  } catch (e) { toast('创建失败：' + e.message); }
}

async function newProject() {
  const name = prompt('项目名（英文或中文都行，会作为知识库 project 层的键）：');
  if (!name) return;
  try {
    await api('/api/projects/create', { method: 'POST', body: JSON.stringify({ name }) });
    await refreshGroups();
    $('project-select').value = name;
    toast('项目 ' + name + ' 已创建');
  } catch (e) { toast('创建失败：' + e.message); }
}

async function compact() {
  const r = await api('/api/chat/compact', { method: 'POST', body: '{}' });
  toast(r.compacted ? `已压缩：${r.before_chars} → ${r.after_chars} 字` : '无需压缩（' + (r.reason || '') + '）');
}

async function restart() {
  const r = await api('/api/ops/restart', { method: 'POST', body: '{}' });
  toast(r.note || '已请求重启', 5000);
}

async function stopAll() {
  if (!confirm('确认彻底停止 watchdog 和 agent？之后需要在 VPS 上 systemctl start hive-watchdog。')) return;
  try {
    const r = await api('/api/ops/stop', { method: 'POST', body: '{}' });
    toast(r.note || '已请求停止', 6000);
  } catch (e) { toast('已发送停止请求（连接可能已断开）'); }
}

/* ---------------- 状态 ---------------- */
async function refreshStatus() {
  const pill = $('status-pill');
  try {
    const s = await api('/api/ops/status');
    const wd = s.watchdog || {};
    const llm = s.llm || {};
    pill.textContent = `v${s.version} · ${s.sessions}会话 · ${s.tickets}工单 · ${wd.alive ? 'watchdog在线' : 'watchdog离线'}`;
    pill.className = 'pill ' + (wd.alive && llm.has_key ? 'ok' : 'bad');
  } catch (e) {
    pill.textContent = '离线';
    pill.className = 'pill bad';
  }
}

function startLive() {
  clearInterval(state.live);
  state.live = setInterval(async () => {
    if (state.busy) return;
    try { await loadTimeline(false); } catch (e) { /* ignore */ }
    refreshStatus().catch(() => {});
  }, LIVE_MS);
}

/* ---------------- 输入 ---------------- */
function autosize() {
  const el = $('input');
  el.style.height = 'auto';
  el.style.height = Math.min(el.scrollHeight, 140) + 'px';
}

async function login() {
  const pw = $('password').value;
  if (!pw) return;
  try {
    await api('/api/auth/login', { method: 'POST', body: JSON.stringify({ password: pw }) });
    $('login-err').textContent = '';
    showApp();
    boot();
  } catch (e) {
    $('login-err').textContent = e.message === 'unauthorized' ? '密码错误' : e.message;
  }
}

async function boot() {
  await refreshGroups().catch(() => {});
  await loadTimeline(true).catch(() => {});
  refreshStatus().catch(() => {});
  startLive();
}

/* ---------------- 绑定 ---------------- */
$('login-btn').onclick = login;
$('password').addEventListener('keydown', (e) => { if (e.key === 'Enter') login(); });
$('send').onclick = send;
$('input').addEventListener('input', autosize);
$('input').addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
});
$('btn-health').onclick = () => showHealth().catch((e) => toast(e.message));
$('btn-versions').onclick = () => showVersions().catch((e) => toast(e.message));
$('btn-events').onclick = () => showEvents().catch((e) => toast(e.message));
$('btn-newticket').onclick = newTicket;
$('btn-newproject').onclick = newProject;
$('btn-compact').onclick = () => compact().catch((e) => toast(e.message));
$('btn-restart').onclick = () => restart().catch((e) => toast(e.message));
$('btn-stop').onclick = stopAll;
$('btn-files').onclick = () => { $('side').classList.toggle('hidden'); loadFiles(); };
$('side-close').onclick = () => $('side').classList.add('hidden');
$('btn-groups').onclick = () => $('rail').classList.toggle('open');
$('modal-close').onclick = () => $('modal').classList.add('hidden');

(async function init() {
  try {
    const s = await api('/api/auth/status');
    if (s.authed) { showApp(); boot(); } else { showLogin(); }
  } catch (e) { showLogin(); }
})();
