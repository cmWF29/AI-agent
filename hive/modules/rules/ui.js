// 业务规则面板：规则是模块之间的唯一关系来源。
function openRules(opts) {
  opts = opts || {};
  var html = '<div class="muted small">规则层在 <code>data/rules/catalog.json</code>；' +
    '模块只暴露能力，跨模块关系只在这里出现。' +
    '<div class="row-btns" style="justify-content:flex-start;margin-top:6px">' +
    '<button class="mini" data-rule-act="validate">校验规则</button>' +
    '<button class="mini" data-rule-act="graph">模块关系图</button>' +
    '<button class="mini" data-rule-act="refresh">刷新</button>' +
    '<span id="rules-status" class="muted small">加载中…</span></div></div>' +
    '<div id="rules-graph" class="rules-graph"></div>' +
    '<div id="rules-list" class="libbody"></div>' +
    '<h4>业务流程（需求 → 规则组合）</h4><div id="rules-process" class="muted small"></div>' +
    '<h4>事件订阅（发布者 → 订阅者）</h4><div id="rules-events" class="muted small"></div>' +
    '<h4>对外入口契约（浏览器 → 公开 API）</h4><div id="rules-surfaces" class="muted small"></div>' +
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
      else if (b.dataset.ruleAct === 'graph') loadGraph();
      else loadRules();
    };
  });
  loadRules();

  function loadGraph() {
    var box = $('rules-graph');
    if (!box) return;
    box.innerHTML = '<div class="muted small">加载模块关系图…</div>';
    api('/api/rules/graph').then(function (data) {
      renderGraph(data);
    }).catch(function (e) {
      box.innerHTML = '<div class="err">' + esc(e.message || String(e)) + '</div>';
    });
  }

  function renderGraph(data) {
    var box = $('rules-graph');
    if (!box) return;
    var nodes = (data.nodes || []).filter(function (n) { return n.type === 'module'; });
    var byId = {};
    (data.nodes || []).forEach(function (n) { byId[n.id] = n; });
    var links = {};
    var pending = {};
    (data.edges || []).forEach(function (e) {
      var mod = String(e.to || '').indexOf('module:') === 0 ? e.to.slice(7) : '';
      if (e.kind === 'from' && String(e.from || '').indexOf('rule:') === 0) pending[e.from] = mod;
      if (e.kind === 'to' && String(e.from || '').indexOf('rule:') === 0 && pending[e.from]) {
        var key = pending[e.from] + '→' + mod;
        links[key] = (links[key] || 0) + 1;
      }
    });
    var cols = Math.max(1, Math.ceil(nodes.length / 7));
    var rows = Math.ceil(nodes.length / cols);
    var width = Math.max(620, cols * 260 + 40);
    var height = Math.max(300, rows * 58 + 60);
    var pos = {};
    nodes.forEach(function (n, i) {
      var col = i % cols, row = Math.floor(i / cols);
      pos[n.id] = { x: 120 + col * 260, y: 54 + row * 58 };
    });
    var svg = ['<div class="muted small">模块级关系（按规则聚合，数字为规则条数）</div>',
      '<svg class="rules-svg" viewBox="0 0 ' + width + ' ' + height + '" role="img" aria-label="模块关系图">'];
    Object.keys(links).forEach(function (key) {
      var parts = key.split('→');
      var a = pos['module:' + parts[0]], b = pos['module:' + parts[1]];
      if (!a || !b) return;
      svg.push('<line x1="' + a.x + '" y1="' + a.y + '" x2="' + b.x + '" y2="' + b.y +
        '" stroke="#3b5a7a" stroke-width="1.2" opacity="0.8"></line>');
      svg.push('<text x="' + ((a.x + b.x) / 2) + '" y="' + ((a.y + b.y) / 2 - 3) +
        '" fill="#7f92ab" font-size="10" text-anchor="middle">' + links[key] + '</text>');
    });
    nodes.forEach(function (n) {
      var p = pos[n.id];
      svg.push('<circle cx="' + p.x + '" cy="' + p.y + '" r="8" fill="' +
        (n.active === false ? '#53657d' : '#58a6ff') + '"></circle>');
      svg.push('<text x="' + (p.x + 13) + '" y="' + (p.y + 4) +
        '" fill="#b8c7dc" font-size="12">' + esc(n.label || n.id) + '</text>');
    });
    svg.push('</svg>');
    box.innerHTML = svg.join('');
  }

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
      ' · 流程 ' + (stats.processes || 0) +
      ' · 订阅 ' + (stats.events || 0) +
      ' · 活跃 ' + (stats.active || 0) +
      ' · 跨模块规则覆盖 ' + (stats.requirements || 0) + '/' + (stats.requirement_total || 0) +
      ' · 对外入口 ' + (stats.entry_covered || 0) + '/' + (stats.entry_total || 0) +
      ' · 对外契约 ' + (stats.surfaces || 0);
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
    var events = (data.events || []).map(function (e) {
      return '<div class="libcard"><div class="libtitle">' + esc(e.cn || e.id) +
        '<span class="tag">' + esc(e.id) + '</span>' +
        '<span class="tag">' + (e.active ? 'active' : 'off') + '</span></div>' +
        '<div class="muted small">' + esc(e.topic || '') + ' · ' + esc(e.from || '') +
        ' → ' + esc(e.to || '') + '</div>' +
        '<div class="small">' + esc(e.intent || '') + '</div></div>';
    }).join('');
    $('rules-events').innerHTML = events || '没有事件订阅';
    var surfaces = (data.surfaces || []).map(function (s) {
      return '<div class="libcard"><div class="libtitle">' + esc(s.intent || s.id) +
        '<span class="tag">' + esc(s.id) + '</span></div>' +
        '<div class="muted small">' + esc(s.ui || '') + ' → ' + esc(s.target || '') +
        ' · ' + esc(s.prefix || '') + ' · ' + esc((s.methods || []).join('/')) + '</div></div>';
    }).join('');
    $('rules-surfaces').innerHTML = surfaces || '没有对外契约';
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
