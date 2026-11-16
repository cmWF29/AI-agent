/* actions：唯一动作出口（view / modal / demand 三态）
*/
async function execute(binding, fields) {
  const { act, ctx, composer } = binding;
  const c = { ...ctx, fields: fields || ctx.fields || {}, composer };
  if (act.view) {
    const next = resolveView(act, c);
    return go(next, true);
  }
  if (act.modal) {
    const fc = { ...c };
    if (fc.row && fc.row.project) fc.project = fc.row.project;
    return openForm(FORMS[act.modal], fc);
  }
  if (!act.demand) return;
  const params = fill(act.params || {}, c);
  if (act.confirm && !confirm(String(fill(act.confirm, c)))) return;
  const flashText = act.flash ? String(fill(act.flash, c)) : "";
  try {
    const res = await run(act.demand, params);
    if (act.clear) {
      const ta = document.querySelector("#view-body .composer textarea");
      if (ta) ta.value = "";   // 成功即清空，避免残留文本把轮询挡在门外
    }
    if (flashText) banner(fill(act.flash, { ...c, result: res }), "ok");
    if (act.after) {
      const next = resolveView(act.after, { ...c, result: res });
      return go(next, true);
    }
    await render({ keepBanner: true });
  } catch (err) {
    banner(gateMessage(err), "err");
  }
}
function resolveView(target, c) {
  const params = fill(target.params || {}, c);
  const view = target.view;
  if (view === "projects") return { view: "projects" };
  if (view === "project") return { view: "project", project: params.project || "" };
  if (view === "ticket") return { view: "ticket", project: params.project || "", ticket: params.ticket || "" };
  if (view === "positions") return { view: "positions" };
  return { view: view };
}


/* ---- 弹窗 ---- */
function openForm(form, ctx) {
  if (!form) return;
  MODAL_CTX = { form, ctx };
  $("modal-title").textContent = fill(form.title || "", ctx);
  $("modal-hint").textContent = fill(form.hint || "", ctx);
  $("modal-err").className = "modal-err";
  $("modal-err").textContent = "";
  $("modal-form").innerHTML = (form.fields || []).map((f) => {
    const val = f.value != null ? fill(f.value, ctx) : "";
    const req = f.required ? ' data-required="1"' : "";
    const ro = f.readonly ? " readonly" : "";
    const ph = f.placeholder ? ` placeholder="${esc(f.placeholder)}"` : "";
    if (f.kind === "textarea") {
      return `<div class="field"><label>${esc(f.label)}</label><textarea name="${esc(f.name)}"${ph}>${esc(val)}</textarea></div>`;
    }
    if (f.kind === "select") {
      const opts = (f.options || []).map((o) =>
        `<option value="${esc(o.value)}"${String(val) === String(o.value) ? " selected" : ""}>${esc(o.label)}</option>`).join("");
      return `<div class="field"><label>${esc(f.label)}</label><select name="${esc(f.name)}">${opts}</select></div>`;
    }
    return `<div class="field"><label>${esc(f.label)}</label><input name="${esc(f.name)}" value="${esc(val)}"${ph}${req}${ro}></div>`;
  }).join("");
  $("modal-ok").textContent = fill((form.submit || {}).ok || "确定", ctx);
  $("modal-ok").disabled = false;
  $("modal").hidden = false;
  const first = $("modal-form").querySelector("input:not([readonly]),textarea,select");
  if (first) first.focus();
  modalSubmit = async (fd) => {
    const fields = {};
    for (const [k, v] of fd.entries()) fields[k] = typeof v === "string" ? v.trim() : v;
    for (const f of form.fields || []) {
      if (f.required && !fields[f.name]) throw new Error(f.label + "不能为空");
    }
    const c = { ...ctx, fields };
    const res = await run(form.submit.demand, fill(form.submit.params || {}, c));
    closeModal();
    if (form.submit.flash) banner(fill(form.submit.flash, { ...c, result: res }), "ok");
    if (form.submit.then) {
      const next = resolveView(form.submit.then, { ...c, result: res });
      return go(next, true);
    }
    await render({ keepBanner: true });
  };
}
function closeModal() { $("modal").hidden = true; modalSubmit = null; MODAL_CTX = null; }
function modalError(msg) {
  $("modal-err").className = "modal-err on";
  $("modal-err").textContent = msg;
}
$("modal-cancel").onclick = closeModal;
$("modal").onclick = (e) => { if (e.target === $("modal")) closeModal(); };
$("modal-form").onsubmit = async (e) => {
  e.preventDefault();
  if (!modalSubmit) return;
  $("modal-ok").disabled = true;
  try { await modalSubmit(new FormData(e.target)); }
  catch (err) { modalError(gateMessage(err)); }
  finally { $("modal-ok").disabled = false; }
};
