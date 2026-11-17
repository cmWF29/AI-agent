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
    msgs.append({"role": "user", "content": p.get("text") or ""})
    rec["messages"] = msgs
    rec["updated"] = p.get("now") or ""
    if rec.get("status") in ("idle", "gone", None):
        rec["status"] = "queued"
    return rec


def mark(p):
    rec = dict(p.get("rec") or {})
    rec["status"] = p.get("status") or "running"
    rec["updated"] = p.get("now") or ""
    return rec


def finish(p):
    rec = dict(p.get("rec") or {})
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
        rec["result"] = {"summary": (failed.get("error") or "后端未答复")[:500],
                         "at": p.get("now") or "", "failed": True}
    else:
        rec["result"] = {"summary": (last.get("content") or "")[:500], "at": p.get("now") or ""}
    return rec


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
                         "now": p.get("now") or ""})
        effects.append({"kind": "write", "module": "agent/sessions",
                        "path": "sessions/%s.yaml" % sid, "value": rec})
        effects.append({"kind": "dispatch", "id": "session-run", "key": sid,
                        "input": {"id": sid}})
    elif verdict == "pass":
        already = bool(meta.get("retrospected"))
        if not already:
            meta["retrospected"] = True
            rec["meta"] = meta
            rec = appendmsg({"rec": rec, "text": p.get("retrospect_text") or "",
                             "now": p.get("now") or ""})
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
