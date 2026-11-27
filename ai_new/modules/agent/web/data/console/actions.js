/* actions：唯一动作出口（view / modal / demand 三态）
*/
/* ---- 本地发件箱：IM 式乐观消息 ----
   发出的瞬间先落一条 pending 气泡（转圈）；成功转成已发送，失败标红并留下重发入口。
   消息 id 由前端生成并随需求带给后端，重发用同一个 id —— 后端按 (project,msg_id) 幂等，
   所以"点了重发其实已入队"不会变成两条。服务器回显同 msg_id 后本地条目自动清掉。 */
const OUTBOX_KEY = "ai_new_outbox_v1";
function outboxAll() {
  try {
    const arr0 = JSON.parse(localStorage.getItem(OUTBOX_KEY) || "[]");
    return Array.isArray(arr0) ? arr0 : [];
  } catch (_) { return []; }
}
function outboxSave(list) {
  try { localStorage.setItem(OUTBOX_KEY, JSON.stringify(list)); } catch (_) {}
}
function outboxFor(view, project) {
  return outboxAll().filter((e) => e && e.view === view && e.project === project);
}
function outboxAdd(entry) {
  const list = outboxAll().filter((e) => e.msg_id !== entry.msg_id);
  list.push(entry);
  outboxSave(list);
  return entry;
}
function outboxMark(msgId, status, error) {
  const list = outboxAll();
  const hit = list.find((e) => e.msg_id === msgId);
  if (!hit) return;
  hit.status = status;
  hit.error = error || "";
  hit.at = hit.at || Date.now() / 1000;
  outboxSave(list);
}
function outboxDrop(msgId) {
  outboxSave(outboxAll().filter((e) => e.msg_id !== msgId));
}
function outboxReconcile(view, project, msgs) {
  const ids = new Set(arr(msgs).map((m) => m && m.msg_id).filter(Boolean));
  const list = outboxAll();
  const keep = list.filter((e) => {
    if (!e || e.view !== view || e.project !== project) return true;
    // 失败的不因服务器已回显而丢掉：红条留着等用户自己重发或忽略
    return e.status === "failed" || !ids.has(e.msg_id);
  });
  if (keep.length !== list.length) outboxSave(keep);
}
function newMsgId() {
  return "c-" + Date.now().toString(36) + "-" + Math.random().toString(36).slice(2, 8);
}

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
    const form = FORMS[act.modal];
    if (!form) {
      banner("表单规格未加载：" + String(act.modal || ""), "err");
      return;
    }
    return openForm(form, fc);
  }
  if (!act.demand) return;
  const params = fill(act.params || {}, c);
  if (act.confirm && !confirm(String(fill(act.confirm, c)))) return;
  const flashText = act.flash ? String(fill(act.flash, c)) : "";
  // 乐观发送：只对声明了 outbox 的 composer 生效，其他表单/动作照旧等结果再刷新。
  let outMsgId = "";
  if (act.outbox) {
    outMsgId = newMsgId();
    params.msg_id = outMsgId;
    outboxAdd({ msg_id: outMsgId, view: state.view, project: params.project || state.project,
                demand: act.demand, text: String(params.text || ""),
                at: Date.now() / 1000, status: "sending", error: "" });
    const ta = document.querySelector("#view-body .composer textarea");
    if (ta && act.clear) ta.value = "";
    await render({ keepBanner: true });
  }
  try {
    // 拆解这类长动作可能跑几十秒，先给一条"加载中"，成功/失败再被下面的提示覆盖。
    banner(uiText("loading") || "加载中…", "info");
    const res = await run(act.demand, params);
    if (outMsgId) {
      outboxMark(outMsgId, "sent", "");
      const at = res && res.entry && res.entry.at;
      if (at) {
        const list = outboxAll();
        const hit = list.find((e) => e.msg_id === outMsgId);
        if (hit) { hit.at = at; outboxSave(list); }
      }
    }
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
    const msg = gateMessage(err);
    if (outMsgId) {
      outboxMark(outMsgId, "failed", msg);
      await render({ keepBanner: true });
    }
    banner(msg, "err");
  }
}
/* 点击失败气泡上的「重发」：同 msg_id 再打一次，后端幂等保证不会重复入队。 */
async function retryOutbox(msgId) {
  const hit = outboxAll().find((e) => e.msg_id === msgId);
  if (!hit) return;
  outboxMark(msgId, "sending", "");
  await render({ keepBanner: true });
  try {
    if (!hit.demand) throw new Error(uiText("msg_no_demand"));
    const params = { project: hit.project, text: hit.text, msg_id: hit.msg_id };
    const res = await run(hit.demand, params);
    outboxMark(msgId, "sent", "");
    const at = res && res.entry && res.entry.at;
    if (at) {
      const list = outboxAll();
      const it = list.find((e) => e.msg_id === msgId);
      if (it) { it.at = at; outboxSave(list); }
    }
    banner(uiText("msg_sent") || "已发送", "ok");
  } catch (err) {
    outboxMark(msgId, "failed", gateMessage(err));
    banner(gateMessage(err), "err");
  }
  await render({ keepBanner: true });
}
/* ---- 澄清问题卡：选项只改本地选中态，统一提交才发消息 ----
   业界聊天机器人常用“快捷选项 + 自由输入兜底”：选项把长句压成一次点选，
   开放项仍保留输入框；提交后答案作为一条普通人消息回给 PM，不另造通道。 */
function pickQuestionOption(el) {
  const card = el.closest(".q-card");
  if (!card || card.classList.contains("done")) return;
  const item = el.closest(".q-item");
  if (!item) return;
  const multi = el.dataset.multi === "1";
  if (!multi) item.querySelectorAll(".q-opt.on").forEach((b) => {
    b.classList.remove("on"); b.setAttribute("aria-pressed", "false");
  });
  const on = el.classList.toggle("on");
  el.setAttribute("aria-pressed", on ? "true" : "false");
}
function collectQuestionAnswers(card) {
  const qid = String(card.dataset.qid || "");
  const out = [];
  card.querySelectorAll(".q-item").forEach((item) => {
    const qi = item.dataset.qi;
    const q = ((item.querySelector(".q-title") || {}).innerText || "").replace(/^\s*\d+\s*/, "").replace(/单选|可多选/, "").trim();
    const vals = [...item.querySelectorAll(".q-opt.on")].map((b) => String(b.dataset.qv || "").trim()).filter(Boolean);
    const box = item.querySelector(".q-other");
    const extra = box ? String(box.value || "").trim() : "";
    if (extra && !vals.includes(extra)) vals.push(extra);
    if (vals.length) out.push({ qid: qid + "#" + qi, question: q, values: vals });
  });
  return { qid, answers: out };
}
async function submitQuestionCard(el) {
  const card = el.closest(".q-card");
  if (!card || card.classList.contains("done")) return;
  const { qid, answers } = collectQuestionAnswers(card);
  if (!answers.length) {
    banner(uiText("q_missing") || "请至少回答一项", "err");
    return;
  }
  const lines = answers.map((a, i) => `${i + 1}. ${a.question || "问题"}\n   答：${a.values.join("；")}`);
  const text = (uiText("q_answer_head") || "【澄清答复】") + "\n" + lines.join("\n");
  const tid = (typeof state !== "undefined" && state.ticket) || "";
  const demand = String(card.dataset.demand || "");
  if (!tid || !demand) {
    banner(uiText("need_param") || "缺少工单", "err");
    return;
  }
  await run(demand, { id: tid, text, qid, answers });
  banner(uiText("msg_sent") || "已发送", "ok");
  await render({ keepBanner: true });
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
  // 写后必看新结果：规格里的 reload 不能被解析掉，否则会命中旧页缓存
  if (target.reload) next.reload = true;
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
    const mul = f.multiple ? " multiple" : "";
    const help = f.hint ? `<div class="field-hint">${esc(f.hint)}</div>` : "";
    return `<div class="field"><label>${esc(f.label)}</label><sl-select name="${esc(f.name)}" data-value="${esc(String(val))}"${mul}>${opts}</sl-select>${help}</div>`;
  }
  const type = f.kind === "url" ? "url" : f.kind === "password" ? "password" : "text";
  return `<div class="field"><label>${esc(f.label)}</label><sl-input name="${esc(f.name)}" type="${type}" value="${esc(val)}"${ph}${req}${ro}></sl-input></div>`;
}
function readModalFields(formEl) {
  const fields = {};
  formEl.querySelectorAll("sl-input,sl-textarea,sl-select,input,select,textarea").forEach((el) => {
    if (!el.name) return;
    let v = el.value;
    // 多选控件保持数组，交给需求原样传给能力；其余控件仍按纯文本归一。
    if (Array.isArray(v)) fields[el.name] = v.map((x) => String(x).trim()).filter(Boolean);
    else fields[el.name] = typeof v === "string" ? v.trim() : (v == null ? "" : v);
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
  $("modal-form").querySelectorAll("sl-select").forEach((el) => {
    const raw = el.dataset.value || "";
    el.value = el.multiple ? raw.split(",").filter(Boolean) : raw;
  });
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
    // 表单成功提交会先 closeModal；此时页面状态机可能停在 modal，
    // 后续卡片/头部动作会被门禁拒绝。弹窗已关就回到 idle；校验失败弹窗仍开着则保持 modal。
    if (typeof uiModal === "function" && !($("modal").open)) uiModal(false);
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
