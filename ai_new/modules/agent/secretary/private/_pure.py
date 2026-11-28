"""项目秘书纯函数：队列成形、批量认领、后发优先合并、回填与失败回滚。

纯函数不碰盘、不取时钟、不读全局状态：状态由路由层从存储读进来，整份 dict 传入，
成形后整份交回；写盘是需求经 runtime.apply 执行的 effect。

队列条目状态机：
    pending -> processing  （claim_batch 认领整批）
    processing -> merged   （mark_merged 建单成功）
    processing -> pending  （mark_failed 建单/合并失败，回滚待处理）
    pending -> discarded   （discard 用户撤回）
    merged / discarded 为终态。
"""
from __future__ import annotations

# 需求结构化 brief 的五个字段（契约 §1/§3）。
FIELDS = ("background", "goal", "acceptance", "constraints", "priority")

STATUSES = ("pending", "processing", "merged", "discarded")
ACTIVE_CLAIM = ("pending",)
RECLAIMABLE = ("processing",)


def empty_state(project):
    """新建一份空队列状态；路由层在读不到档案时用，纯函数不自带默认数据。"""
    return {"project": str(project or ""), "messages": [], "batches": []}


def _find(messages, msg_id):
    for m in messages:
        if m.get("msg_id") == msg_id:
            return m
    return None


def enqueue(p):
    """入队（幂等）：同一 (project, msg_id) 重复投递回原条目，不新建、不二次建单。

    入参: state, msg_id, text, at, fields(可选结构化覆盖)
    回包: ok / created / entry / state
    """
    state = p.get("state") or {}
    messages = state.setdefault("messages", [])
    msg_id = str(p.get("msg_id") or "").strip()
    text = str(p.get("text") or "").strip()
    if not msg_id:
        return {"ok": False, "code": "msg_id_missing", "state": state}
    if not text:
        return {"ok": False, "code": "empty_text", "state": state}
    existing = _find(messages, msg_id)
    if existing is not None:
        return {"ok": True, "created": False, "entry": existing, "state": state}
    entry = {
        "msg_id": msg_id,
        "text": text,
        "at": p.get("at"),
        "status": "pending",
        "batch_id": "",
        "attempts": 0,
        "last_error": "",
        "merged_ticket": "",
        "merged_at": "",
        "source": str(p.get("source") or "user"),
        "timer_id": str(p.get("timer_id") or ""),
        "slot": str(p.get("slot") or ""),
        "fields": dict(p.get("fields") or {}),
    }
    messages.append(entry)
    return {"ok": True, "created": True, "entry": entry, "state": state}


def last_batch_no(p):
    """已有批次里的最大编号：进程重启后序号从这里续，不能从 0 重来。"""
    nums = []
    for b in (p.get("state") or {}).get("batches") or []:
        bid = str(b.get("batch_id") or "")
        if bid.startswith("B-") and bid[2:].isdigit():
            nums.append(int(bid[2:]))
    return max(nums or [0])


def claim_batch(p):
    """原子取整批：全部 pending -> processing，挂同一个 batch_id。

    入参: state, batch_id, claimed_at, roles_hint(可选)
    回包: ok / empty / batch / state。空队列 empty=True，不造批次、不建单。
    """
    state = p.get("state") or {}
    messages = state.setdefault("messages", [])
    batch_id = str(p.get("batch_id") or "").strip()
    pending = [m for m in messages if m.get("status") in ACTIVE_CLAIM]
    if not pending:
        return {"ok": True, "empty": True,
                "batch": {"batch_id": batch_id, "msg_ids": []}, "state": state}
    pending.sort(key=lambda m: (m.get("at") is None, m.get("at")))
    msg_ids = [m["msg_id"] for m in pending]
    for m in pending:
        m["status"] = "processing"
        m["batch_id"] = batch_id
    batch = {
        "batch_id": batch_id,
        "claimed_at": p.get("claimed_at"),
        "msg_ids": msg_ids,
        "brief": {},
        "sources": {},
        "ticket": "",
        "roles_hint": list(p.get("roles_hint") or []),
        "error": "",
    }
    state.setdefault("batches", []).append(batch)
    return {"ok": True, "empty": False, "batch": batch, "state": state}


def merge(p):
    """后发优先合并：按 at 升序逐条覆盖，同字段后发的非空值覆盖前面的；逐字段留来源 msg_id。

    显式撤回/废弃的条目不参与合并（状态 discarded），只列进 discarded。
    入参: entries（认领批次的整批条目）
    回包: brief / sources / msg_ids / discarded
    """
    entries = list(p.get("entries") or [])
    ordered = sorted(entries, key=lambda m: (m.get("at") is None, m.get("at")))
    active, discarded = [], []
    for m in ordered:
        if m.get("status") == "discarded":
            discarded.append(m.get("msg_id"))
        else:
            active.append(m)
    brief = {f: "" for f in FIELDS}
    sources = {}
    for m in active:
        fields = m.get("fields") or {}
        for f in FIELDS:
            val = str(fields.get(f) or "").strip()
            if val:
                brief[f] = val
                sources[f] = m.get("msg_id")
    msg_ids = [m.get("msg_id") for m in active]
    return {"brief": brief, "sources": sources,
            "msg_ids": msg_ids, "discarded": discarded}


def to_brief(p):
    """成形需求结构化 brief：合并结果 + 原文兜底；goal 缺省取最后一条活跃消息原文。

    入参: merged（merge 回包）, entries（整批条目，取兜底原文）
    回包: brief / sources / msg_ids
    """
    merged = p.get("merged") or {}
    entries = list(p.get("entries") or [])
    brief = dict(merged.get("brief") or {})
    sources = dict(merged.get("sources") or {})
    active = [m for m in entries if m.get("status") != "discarded"]
    active.sort(key=lambda m: (m.get("at") is None, m.get("at")))
    if not brief.get("goal") and active:
        last = active[-1]
        brief["goal"] = str(last.get("text") or "").strip()
        sources["goal"] = last.get("msg_id")
    for f in FIELDS:
        brief.setdefault(f, "")
    return {"brief": brief, "sources": sources,
            "msg_ids": merged.get("msg_ids") or [m.get("msg_id") for m in active]}


def mark_merged(p):
    """建单成功回填：批次条目 -> merged，记工单号与并入时间；批次记录挂工单。"""
    state = p.get("state") or {}
    messages = state.setdefault("messages", [])
    batch_id = str(p.get("batch_id") or "")
    ticket = str(p.get("ticket") or "")
    merged_at = p.get("merged_at")
    batch = next((b for b in state.get("batches", []) if b.get("batch_id") == batch_id), None)
    for m in messages:
        if m.get("batch_id") == batch_id and m.get("status") in RECLAIMABLE:
            m["status"] = "merged"
            m["merged_ticket"] = ticket
            m["merged_at"] = merged_at
    if batch is not None:
        batch["ticket"] = ticket
    return {"ok": True, "state": state}


def mark_failed(p):
    """失败回滚：批次内 processing 条目全部回 pending，attempts+1、last_error 写入；
    消息不丢、不自动出队；批次记录留错误供 UI 可见。
    """
    state = p.get("state") or {}
    messages = state.setdefault("messages", [])
    batch_id = str(p.get("batch_id") or "")
    error = str(p.get("error") or "").strip()
    batch = next((b for b in state.get("batches", []) if b.get("batch_id") == batch_id), None)
    for m in messages:
        if m.get("batch_id") == batch_id and m.get("status") in RECLAIMABLE:
            m["status"] = "pending"
            m["attempts"] = int(m.get("attempts") or 0) + 1
            m["last_error"] = error
            m["batch_id"] = ""
    if batch is not None:
        batch["error"] = error
    return {"ok": True, "state": state}


def discard(p):
    """撤回一条：pending/processing -> discarded；终态不许翻回。"""
    state = p.get("state") or {}
    messages = state.setdefault("messages", [])
    msg_id = str(p.get("msg_id") or "").strip()
    entry = _find(messages, msg_id)
    if entry is None:
        return {"ok": False, "code": "not_found", "state": state}
    if entry.get("status") in ("merged", "discarded"):
        return {"ok": False, "code": "invalid_state", "state": state}
    entry["status"] = "discarded"
    return {"ok": True, "entry": entry, "state": state}


def queue_view(p):
    """视图数据：counts / rows / batches。纯展示成形，文案标签由视图词表映射。"""
    state = p.get("state") or {}
    messages = state.get("messages") or []
    counts = {"pending": 0, "processing": 0, "merged": 0, "discarded": 0}
    rows = []
    for m in messages:
        status = m.get("status") or "pending"
        counts[status] = counts.get(status, 0) + 1
        rows.append({
            "msg_id": m.get("msg_id"),
            "text": m.get("text"),
            "at": m.get("at"),
            "status": status,
            "batch_id": m.get("batch_id"),
            "attempts": m.get("attempts") or 0,
            "last_error": m.get("last_error") or "",
            "merged_ticket": m.get("merged_ticket") or "",
            "merged_at": m.get("merged_at") or "",
            "source": m.get("source") or "user",
            "timer_id": m.get("timer_id") or "",
            "slot": m.get("slot") or "",
            "fields": dict(m.get("fields") or {}),
        })
    batches = []
    for b in state.get("batches") or []:
        batches.append({
            "batch_id": b.get("batch_id"),
            "claimed_at": b.get("claimed_at"),
            "msg_ids": b.get("msg_ids") or [],
            "brief": dict(b.get("brief") or {}),
            "sources": dict(b.get("sources") or {}),
            "ticket": b.get("ticket") or "",
            "roles_hint": list(b.get("roles_hint") or []),
            "error": b.get("error") or "",
        })
    # 群聊流只输出结构化事件，文案由路由层按词表渲染；队列/批次明细仍留在“群信息”页。
    events = [{
        "kind": "message", "text": r.get("text") or "", "at": r.get("at"),
        "msg_id": r.get("msg_id"), "status": r.get("status"),
    } for r in rows if (r.get("text") or "").strip()]
    for b in batches:
        events.append({
            "kind": "batch", "at": b.get("claimed_at"),
            "count": len(b.get("msg_ids") or []), "ticket": b.get("ticket") or "",
            "goal": str((b.get("brief") or {}).get("goal") or "").strip(),
            "error": b.get("error") or "", "batch_id": b.get("batch_id"),
        })
    events.sort(key=lambda e: (e.get("at") is None, e.get("at") or 0))
    return {"counts": counts, "rows": rows, "batches": batches, "events": events}


STATUS_TRANSITIONS = {
    "pending": ["processing", "discarded"],
    "processing": ["merged", "pending"],
    "merged": [],
    "discarded": [],
}


def status_machine(p):
    """队列状态机：回包状态枚举、合法迁移；带 entry 时附它当前状态与可去状态。

    契约稳定带 ``ok``：消息 id 给了但队列里找不到，回 ``ok: False / not_found``，
    不静默省略 entry 让调用方把"不存在"当成"空状态"。
    """
    msg_id = str(p.get("msg_id") or "").strip()
    entry = None
    if msg_id:
        entry = _find((p.get("state") or {}).get("messages") or [], msg_id)
    if msg_id and entry is None:
        return {"ok": False, "code": "not_found",
                "statuses": list(STATUSES), "transitions": STATUS_TRANSITIONS}
    out = {"ok": True, "statuses": list(STATUSES), "transitions": STATUS_TRANSITIONS}
    if entry is not None:
        out["entry"] = {"msg_id": entry.get("msg_id"), "status": entry.get("status"),
                        "next": STATUS_TRANSITIONS.get(entry.get("status") or "", [])}
    return out
