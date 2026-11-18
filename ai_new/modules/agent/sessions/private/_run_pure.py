"""会话运行相关的纯函数：追加消息、改状态、收尾、状态计数。"""
from __future__ import annotations

# 推进/交付类工具：本轮调用过任一，才算有实质产出或编排动作；仅读类工具不算。
ADVANCE_TOOLS = {
    "artifact_write", "knowledge_write",
    "role_spawn", "role_task", "ticket_split", "ticket_close",
}


def appendmsg(p):
    rec = dict(p.get("rec") or {})
    msgs = list(rec.get("messages") or [])
    msg = {"role": p.get("role") or "user", "content": p.get("text") or ""}
    # 闭环注入的回催/复盘提示不是真实用户发言：打 note 标记，前端归系统条展示；
    # role 仍留 user，作为下一轮给模型的指令输入。标记只供展示，不进 LLM 载荷。
    if p.get("kind"):
        msg["kind"] = p["kind"]
    msgs.append(msg)
    rec["messages"] = msgs
    rec["updated"] = p.get("now") or ""
    if rec.get("status") in ("idle", "gone", None):
        rec["status"] = "queued"
    return rec


def _retrospect_enabled(p):
    """复盘开关：工单级标记优先；工单未显式设置时回退全局默认。兜底判定在纯函数内。"""
    ticket = p.get("retrospect_enabled")
    if ticket is not None:
        return bool(ticket)
    return bool(p.get("retrospect_default"))


def mark(p):
    rec = dict(p.get("rec") or {})
    rec["status"] = p.get("status") or "running"
    rec["updated"] = p.get("now") or ""
    return rec


def finish(p):
    rec = dict(p.get("rec") or {})
    limit = int(p.get("result_chars"))
    out = p.get("out") or {}
    base = list(rec.get("messages") or [])
    msgs = list(out.get("messages") or base)
    # 运行期间用户又发了消息：它们在 latest 里，不在本轮快照里，必须接在后面，否则被覆盖丢失
    fresh = list((p.get("latest") or {}).get("messages") or [])
    if len(fresh) > len(base):
        msgs = msgs + fresh[len(base):]
    rec["messages"] = msgs
    rec["status"] = "idle"
    rec["steps"] = out.get("steps") or 0
    # 滚动摘要：本轮 react 产出新摘要就回填；未产出（打断/失败/首轮）保留旧摘要。
    if out.get("summary") is not None:
        rec["summary"] = out.get("summary") or ""
    rec["updated"] = p.get("now") or ""
    meta = dict(rec.get("meta") or {})
    failed = out.get("failed")
    # 后端未答复的原因落进会话面，供视图透出；成功一轮后清除上一次的错误痕迹
    if failed:
        meta["last_error"] = {"code": failed.get("code") or "", "error": failed.get("error") or ""}
    else:
        meta.pop("last_error", None)
    rec["meta"] = meta
    last = out.get("last") or {}
    if out.get("cancelled"):
        rec["result"] = {"summary": "（已打断）", "at": p.get("now") or "", "cancelled": True}
    elif failed:
        rec["result"] = {"summary": (failed.get("error") or "后端未答复")[:limit],
                         "at": p.get("now") or "", "failed": True}
    else:
        rec["result"] = {"summary": (last.get("content") or "")[:limit], "at": p.get("now") or ""}
    return rec


def resume_plan(p):
    """启动回收：把上次进程崩溃前卡在 running 的会话分两类。

    resume  开关开且未超并发上限：标记中断痕迹、续跑计数 +1，复位 idle 交编排层重新驱动；
    stale   开关关或超上限：只复位 idle，等待后续人工/停滞扫描拉起。
    纯比较与字段定型，时间与文案由编排层给；落盘与派发都交编排层。
    """
    now = p.get("now") or ""
    resume_text = p.get("resume_text") or ""
    stale_text = p.get("stale_text") or ""
    enabled = bool(p.get("enabled", True))
    max_n = int(p.get("max") or 0)
    resume, stale, count = [], [], 0
    for item in p.get("rows") or []:
        rec = dict((item or {}).get("rec") or {})
        if rec.get("status") != "running":
            continue
        meta = dict(rec.get("meta") or {})
        path = (item or {}).get("path")
        if enabled and (max_n <= 0 or count < max_n):
            meta["last_error"] = {"code": "interrupted_on_boot", "error": resume_text}
            meta["resumed"] = int(meta.get("resumed") or 0) + 1
            rec["meta"] = meta
            rec["status"] = "idle"
            rec["updated"] = now
            resume.append({"path": path, "rec": rec, "id": rec.get("id")})
            count += 1
        else:
            meta["last_error"] = {"code": "interrupted_on_boot", "error": stale_text}
            rec["meta"] = meta
            rec["status"] = "idle"
            rec["updated"] = now
            stale.append({"path": path, "rec": rec, "id": rec.get("id")})
    return {"resume": resume, "stale": stale}


def reply(p):
    rec = p.get("rec") or {}
    msgs = rec.get("messages") or []
    last = next((m for m in reversed(msgs) if m.get("role") == "assistant"), None)
    return {"id": rec.get("id") or p.get("id"), "status": rec.get("status"),
            "content": (last or {}).get("content") or "", "steps": rec.get("steps", 0)}


def statsp(p):
    statuses = {}
    for it in p.get("items") or []:
        key = it.get("status") or "unknown"
        statuses[key] = statuses.get(key, 0) + 1
    return {"active": sum(1 for it in (p.get("items") or []) if it.get("status") == "running"),
            "max_concurrent": int(p.get("max") or 0), "statuses": statuses}


def waitingp(p):
    """判断本轮是否停在等待用户输入：末次 assistant 纯文本收尾，且自上一条用户消息
    起没有任何推进/交付类工具调用。纯计算，不碰盘、不取时钟。

    场景：需求信息不足时，PM 列出缺失项、向用户提问后结束本轮；此时尚无产物或编排
    动作，闭环不应回催、复盘或再驱动，保持 idle 等用户插话。
    """
    msgs = p.get("messages") or []
    if not msgs:
        return {"waiting": False, "reason": "empty"}
    last = msgs[-1]
    if last.get("role") != "assistant" or last.get("tool_calls"):
        return {"waiting": False, "reason": "active"}
    cut = 0
    for i in range(len(msgs) - 1, -1, -1):
        if msgs[i].get("role") == "user":
            cut = i + 1
            break
    segment = msgs[cut:]
    advanced = any(
        m.get("name") in ADVANCE_TOOLS
        for m in segment if m.get("role") == "tool"
    )
    if advanced:
        return {"waiting": False, "reason": "advanced"}
    return {"waiting": True, "reason": "awaiting_user"}


def flow_plan(p):
    """一轮收尾后的闭环动作清单：三态判定已在 library.review，这里只翻译成 effects。

    repush    回催缺口：追加回催消息、计数落盘、后台再跑一轮；
    pass      达标：追加复盘提示、后台再跑一轮，由模型自行决定是否沉淀知识；
    exhausted 超上限：标记卡点、记工单备注，不再回催。
    纯计算，不碰盘；写盘与再驱动都交 effect，由 runtime.apply 落地。
    """
    rec = dict(p.get("rec") or {})
    review = p.get("review") or {}
    verdict = review.get("verdict") or "pass"
    meta = dict(rec.get("meta") or {})
    meta["retries"] = review.get("retries") or 0
    rec["meta"] = meta
    sid = rec.get("id")
    effects = []
    if not sid:
        # 会话标识缺失：不写盘、不再驱动，避免落出 sessions/None.yaml 孤儿
        return {"verdict": verdict, "rec": rec, "effects": []}
    wait = waitingp({"messages": rec.get("messages")})
    if wait["waiting"]:
        # 停在等待用户输入：只落盘保持 idle，不回催、不复盘、不再驱动，等用户插话。
        effects.append({"kind": "write", "module": "agent/sessions",
                        "path": "sessions/%s.yaml" % sid, "value": rec})
        return {"verdict": "waiting", "waiting": True, "reason": wait["reason"],
                "rec": rec, "effects": effects}
    if verdict == "repush":
        rec = appendmsg({"rec": rec, "text": p.get("repush_text") or "",
                         "kind": "note", "now": p.get("now") or ""})
        effects.append({"kind": "write", "module": "agent/sessions",
                        "path": "sessions/%s.yaml" % sid, "value": rec})
        effects.append({"kind": "dispatch", "id": "session-run", "key": sid,
                        "input": {"id": sid}})
    elif verdict == "pass":
        already = bool(meta.get("retrospected"))
        enabled = _retrospect_enabled(p)
        if not already and enabled:
            meta["retrospected"] = True
            rec["meta"] = meta
            rec = appendmsg({"rec": rec, "text": p.get("retrospect_text") or "",
                             "kind": "note", "now": p.get("now") or ""})
            effects.append({"kind": "write", "module": "agent/sessions",
                            "path": "sessions/%s.yaml" % sid, "value": rec})
            effects.append({"kind": "dispatch", "id": "session-run", "key": sid,
                            "input": {"id": sid}})
        else:
            effects.append({"kind": "write", "module": "agent/sessions",
                            "path": "sessions/%s.yaml" % sid, "value": rec})
    else:
        effects.append({"kind": "write", "module": "agent/sessions",
                        "path": "sessions/%s.yaml" % sid, "value": rec})
        effects.append({"kind": "demand", "id": "ticket-note",
                        "input": {"id": p.get("ticket"),
                                  "text": p.get("exhausted_text") or ""}})
    return {"verdict": verdict, "rec": rec, "effects": effects}
