"""待办纯函数：会话内 todo 的增删查改成形，不碰盘、不取时钟。"""
from __future__ import annotations

STATUSES = ("pending", "doing", "done")
_ALIAS = {"todo": "pending", "open": "pending", "pending": "pending",
          "doing": "doing", "in_progress": "doing", "progress": "doing",
          "done": "done", "completed": "done", "closed": "done"}


def _status(raw):
    """状态归一：模型可能给中文或近义词，落到三态之一；认不出按 pending。"""
    text = str(raw or "").strip().lower()
    return _ALIAS.get(text, "pending")


def _item(raw, seq):
    """单条待办成形：id 缺省按序位补，status 归一，text 去空白。"""
    src = raw if isinstance(raw, dict) else {"text": raw}
    text = str(src.get("text") or src.get("title") or "").strip()
    if not text:
        return None
    return {"id": str(src.get("id") or "t%d" % seq).strip(),
            "text": text,
            "status": _status(src.get("status")),
            "note": str(src.get("note") or "").strip()}


def _norm(items, limit):
    """整表归一：逐条成形、按序位补号、去重 id、截到上限。"""
    out, seen = [], set()
    for idx, raw in enumerate(items or [], start=1):
        rec = _item(raw, idx)
        if not rec:
            continue
        if rec["id"] in seen:
            rec["id"] = "t%d" % (len(out) + 1)
            while rec["id"] in seen:
                rec["id"] = rec["id"] + "x"
        seen.add(rec["id"])
        out.append(rec)
        if len(out) >= limit:
            break
    return out


def _next_id(items):
    """新条 id：在已有 t<N> 里取最大号顺延，避免与手填 id 撞车。"""
    num = 0
    for rec in items or []:
        rid = str((rec or {}).get("id") or "")
        if rid.startswith("t") and rid[1:].isdigit():
            num = max(num, int(rid[1:]))
    return "t%d" % (num + 1)


def counts(items):
    """按状态计数，视图与提示都用同一套口径。"""
    out = {"total": 0, "pending": 0, "doing": 0, "done": 0}
    for rec in items or []:
        out["total"] += 1
        st = (rec or {}).get("status") or "pending"
        if st in out:
            out[st] += 1
    return out


def apply_ops(p):
    """待办动作成形：list/add/update/remove/clear/replace，回新表与是否有改动。

    纯数据变换：不动盘、不取时钟；越界或参数缺失只回错误码，不改原表。
    """
    items = _norm(p.get("todos") or [], int(p.get("limit")))
    args = p.get("args") or {}
    action = str(args.get("action") or "list").strip().lower()
    if action in ("list", "show", "read", "get"):
        return {"ok": True, "action": "list", "changed": False,
                "todos": items, "counts": counts(items)}
    if action in ("clear", "reset", "delete_all"):
        return {"ok": True, "action": "clear", "changed": bool(items),
                "todos": [], "counts": counts([])}
    if action in ("replace", "write", "set"):
        new = _norm(args.get("items") or args.get("todos") or [], int(p.get("limit")))
        return {"ok": True, "action": "replace", "changed": True,
                "todos": new, "counts": counts(new)}
    if action in ("add", "append", "create"):
        text = str(args.get("text") or args.get("title") or "").strip()
        if not text:
            return {"ok": False, "action": "add", "code": "bad_request",
                    "error": p.get("tpl", {}).get("text_required") or ""}
        rec = {"id": str(args.get("id") or _next_id(items)).strip(),
               "text": text, "status": _status(args.get("status") or "pending"),
               "note": str(args.get("note") or "").strip()}
        if any(x["id"] == rec["id"] for x in items):
            rec["id"] = _next_id(items)
        new = _norm(items + [rec], int(p.get("limit")))
        return {"ok": True, "action": "add", "changed": True,
                "todos": new, "counts": counts(new)}
    if action in ("update", "edit", "set_status", "patch"):
        rid = str(args.get("id") or "").strip()
        hit = [x for x in items if x["id"] == rid]
        if not hit:
            return {"ok": False, "action": "update", "code": "not_found",
                    "error": p.get("tpl", {}).get("id_missing") or ""}
        new = []
        for rec in items:
            if rec["id"] != rid:
                new.append(rec)
                continue
            text = str(args.get("text") or args.get("title") or "").strip()
            if text:
                rec["text"] = text
            if args.get("status"):
                rec["status"] = _status(args.get("status"))
            if args.get("note") is not None:
                rec["note"] = str(args.get("note") or "").strip()
            new.append(rec)
        return {"ok": True, "action": "update", "changed": True,
                "todos": new, "counts": counts(new)}
    if action in ("remove", "delete", "drop"):
        rid = str(args.get("id") or "").strip()
        rest = [x for x in items if x["id"] != rid]
        if len(rest) == len(items):
            return {"ok": False, "action": "remove", "code": "not_found",
                    "error": p.get("tpl", {}).get("id_missing") or ""}
        return {"ok": True, "action": "remove", "changed": True,
                "todos": rest, "counts": counts(rest)}
    return {"ok": False, "action": action, "code": "bad_request",
            "error": p.get("tpl", {}).get("action_unknown") or ""}


def brief(p):
    """视图摘要：条数与当前进行项，用来在群聊头部显示一行待办。"""
    items = p.get("todos") or []
    c = counts(items)
    cur = [x for x in items if x.get("status") == "doing"]
    return {"total": c["total"], "done": c["done"], "doing": c["doing"],
            "pending": c["pending"],
            "current": (cur[0].get("text") if cur else ""),
            "items": [{"id": x.get("id"), "text": x.get("text"),
                       "status": x.get("status")} for x in items]}


def context(p):
    """上下文段：把当前待办拼成一条 system 消息，模型每轮看得到自己的计划。"""
    items = _norm(p.get("todos") or [], int(p.get("limit")))
    tpl = p.get("tpl") or {}
    if not items:
        return {"message": None}
    head = tpl.get("heading") or ""
    rows = [tpl.get("row") or ""]
    lines = [head] if head else []
    for rec in items:
        lines.append(rows[0].format(id=rec["id"], status=rec["status"], text=rec["text"]) if rows[0] else
                     "%s [%s] %s" % (rec["id"], rec["status"], rec["text"]))
    if tpl.get("hint"):
        lines.append(tpl["hint"])
    return {"message": {"role": "system", "content": "\n".join(lines), "kind": "todo-context"}}
