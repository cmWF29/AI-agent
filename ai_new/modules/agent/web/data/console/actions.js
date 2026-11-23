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
    // 拆解这类长动作可能跑几十秒，先给一条"加载中"，成功/失败再被下面的提示覆盖。
    banner(uiText("loading") || "加载中…", "info");
    const res = await run(act.demand, params);
    if (act.clear) {
      const ta = document.querySelector("#view-body .composer textarea");
      if (ta) ta.value = "";   // 成功即清空，避免残留文本把轮询挡在门外
    }
    if (flashText) {
      // 工具禁用会连带禁用依赖岗位：把连带结果一并说清楚，否则用户只看到"岗位也灰了"
      const casc = (res && (res.cascaded || (res.result && res.result.cascaded))) || [];
      const cnames = (res && res.cascaded_names) || casc.map(roleLabel);
      const names = cnames.join("/");
      const extra = casc.length ? uiText("cascaded_roles", casc.length, names) : "";
      banner(fill(act.flash, { ...c, result: res }) + extra, "ok");
    }
    if (act.after) {
      const next = resolveView(act.after, { ...c, result: res });
      return go(next, true);
    }
    await render({ keepBanner: true });
  } catch (err) {
    banner(gateMessage(err), "err");
  }
}
/* ---- 语音录音：开始/停止 → 识别 → 回填输入框，不自动发送 ---- */
function voiceBtnLabel(binding) {
  return String((binding.act && binding.act.label) || uiText("voice"));
}
function resetVoiceBtn(btn, binding) {
  btn.classList.remove("on");
  btn.textContent = voiceBtnLabel(binding);
}
async function executeVoice(binding, btn) {
  const act = binding.act;
  const box = $("view-body").querySelector(".composer textarea");
  if (!VoiceRecorder.recording) {
    try { await VoiceRecorder.start(); }
    catch (err) { banner(gateMessage(err) || uiText("mic_denied"), "err"); return; }
    btn.classList.add("on");
    btn.textContent = uiText("stop");
    return;
  }
  let rec;
  try { rec = await VoiceRecorder.stop(); }
  catch (err) { resetVoiceBtn(btn, binding); banner(gateMessage(err), "err"); return; }
  resetVoiceBtn(btn, binding);
  try {
    const params = fill(act.params || {}, { ...binding.ctx });
    params.audio_b64 = rec.b64;
    params.mime = rec.mime;
    const res = await run(act.demand, params);
    const text = String((res && res.text) || "").trim();
    if (text && box) {
      box.value = box.value.trim() ? box.value.trim() + " " + text : text;
      box.focus();
    }
  } catch (err) { banner(gateMessage(err), "err"); }
}

function resolveView(target, c) {
  const params = fill(target.params || {}, c);
  const next = { view: target.view };
  for (const p of viewParams(target.view)) next[p] = params[p] || "";
  return next;
}


/* ---- 弹窗 ---- */
function bindDropZones(form) {
  (form.querySelectorAll("[data-drop]") || []).forEach((box) => {
    const ta = box.querySelector("textarea,sl-textarea");
    if (!ta) return;
    box.addEventListener("dragover", (e) => { e.preventDefault(); box.classList.add("drag"); });
    box.addEventListener("dragleave", () => box.classList.remove("drag"));
    box.addEventListener("drop", (e) => {
      e.preventDefault(); box.classList.remove("drag");
      const file = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
      if (!file) return;
      const reader = new FileReader();
      reader.onload = () => { ta.value = String(reader.result || ""); ta.dispatchEvent(new Event("input")); };
      reader.readAsText(file);
    });
  });
}
function fieldHtml(f, ctx) {
  let val = f.value != null ? fill(f.value, ctx) : "";
  if (Array.isArray(val)) val = val.join("\n");
  const req = f.required ? ' data-required="1"' : "";
  const ro = f.readonly ? " readonly" : "";
  const ph = f.placeholder ? ` placeholder="${esc(f.placeholder)}"` : "";
  if (f.kind === "textarea") {
    const drop = f.drop ? ` data-drop="${esc(f.name)}"` : "";
    return `<div class="field"${drop}><label>${esc(f.label)}</label><sl-textarea name="${esc(f.name)}"${ph}${req}${ro}>${esc(val)}</sl-textarea></div>`;
  }
  if (f.kind === "select") {
    const opts = (f.options || []).map((o) =>
      `<sl-option value="${esc(o.value)}">${esc(o.label)}</sl-option>`).join("");
    return `<div class="field"><label>${esc(f.label)}</label><sl-select name="${esc(f.name)}" data-value="${esc(String(val))}">${opts}</sl-select></div>`;
  }
  const type = f.kind === "url" ? "url" : f.kind === "password" ? "password" : "text";
  return `<div class="field"><label>${esc(f.label)}</label><sl-input name="${esc(f.name)}" type="${type}" value="${esc(val)}"${ph}${req}${ro}></sl-input></div>`;
}
function readModalFields(formEl) {
  const fields = {};
  formEl.querySelectorAll("sl-input,sl-textarea,sl-select,input,select,textarea").forEach((el) => {
    if (!el.name) return;
    let v = el.value;
    if (Array.isArray(v)) v = v.join(",");
    fields[el.name] = typeof v === "string" ? v.trim() : (v == null ? "" : v);
  });
  return fields;
}
function openForm(form, ctx) {
  if (!form) return;
  MODAL_CTX = { form, ctx };
  const dlg = $("modal");
  dlg.label = fill(form.title || "", ctx);
  $("modal-hint").textContent = fill(form.hint || "", ctx);
  $("modal-err").className = "modal-err";
  $("modal-err").textContent = "";
  $("modal-form").innerHTML = (form.fields || []).map((f) => fieldHtml(f, ctx)).join("");
  // sl-select 选中值：渲染后按 data-value 回填
  $("modal-form").querySelectorAll("sl-select").forEach((el) => { el.value = el.dataset.value || ""; });
  bindDropZones($("modal-form"));
  $("modal-ok").textContent = fill((form.submit || {}).ok || uiText("ok"), ctx);
  $("modal-ok").disabled = false;
  dlg.show();
  if (typeof uiModal === "function") uiModal(true);
  const first = $("modal-form").querySelector("sl-input:not([readonly]),sl-textarea:not([readonly]),sl-select,input:not([readonly]),textarea,select");
  // Web Components 刚插入时内部 input 还没挂上，直接 focus 会抛 null；等 updateComplete 再聚焦。
  if (first) {
    const focus = () => { try { first.focus?.(); } catch (_) {} };
    if (first.updateComplete && typeof first.updateComplete.then === "function") first.updateComplete.then(focus, focus);
    else focus();
  }
  modalSubmit = async (fields) => {
    for (const f of form.fields || []) {
      if (f.required && !fields[f.name]) throw new Error(uiText("required_empty", f.label));
    }
    const c = { ...ctx, fields };
    banner(uiText("loading") || "加载中…", "info");
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
function closeModal() {
  const dlg = $("modal");
  if (dlg && dlg.open) dlg.hide();
  modalSubmit = null; MODAL_CTX = null; modalBusy = false;
  if (typeof uiModal === "function") uiModal(false);
}
function modalError(msg) {
  $("modal-err").className = "modal-err on";
  $("modal-err").textContent = msg;
}
let modalBusy = false;
async function submitModal() {
  if (!modalSubmit || modalBusy) return;
  if (typeof uiAllowed === "function" && !uiAllowed("modal_ok")) return;
  modalBusy = true;
  if (typeof uiEnter === "function") uiEnter("modal_ok");
  const okBtn = $("modal-ok");
  const okLabel = okBtn.textContent;
  okBtn.disabled = true;
  okBtn.textContent = uiText("loading") || "加载中…";
  try { await modalSubmit(readModalFields($("modal-form"))); }
  catch (err) {
    const msg = gateMessage(err);
    modalError(msg);
    banner(msg, "err");   // 表单失败也要换掉"加载中"，否则横幅一直挂着
  }
  finally {
    okBtn.disabled = false; okBtn.textContent = okLabel;
    modalBusy = false;
    if (typeof uiExit === "function") uiExit("modal_ok");
  }
}
$("modal-cancel").onclick = () => {
  if (typeof uiAllowed === "function" && !uiAllowed("modal_cancel")) return;
  closeModal();
};
$("modal-ok").onclick = submitModal;
$("modal-form").onsubmit = (e) => { e.preventDefault(); submitModal(); };
/* 遮罩点按关闭：过弹窗门禁；拒绝时拦下 sl-dialog 的默认关闭动作 */
$("modal").addEventListener("sl-request-close", (e) => {
  if (e.detail && e.detail.source !== "overlay") return;
  if (typeof uiAllowed === "function" && !uiAllowed("modal_backdrop")) { e.preventDefault(); }
});
