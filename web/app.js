const $ = (id) => document.getElementById(id);
const POLL_MS = 1200;

const state = { busy: false, timer: null };

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

function showLogin() {
  $('login').classList.remove('hidden');
  $('app').classList.add('hidden');
}

function showApp() {
  $('login').classList.add('hidden');
  $('app').classList.remove('hidden');
}

/* ---------- 聊天 ---------- */
function addMsg(role, text, meta = '') {
  const div = document.createElement('div');
  div.className = 'msg ' + role;
  div.textContent = text;
  if (meta) {
    const m = document.createElement('span');
    m.className = 'meta';
    m.textContent = meta;
    div.appendChild(m);
  }
  $('chat').appendChild(div);
  $('chat').scrollTop = $('chat').scrollHeight;
  return div;
}

function typing(on) {
  let el = $('chat').querySelector('.typing');
  if (on && !el) {
    el = document.createElement('div');
    el.className = 'msg sys typing';
    el.textContent = '秘书正在处理…';
    $('chat').appendChild(el);
    $('chat').scrollTop = $('chat').scrollHeight;
  } else if (!on && el) {
    el.remove();
  }
}

async function send() {
  const input = $('input');
  const text = input.value.trim();
  if (!text || state.busy) return;
  input.value = '';
  autosize();
  addMsg('user', text);
  state.busy = true;
  $('send').disabled = true;
  typing(true);
  try {
    const { job_id } = await api('/api/chat/send', { method: 'POST', body: JSON.stringify({ text }) });
    await pollJob(job_id);
  } catch (e) {
    typing(false);
    addMsg('sys', '发送失败：' + e.message);
  } finally {
    state.busy = false;
    $('send').disabled = false;
  }
}

async function pollJob(jobId) {
  const started = Date.now();
  for (;;) {
    await new Promise((r) => setTimeout(r, POLL_MS));
    let job;
    try {
      job = (await api('/api/chat/job/' + jobId)).job;
    } catch (e) {
      typing(false);
      addMsg('sys', '任务失联：' + e.message);
      return;
    }
    if (job.status === 'running') {
      const sec = Math.round((Date.now() - started) / 1000);
      if (sec % 5 === 0) typing(true);
      continue;
    }
    typing(false);
    const elapsed = ((job.ms || 0) / 1000).toFixed(1);
    if (job.status === 'done') {
      addMsg('bot', job.reply || '(空回复)', `status=done  ${elapsed}s`);
    } else {
      addMsg('bot', '（失败）' + (job.error || job.reply || '未知错误'), `status=${job.status}  ${elapsed}s`);
    }
    return;
  }
}

async function loadHistory() {
  try {
    const data = await api('/api/chat/history?limit=12');
    if (!data.items || !data.items.length) {
      addMsg('sys', '这是你和秘书的第一个会话。试试：“把当前仓库的 README 补一版本说明，开个工单”。');
      return;
    }
    data.items.forEach((m) => {
      if (m.role === 'user' || m.role === 'assistant') {
        addMsg(m.role === 'user' ? 'user' : 'bot', m.content || '');
      }
    });
  } catch (e) { /* ignore */ }
}

/* ---------- 状态 ---------- */
async function refreshStatus() {
  const pill = $('status-pill');
  try {
    const s = await api('/api/ops/status');
    const wd = s.watchdog || {};
    const llm = s.llm || {};
    pill.textContent = `v${s.version} · ${s.sessions}会话 · ${s.tickets}工单 · ${wd.alive ? 'watchdog在线' : 'watchdog离线'} · ${llm.has_key ? llm.model : '无APIKey'}`;
    pill.className = 'pill ' + (wd.alive && llm.has_key ? 'ok' : 'bad');
  } catch (e) {
    pill.textContent = '离线';
    pill.className = 'pill bad';
  }
}

/* ---------- 固定命令 ---------- */
async function compact() {
  const r = await api('/api/chat/compact', { method: 'POST', body: '{}' });
  toast(r.compacted ? `已压缩：${r.before_chars} → ${r.after_chars} 字` : '无需压缩（' + (r.reason || '') + '）');
}

async function restart() {
  const r = await api('/api/ops/restart', { method: 'POST', body: '{}' });
  toast(r.note || '已请求重启');
  setTimeout(refreshStatus, 6000);
}

async function rollback() {
  if (!confirm('确认回退到上一个版本？回退前会自动存档当前改动（分支 autosave/*）。')) return;
  const r = await api('/api/ops/rollback', { method: 'POST', body: '{}' });
  toast(r.note || '已请求回退');
}

async function stopAll() {
  if (!confirm('确认彻底停止 watchdog 和 agent？停止后需要在 VPS 上手动 systemctl start hive-watchdog。')) return;
  try {
    const r = await api('/api/ops/stop', { method: 'POST', body: '{}' });
    toast(r.note || '已请求停止', 6000);
  } catch (e) {
    toast('已发送停止请求（连接可能已断开）');
  }
  setTimeout(refreshStatus, 5000);
}

async function newTicket() {
  const goal = prompt('工单目标（含验收标准、边界）：');
  if (!goal) return;
  try {
    const r = await api('/api/tickets/create', { method: 'POST', body: JSON.stringify({ goal }) });
    toast('工单 ' + r.ticket.id + ' 已派给 PM');
    addMsg('sys', `工单 ${r.ticket.id} 已创建，PM 会话 ${r.ticket.pm} 开始编排。`);
  } catch (e) {
    toast('创建失败：' + e.message);
  }
}

/* ---------- 抽屉 ---------- */
function drawer(title, body) {
  $('drawer-title').textContent = title;
  $('drawer-body').textContent = body;
  $('drawer').classList.remove('hidden');
}

async function showTickets() {
  try {
    const data = await api('/api/tickets/list');
    if (!data.items.length) return drawer('工单', '暂无工单');
    const lines = data.items.map((t) => {
      const roles = (t.roles || []).map((r) => r.role).join(', ');
      return `${t.id}  [${t.status}]  ${t.title}\n  项目=${t.project}  PM=${t.pm || '-'}\n  目标=${t.goal.slice(0, 120)}\n  角色=${roles || '-'}\n`;
    });
    drawer('工单（' + data.items.length + '）', lines.join('\n'));
  } catch (e) {
    toast('读取失败：' + e.message);
  }
}

async function showEvents() {
  try {
    const data = await api('/api/obs/events?limit=60');
    const lines = (data.items || []).map((e) => `${new Date((e.t || 0) * 1000).toLocaleTimeString()}  ${e.topic}  ${JSON.stringify(e.payload || {}).slice(0, 160)}`);
    drawer('最近事件（' + lines.length + '）', lines.join('\n') || '暂无事件');
  } catch (e) {
    toast('读取失败：' + e.message);
  }
}

/* ---------- 输入框 ---------- */
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

function boot() {
  loadHistory();
  refreshStatus();
  clearInterval(state.timer);
  state.timer = setInterval(refreshStatus, 15000);
}

/* ---------- 绑定 ---------- */
$('login-btn').onclick = login;
$('password').addEventListener('keydown', (e) => { if (e.key === 'Enter') login(); });
$('send').onclick = send;
$('input').addEventListener('input', autosize);
$('input').addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
});
$('btn-status').onclick = async () => {
  try {
    const s = await api('/api/ops/status');
    const sel = await api('/api/ops/selftest', { method: 'POST', body: '{}' }).catch(() => null);
    drawer('运行状态', JSON.stringify(s, null, 2) + (sel ? '\n\n---- selftest ----\n' + JSON.stringify(sel, null, 2) : ''));
  } catch (e) { toast(e.message); }
};
$('btn-tickets').onclick = showTickets;
$('btn-events').onclick = showEvents;
$('btn-compact').onclick = () => compact().catch((e) => toast(e.message));
$('btn-restart').onclick = () => restart().catch((e) => toast(e.message));
$('btn-rollback').onclick = () => rollback().catch((e) => toast(e.message));
$('btn-stop').onclick = () => stopAll();
$('btn-newticket').onclick = newTicket;
$('drawer-close').onclick = () => $('drawer').classList.add('hidden');

(async function init() {
  try {
    const s = await api('/api/auth/status');
    if (s.authed) { showApp(); boot(); } else { showLogin(); }
  } catch (e) { showLogin(); }
})();
