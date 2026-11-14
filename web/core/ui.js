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

