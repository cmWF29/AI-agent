// 业务规则面板：规则是模块之间的唯一关系来源。
function openRules(opts) {
  opts = opts || {};
  var html = '<div class="muted small">规则层在 <code>data/rules/catalog.json</code>；' +
    '模块只暴露能力，跨模块关系只在这里出现。' +
    '<div class="row-btns" style="justify-content:flex-start;margin-top:6px">' +
    '<button class="mini" data-rule-act="validate">校验规则</button>' +
    '<button class="mini" data-rule-act="refresh">刷新</button>' +
    '<span id="rules-status" class="muted small">加载中…</span></div></div>' +
    '<div id="rules-list" class="libbody"></div>' +
    '<h4>业务流程（需求 → 规则组合）</h4><div id="rules-process" class="muted small"></div>' +
    '<div id="rules-errors" class="err"></div>';
  openModal('业务规则层', html, { root: true });
  if (!opts.fromRoute) {
    setTab('rules');
    if (isOverlayHash()) replaceHash('#/rules'); else pushHash('#/rules');
    updateBackBtn();
  }
  document.querySelectorAll('#modal-body [data-rule-act]').forEach(function (b) {
    b.onclick = function () {
      if (b.dataset.ruleAct === 'validate') validateRules();
      else loadRules();
    };
  });
  loadRules();

  function loadRules() {
    $('rules-status').textContent = '加载中…';
    api('/api/rules/catalog').then(function (data) {
      renderRules(data);
    }).catch(function (e) {
      $('rules-status').textContent = '读取失败';
      $('rules-errors').textContent = e.message || String(e);
    });
  }

  function renderRules(data) {
    var box = $('rules-list');
    if (!box) return;
    var stats = data.stats || {};
    $('rules-status').textContent = '关系 ' + (stats.relations || 0) +
      ' · 流程 ' + (stats.processes || 0) + ' · 活跃 ' + (stats.active || 0) +
      ' · 需求覆盖 ' + (stats.requirements || 0) + '/' + (stats.requirement_total || 0);
    var groups = {};
    (data.relations || []).forEach(function (r) { (groups[r.from] = groups[r.from] || []).push(r); });
    var out = Object.keys(groups).sort().map(function (mod) {
      return '<h4>' + esc(mod) + '</h4>' + groups[mod].map(function (r) {
        return '<div class="libcard"><div class="libtitle">' + esc(r.cn || r.id) +
          '<span class="tag">' + esc(r.id) + '</span>' +
          '<span class="tag">' + (r.active ? 'active' : 'off') + '</span></div>' +
          '<div class="muted small">' + esc(r.subject || '') + ' ' + esc(r.predicate || '') + ' ' +
          esc(r.object || '') + ' · ' + esc(r.cardinality || '') + ' · ' + esc(r.from || '') +
          ' → ' + esc(r.to || '') + '</div>' +
          '<div class="small">' + esc(r.intent || '') + '</div>' +
          '<div class="muted small">' + ((r.steps || []).map(function (s) { return 'call ' + esc(s.call); }).join(' / ')) + '</div></div>';
      }).join('');
    }).join('');
    box.innerHTML = out || '<div class="muted">没有规则</div>';
    var procs = (data.processes || []).map(function (p) {
      return '<div class="libcard"><div class="libtitle">' + esc(p.cn || p.id) +
        '<span class="tag">' + esc(p.id) + '</span></div>' +
        '<div class="muted small">需求: ' + esc((p.requirements || []).join(', ') || '—') + '</div>' +
        '<div class="small">' + esc((p.composes || []).join(' → ') || '—') + '</div></div>';
    }).join('');
    $('rules-process').innerHTML = procs || '没有流程';
    $('rules-errors').textContent = (data.errors || []).join(' · ');
  }

  function validateRules() {
    api('/api/rules/validate', { method: 'POST', body: {} }).then(function (data) {
      $('rules-status').textContent = data.ok ? '规则校验通过（无冲突）' : '规则校验失败';
      $('rules-errors').textContent = (data.errors || []).join(' · ');
    }).catch(function (e) { $('rules-errors').textContent = e.message || String(e); });
  }
}

HiveUI.on('panel:open', function (p) { if (p && p.name === 'rules') openRules(p.opts); });
