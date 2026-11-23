"""文档修订版本元数据：纯函数，不读盘、不取时间、不调服务。

版本令牌随读返回；写时校验令牌，冲突显式返回双方版本/作者，不静默覆盖。
修订历史只保留最近 ``keep`` 条，便于追溯而不无限膨胀。
"""
from __future__ import annotations


def token_int(token):
    """令牌归一为整数；空/非数字按 0 处理。"""
    try:
        return int(token)
    except (TypeError, ValueError):
        return 0


def init_meta(author, now, content):
    """新建文档元数据：版本从 1 起，首条历史即初始版本。"""
    chars = len(content or "")
    entry = {"version": 1, "author": author or "", "updated": now or "",
             "chars": chars, "forced": False}
    return {"version": 1, "author": author or "", "updated": now or "",
            "chars": chars, "history": [entry]}


def check(meta, token):
    """写前版本校验：客户端令牌必须等于当前版本。

    返回 ``{ok, current_version, current_author, token}``；不等即冲突，交由上层
    回 409，不做静默覆盖。
    """
    current = (meta or {}).get("version") or 0
    client = token_int(token)
    ok = client == current
    return {"ok": ok, "current_version": current,
            "current_author": (meta or {}).get("author", ""), "token": token}


def bump(meta, author, now, content, keep=20, forced=False):
    """版本 +1 并追加一条历史；历史只留最近 ``keep`` 条。forced 标记显式覆盖。"""
    m = dict(meta or {})
    m["version"] = (m.get("version") or 0) + 1
    m["author"] = author or ""
    m["updated"] = now or ""
    m["chars"] = len(content or "")
    hist = list(m.get("history") or [])
    hist.append({"version": m["version"], "author": m["author"],
                 "updated": m["updated"], "chars": m["chars"], "forced": bool(forced)})
    m["history"] = hist[-keep:]
    return m
