"""定时器纯函数：规格校验、配额、幂等键、槽位挑选、审计条目与视图成形。

本层不读盘、不取时间、不碰编解码：时刻推算归 clock，落盘效果由需求 runtime.apply 落地。
"""
from __future__ import annotations

KINDS = ("once", "cron")
ACTIONS = ("notify", "spawn_ticket")
SCOPES = ("project", "ticket", "global")


def normalize_caller(payload):
    """调用方上下文归一：缺省按项目作用域；scope 不由模型随意抬到 global。"""
    raw = payload.get("caller") or {}
    if not isinstance(raw, dict):
        raw = {}
    scope = str(raw.get("scope") or "project")
    if scope not in SCOPES:
        scope = "project"
    return {
        "scope": scope,
        "project": str(raw.get("project") or payload.get("project") or ""),
        "ticket": str(raw.get("ticket") or payload.get("ticket") or ""),
        "session": str(raw.get("session") or payload.get("source_session") or ""),
        "role": str(raw.get("role") or payload.get("creator") or ""),
    }


def idem_signature(payload):
    """幂等键原始串：项目|标题|类型|表达式|时区|动作|工单|岗位。

    键里没有时间戳与随机数，同一件事重投/崩溃重放算出来的键必然相同。
    """
    fields = ("project", "title", "kind", "expr", "tz", "action", "ticket", "role")
    return "|".join("" if payload.get(k) is None else str(payload.get(k)) for k in fields)


def validate_shape(payload):
    """必填与枚举形状校验；表达式/时区/间隔的时刻校验归 clock.schedule_next。"""
    if payload.get("kind") not in KINDS:
        return {"ok": False, "code": "bad_kind"}
    if payload.get("action") not in ACTIONS:
        return {"ok": False, "code": "bad_action"}
    if not str(payload.get("expr") or "").strip():
        return {"ok": False, "code": "bad_cron"}
    if not str(payload.get("title") or "").strip():
        return {"ok": False, "code": "bad_title"}
    if not str(payload.get("project") or "").strip():
        return {"ok": False, "code": "missing_project"}
    return {"ok": True}


def validate_spec(payload, schedule):
    """规格校验收口：形状 + clock 推算结果 → next_at 或错误码。

    schedule 为 clock.schedule_next 的返回；错误码 bad_cron/bad_tz/interval_too_short 原样透传。
    """
    shape = validate_shape(payload)
    if shape["ok"] is False:
        return shape
    if not schedule.get("ok"):
        return {"ok": False, "code": schedule.get("code") or "bad_cron"}
    return {"ok": True, "next_at": schedule.get("ts"), "iso": schedule.get("iso"),
            "tz": payload.get("tz") or "", "slot": schedule.get("slot")}


def quota_check(records, cfg):
    """项目内配额：在档定时器数 ≥ 上限 → quota_exceeded。"""
    limit = int((cfg or {}).get("max_per_project") or 0)
    count = len(records or [])
    if limit and count >= limit:
        return {"ok": False, "code": "quota_exceeded", "count": count, "limit": limit}
    return {"ok": True, "count": count, "limit": limit}


def authorize(caller, rec, action):
    """作用域裁决：project 管本项目；ticket 再加工单相等；global 放行跨项目。

    越权读取与修改一律 forbidden_scope；先过滤后返回，不靠前端隐藏。
    """
    scope = (caller or {}).get("scope") or "project"
    if scope == "global":
        return {"ok": True}
    if scope == "ticket":
        if str(rec.get("project") or "") != str((caller or {}).get("project") or ""):
            return {"ok": False, "code": "forbidden_scope", "reason": "cross_project"}
        if str(rec.get("ticket") or "") != str((caller or {}).get("ticket") or ""):
            return {"ok": False, "code": "forbidden_scope", "reason": "cross_ticket"}
        return {"ok": True}
    # project 作用域
    if str(rec.get("project") or "") != str((caller or {}).get("project") or ""):
        return {"ok": False, "code": "forbidden_scope", "reason": "cross_project"}
    return {"ok": True}


def filter_scope(records, caller):
    """按作用域过滤可见记录：global 全量，project/ticket 各自收口。"""
    out = []
    for rec in records or []:
        verdict = authorize(caller, rec, "list")
        if verdict["ok"]:
            out.append(rec)
    return out


def due_select(rec, slots, fired, max_catchup):
    """挑出未执行过的到期槽位，受 max_catchup 上限截断；同槽位重复 tick 不重复触发。"""
    fired = set(fired or [])
    pending = [s for s in (slots or []) if s not in fired]
    if max_catchup and len(pending) > max_catchup:
        pending = pending[:max_catchup]
    return pending


def run_record(rec, slot, ok, detail, attempt, now, action):
    """执行审计条目：成功/失败都留痕；失败保留槽位待重试，attempt 累加回退。"""
    return {
        "at": now,
        "slot": slot,
        "ok": bool(ok),
        "detail": detail or "",
        "attempt": int(attempt or 0),
        "action": action,
        "timer_id": rec.get("id"),
        "project": rec.get("project"),
        "ticket": rec.get("ticket"),
    }


def last_run_view(rec):
    """最近一次结果视图形状：at/ok/detail/attempt。"""
    last = rec.get("last_run") or {}
    return {
        "at": last.get("at"),
        "ok": last.get("ok"),
        "detail": last.get("detail") or "",
        "attempt": last.get("attempt") or 0,
    }


def view_row(rec):
    """列表给 UI 的字段（契约 §10.2）。"""
    return {
        "id": rec.get("id"),
        "project": rec.get("project"),
        "ticket": rec.get("ticket") or "",
        "role": rec.get("role") or "",
        "title": rec.get("title"),
        "kind": rec.get("kind"),
        "expr": rec.get("expr"),
        "kind_expr": "%s · %s" % (rec.get("kind"), rec.get("expr")),
        "tz": rec.get("tz") or "",
        "next_at": rec.get("next_at"),
        "status": rec.get("status"),
        "last_run": last_run_view(rec),
        "creator": rec.get("creator"),
        "source_session": rec.get("source_session"),
        "created": rec.get("created"),
    }


def view_rows(records):
    return [view_row(rec) for rec in (records or [])]


def index_stats(rows, now):
    """聚合统计：活动/暂停/本日触发。"""
    today = str(now or "")[:10]
    counts = {"active": 0, "paused": 0, "today": 0, "done": 0, "error": 0}
    for row in rows or []:
        status = row.get("status") or ""
        if status in counts:
            counts[status] += 1
        last = row.get("last_run") or {}
        if str(last.get("at") or "")[:10] == today and last.get("ok"):
            counts["today"] += 1
    return counts
