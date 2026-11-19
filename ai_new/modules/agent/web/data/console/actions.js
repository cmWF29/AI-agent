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
/* ---- 语音录音：开始/停止 → 识别 → 回填输入框，不自动发送 ---- */
function voiceBtnLabel(binding) {
  return String((binding.act && binding.act.label) || "语音");
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
    catch (err) { banner(gateMessage(err) || "麦克风不可用，请检查浏览器授权", "err"); return; }
    btn.classList.add("on");
    btn.textContent = "停止";
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

function resolveView(target, c) {  const params = fill(target.params || {}, c);
  const view = target.view;
  if (view === "projects") return { view: "projects" };
  if (view === "project") return { view: "project", project: params.project || "" };
  if (view === "ticket") return { view: "ticket", project: params.project || "", ticket: params.ticket || "" };
  if (view === "tools") return { view: "tools" };
  if (view === "skills") return { view: "skills" };
  if (view === "positions") return { view: "positions" };
  if (view === "position") return { view: "position", position: params.position || "" };
  if (view === "knowledge") return { view: "knowledge" };
  if (view === "logs") return { view: "logs" };
  if (view === "artifacts") return { view: "artifacts" };
  if (view === "user") return { view: "user" };
  if (view === "knowledge-doc") return { view: "knowledge-doc",
    layer: params.layer || "", name: params.name || "",
    project: params.project || "", ticket: params.ticket || "" };
  return { view: view };
}


/* ---- 弹窗 ---- */
function bindDropZones(form) {
  (form.querySelectorAll("[data-drop]") || []).forEach((box) => {
    const ta = box.querySelector("textarea");
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
function openForm(form, ctx) {
  if (!form) return;
  MODAL_CTX = { form, ctx };
  $("modal-title").textContent = fill(form.title || "", ctx);
  $("modal-hint").textContent = fill(form.hint || "", ctx);
  $("modal-err").className = "modal-err";
  $("modal-err").textContent = "";
  $("modal-form").innerHTML = (form.fields || []).map((f) => {
    let val = f.value != null ? fill(f.value, ctx) : "";
    if (Array.isArray(val)) val = val.join("\n");
    const req = f.required ? ' data-required="1"' : "";
    const ro = f.readonly ? " readonly" : "";
    const ph = f.placeholder ? ` placeholder="${esc(f.placeholder)}"` : "";
    if (f.kind === "textarea") {
      const drop = f.drop ? ` data-drop="${esc(f.name)}"` : "";
      return `<div class="field"${drop}><label>${esc(f.label)}</label><textarea name="${esc(f.name)}"${ph}${req}${ro}>${esc(val)}</textarea></div>`;
    }
    if (f.kind === "select") {
      const opts = (f.options || []).map((o) =>
        `<option value="${esc(o.value)}"${String(val) === String(o.value) ? " selected" : ""}>${esc(o.label)}</option>`).join("");
      return `<div class="field"><label>${esc(f.label)}</label><select name="${esc(f.name)}">${opts}</select></div>`;
    }
    const type = f.kind === "url" ? "url" : f.kind === "password" ? "password" : "text";
    return `<div class="field"><label>${esc(f.label)}</label><input name="${esc(f.name)}" type="${type}" value="${esc(val)}"${ph}${req}${ro}></div>`;
  }).join("");
  bindDropZones($("modal-form"));
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
