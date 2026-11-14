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

