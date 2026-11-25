"""项目模块：项目档案。只有纯函数，取数/落盘由需求完成。"""
from __future__ import annotations

from .private import _pure


def _msg_tpl(ctx):
    """消息模板表：项目模块自己的 data，读不到就退化成空。"""
    row = ctx.api.call("store.read", {
        "module": "agent/projects", "path": "messages.yaml"}, caller=None)
    return row.get("value") or {}


def _cfg_paths(ctx):
    row = ctx.api.call("config.get", {"key": "projects.paths"}, caller=None)
    return row.get("value") or {}


def _cfg_logs(ctx):
    row = ctx.api.call("config.get", {"key": "logs.paths"}, caller=None)
    return row.get("value") or {}


def _record(paths, pid):
    t = (paths or {}).get("record") or ""
    return t.format(id=pid) if t else pid


def _project_root(ctx, pid, root):
    """项目根路径的唯一校验入口：非空时必须经 store 的 absolute/realpath/越界守卫。

    返回规范化后的绝对路径；空串表示继续使用系统默认数据目录（legacy 模式）。
    """
    root = str(root or "").strip()
    if not root:
        return ""
    ws = ctx.api.call("store.workspace", {
        "project": pid, "root": root}, caller=None)
    if not ws.get("ok"):
        raise ctx.ApiError(ws.get("error") or "项目路径不可用",
                           code=ws.get("code") or "bad_root",
                           status=int(ws.get("status") or 400))
    return ws.get("root") or ""


def setup(ctx):
    """装配入口：注册纯函数；组合逻辑在 demand_engine/data/demands/projects-*.json。"""
    for name, fn in [
        ("projects.build", _pure.build),
        ("projects.view", _pure.view),
        ("projects.present", _pure.present),
        ("projects.screen", _pure.screen),
        ("projects.tree", _pure.tree),
        ("projects.archive", _pure.archive),
        ("projects.missing", _pure.missing),
        ("projects.record_path", _pure.record_path),
        ("projects.rooted", _pure.rooted),
        ("projects.conflict", _pure.conflict),
        ("projects.deleted", _pure.deleted),
        ("projects.renamed", _pure.renamed),
        ("projects.override_parts", _pure.override_parts),
        ("projects.toggle_override", _pure.toggle_override),
    ]:
        ctx.api.register(name, _as_handler(fn), module="projects")
    ctx.api.register("projects.create", _route_create, "新建项目：归一→造档→查重→落盘→回执", module="projects")
    ctx.api.register("projects.set_root", _route_set_root, "设置项目路径：校验绝对路径→写档案→回执", module="projects")
    ctx.api.register("projects.workspace", _route_workspace, "解析项目工作区：公共层与工单隔离目录", module="projects")
    ctx.api.register("projects.remove", _route_remove, "删除项目：purge 真删，否则归档", module="projects")
    ctx.api.register("projects.rename", _route_rename, "项目改名：查重→迁档→工单引用改挂", module="projects")
    ctx.api.register("projects.toggle", _route_toggle, "项目启停：翻转覆盖层禁用清单，定义正文仍指向公共库", module="projects")
    return True


def _route_create(ctx, payload):
    name = str(payload.get("name") or "").strip()
    if not name:
        return {"ok": False, "code": "missing_name", "status": 400,
                "error": "项目名不能为空"}
    paths = _cfg_paths(ctx)
    pid = ctx.api.call("store.id", {"value": name}, caller=None)
    root = _project_root(ctx, pid.get("id"), payload.get("root"))
    now = ctx.api.call("clock.now", {}, caller=None)
    rec = ctx.api.call("projects.build", {
        "id": pid.get("id"), "name": name,
        "root": root,
        "created": now.get("ts")}, caller=None)
    ex = ctx.api.call("store.exists", {"module": "agent/projects",
        "path": _record(paths, pid.get("id"))}, caller=None)
    if ex.get("exists"):
        return ctx.api.call("projects.conflict",
            {"id": pid.get("id"), "tpl": _msg_tpl(ctx).get("conflict")}, caller=None)
    view = ctx.api.call("projects.view", {"rec": rec}, caller=None)
    view["effects"] = [{"kind": "write", "module": "agent/projects",
                "path": _record(paths, pid.get("id")), "value": rec}]
    return view


def _route_set_root(ctx, payload):
    """设置项目路径：读档→守卫→路径校验→写档案；不迁移既有数据，只改变后续工作区解析。"""
    pid = ctx.api.call("store.id", {"value": payload.get("id")}, caller=None)
    paths = _cfg_paths(ctx)
    row = ctx.api.call("store.read", {"module": "agent/projects",
        "path": _record(paths, pid.get("id"))}, caller=None)
    if row.get("value") is None:
        return ctx.api.call("projects.missing",
            {"id": pid.get("id"), "tpl": _msg_tpl(ctx).get("missing")}, caller=None)
    guard = _pure.guard_writable({"rec": row.get("value"), "tpl": _msg_tpl(ctx)})
    if guard.get("ok") is False:
        return guard
    root = _project_root(ctx, pid.get("id"), payload.get("root"))
    now = ctx.api.call("clock.now", {}, caller=None)
    rec = ctx.api.call("projects.rooted", {
        "rec": row.get("value"), "root": root,
        "now": now.get("ts")}, caller=None)
    view = ctx.api.call("projects.view", {"rec": rec}, caller=None)
    view["effects"] = [{"kind": "write", "module": "agent/projects",
                        "path": _record(paths, pid.get("id")), "value": rec}]
    return view


def _route_workspace(ctx, payload):
    """项目工作区只读视图：根路径、公共层、工单隔离目录与当前隔离档位。"""
    pid = ctx.api.call("store.id", {"value": payload.get("id")}, caller=None)
    paths = _cfg_paths(ctx)
    row = ctx.api.call("store.read", {"module": "agent/projects",
        "path": _record(paths, pid.get("id"))}, caller=None)
    if row.get("value") is None:
        return ctx.api.call("projects.missing",
            {"id": pid.get("id"), "tpl": _msg_tpl(ctx).get("missing")}, caller=None)
    rec = row.get("value") or {}
    ws = ctx.api.call("store.workspace", {
        "project": pid.get("id"), "ticket": payload.get("ticket") or "",
        "cwd": payload.get("cwd") or "",
        "root": rec.get("root") or ""}, caller=None)
    ws = dict(ws or {})
    ws["project"] = {"id": rec.get("id") or pid.get("id"),
                     "name": rec.get("name") or "", "root": rec.get("root") or "",
                     "archived": rec.get("archived") is True}
    dirs = ws.get("dirs") or {}
    tickets = (dirs.get("tickets") or "").rstrip("/")
    pattern = (tickets + "/<工单ID>") if tickets else ""
    ws["ticket_pattern"] = pattern
    ws["layers"] = [
        {"name": "项目根", "path": ws.get("root") or "未配置（系统默认目录）",
         "scope": "外层边界；工单会话不整体挂载"},
        {"name": "公共文档", "path": dirs.get("documents") or "—",
         "scope": "项目内公共"},
        {"name": "公共日志", "path": dirs.get("logs") or "—",
         "scope": "项目内公共"},
        {"name": "公共交付件", "path": dirs.get("artifacts") or "—",
         "scope": "项目内公共"},
        {"name": "工单工作区", "path": pattern or "—",
         "scope": "仅本工单可见"},
    ]
    return ws


def _route_toggle(ctx, payload):
    """项目启停闭环：读档 → 纯函数翻转覆盖层禁用清单 → 写回项目档案；定义正文不回写公共库。

    项目档案不存在返 missing；类型/标识非法由纯函数返错误形状，不落盘。
    """
    pid = ctx.api.call("store.id", {"value": payload.get("project")}, caller=None)
    paths = _cfg_paths(ctx)
    row = ctx.api.call("store.read", {"module": "agent/projects",
        "path": _record(paths, pid.get("id"))}, caller=None)
    if row.get("value") is None:
        return ctx.api.call("projects.missing",
            {"id": pid.get("id"), "tpl": _msg_tpl(ctx).get("missing")}, caller=None)
    guard = _pure.guard_writable({"rec": row.get("value"), "tpl": _msg_tpl(ctx)})
    if guard.get("ok") is False:
        return guard
    now = ctx.api.call("clock.now", {}, caller=None)
    cascaded = []
    cascaded_names = []
    if payload.get("kind") == "tools" and payload.get("enabled") is False:
        lib = ctx.api.call("store.read", {"module": "agent/library",
                                          "path": "roles.yaml"}, caller=None)
        tool_id = str(payload.get("id") or "")
        for role_id, role in (lib.get("value") or {}).items():
            if tool_id in [str(t) for t in ((role or {}).get("tools") or [])]:
                cascaded.append(str(role_id))
                cascaded_names.append(str((role or {}).get("cn") or role_id))
    rec = ctx.api.call("projects.toggle_override", {
        "rec": row.get("value"), "kind": payload.get("kind"),
        "id": payload.get("id"), "enabled": payload.get("enabled"),
        "cascade_roles": cascaded,
        "now": now.get("ts"), "tpl": _msg_tpl(ctx)}, caller=None)
    if rec.get("ok") is False:
        return rec
    view = ctx.api.call("projects.view", {"rec": rec}, caller=None)
    view["overrides"] = ctx.api.call("projects.override_parts",
                                     {"rec": rec}, caller=None)
    view["cascaded"] = cascaded
    view["cascaded_names"] = cascaded_names
    view["effects"] = [{"kind": "write", "module": "agent/projects",
                        "path": _record(paths, pid.get("id")), "value": rec}]
    return view


def _purge_tickets(ctx, pid):
    """真删项目时清掉它名下的工单：工单必属项目，不能留指向空项目的孤儿单。

    返回 (effects, 被删工单 id 集合)；会话只记 ticket 不记 project，要靠这组 id 回扫。
    """
    effects = []
    ticket_ids = []
    paths = _cfg_paths(ctx)
    listed = ctx.api.call("store.glob", {
        "module": "agent/tickets", "pattern": paths.get("ticket_glob") or ""}, caller=None)
    for rel in listed.get("items") or []:
        # 路径形状：projects/<project>/tickets/<id>/ticket.yaml
        segs = str(rel).split("/")
        if len(segs) != 5:
            continue
        if segs[1] != pid:
            continue
        ticket_ids.append(segs[3])
        tp = paths.get("ticket_prefix") or ""
        effects.append({"kind": "remove_dir", "module": "agent/tickets",
                        "path": tp.format(project=segs[1], seg=segs[3]) if tp else segs[3]})
    return effects, ticket_ids


def _purge_sessions(ctx, ticket_ids):
    """清掉挂在被删工单上的 PM/角色会话；会话记录只记 ticket，按工单集合匹配。

    删文件前先 stop 后台线程并等收尾：未定稿的线程若在 remove 后再落盘，会把会话写回。
    """
    if not ticket_ids:
        return []
    ids = set(ticket_ids)
    effects = []
    removed = []
    listed = ctx.api.call("store.glob", {
        "module": "agent/logs",
        "pattern": _cfg_logs(ctx).get("session_glob") or ""}, caller=None)
    for rel in listed.get("items") or []:
        row = ctx.api.call("store.read", {
            "module": "agent/logs", "path": rel}, caller=None)
        rec = row.get("value") or {}
        if rec.get("ticket") not in ids:
            continue
        sid = rec.get("id") or str(rel.rsplit("/", 1)[-1])[:-5]
        ctx.runtime.stop(sid)
        effects.append({"kind": "remove", "module": "agent/logs", "path": rel})
        removed.append(rel)
    if removed:
        purge = ctx.api.call("logs.purge", {"paths": removed}, caller=None)
        effects += purge.get("effects") or []
    return effects


def _purge_ticket_knowledge(ctx, ticket_ids):
    """清掉被删工单的 ticket 层知识；该层前缀 tickets/<tid>，tid 经 store.id 归一为小写。"""
    effects = []
    # 知识层的 ticket 前缀是知识自己的模板，不能拿项目层模板顶替。
    kp = ctx.api.call("config.get", {"key": "knowledge.paths"}, caller=None).get("value") or {}
    tp = kp.get("ticket") or ""
    for tid in ticket_ids:
        nid = ctx.api.call("store.id", {"value": tid}, caller=None).get("id")
        effects.append({"kind": "remove_dir", "module": "agent/knowledge",
                        "path": tp.format(ticket=nid) if tp else nid})
    return effects


def _purge_project_tree(ctx, module, pid):
    """清掉项目在产物/知识层的整棵前缀目录；目录不存在时 remove_dir 自报未删，不报错。"""
    t = _cfg_paths(ctx).get("project_dir") or ""
    return [{"kind": "remove_dir", "module": module,
             "path": t.format(pid=pid) if t else pid}]


def _route_remove(ctx, payload):
    paths = _cfg_paths(ctx)
    pid = ctx.api.call("store.id", {"value": payload.get("id")}, caller=None)
    row = ctx.api.call("store.read", {"module": "agent/projects",
        "path": _record(paths, pid.get("id"))}, caller=None)
    if payload.get("purge") is True:
        # 彻底删除不受归档限制：归档是"只读封存"，不是"防删除"；删掉归档项目是合法收尾。
        ticket_effects, ticket_ids = _purge_tickets(ctx, pid.get("id"))
        effects = list(ticket_effects)
        effects += _purge_sessions(ctx, ticket_ids)
        effects += _purge_ticket_knowledge(ctx, ticket_ids)
        effects += _purge_project_tree(ctx, "agent/artifacts", pid.get("id"))
        effects += _purge_project_tree(ctx, "agent/knowledge", pid.get("id"))
        effects.append({"kind": "remove", "module": "agent/projects",
                        "path": _record(paths, pid.get("id"))})
        out = ctx.api.call("projects.deleted", {"id": pid.get("id")}, caller=None)
        out["effects"] = effects
        return out
    paths2 = _cfg_paths(ctx)
    listed = ctx.api.call("store.glob", {
        "module": "agent/tickets", "pattern": paths2.get("ticket_glob") or ""}, caller=None)
    open_ids = []
    for rel in listed.get("items") or []:
        segs = str(rel).split("/")
        if len(segs) != 5 or segs[1] != pid.get("id"):
            continue
        trow = ctx.api.call("store.read", {"module": "agent/tickets", "path": rel}, caller=None)
        trec = trow.get("value") or {}
        if trec and trec.get("status") != "closed":
            open_ids.append(trec.get("id") or segs[3])
    guard = _pure.guard_archive({
        "rec": row.get("value"), "open_tickets": open_ids,
        "tpl": _msg_tpl(ctx)})
    if guard.get("ok") is False:
        return guard
    now = ctx.api.call("clock.now", {}, caller=None)
    rec = ctx.api.call("projects.archive", {"rec": row.get("value"),
        "now": now.get("ts")}, caller=None)
    view = ctx.api.call("projects.view", {"rec": rec}, caller=None)
    view["effects"] = [{"kind": "write", "module": "agent/projects",
                        "path": _record(paths, pid.get("id")), "value": rec}]
    return view


def _route_rename(ctx, payload):
    """改名闭环：定位旧档→查重→造新档→落新档→删旧档→工单引用改挂。分岔全在能力内部。"""
    old = ctx.api.call("store.id", {"value": payload.get("id")}, caller=None).get("id")
    paths = _cfg_paths(ctx)
    row = ctx.api.call("store.read", {"module": "agent/projects",
        "path": _record(paths, old)}, caller=None)
    if row.get("value") is None:
        return ctx.api.call("projects.missing",
            {"id": old, "tpl": _msg_tpl(ctx).get("missing")}, caller=None)
    guard = _pure.guard_writable({"rec": row.get("value"), "tpl": _msg_tpl(ctx)})
    if guard.get("ok") is False:
        return guard
    new_id = ctx.api.call("store.id", {"value": payload.get("name")}, caller=None).get("id")
    if new_id != old:
        ex = ctx.api.call("store.exists", {"module": "agent/projects",
            "path": _record(paths, new_id)}, caller=None)
        if ex.get("exists"):
            return ctx.api.call("projects.conflict",
                {"id": new_id, "tpl": _msg_tpl(ctx).get("conflict")}, caller=None)
    now = ctx.api.call("clock.now", {}, caller=None)
    rec = ctx.api.call("projects.renamed", {
        "rec": row.get("value"), "id": new_id, "name": payload.get("name"),
        "now": now.get("ts")}, caller=None)
    effects = [{"kind": "write", "module": "agent/projects",
                "path": _record(paths, new_id), "value": rec}]
    if new_id != old:
        effects.append({"kind": "remove", "module": "agent/projects",
                        "path": _record(paths, old)})
        moved = ctx.api.call("tickets.rebind", {"from": old, "to": new_id,
            "now": now.get("ts")}, caller=None)
        effects.extend((moved or {}).get("effects") or [])
    view = ctx.api.call("projects.view", {"rec": rec}, caller=None)
    view["effects"] = effects
    return view


def _as_handler(fn):
    """装配适配：纯函数只收 payload，路由协议仍是 fn(ctx, payload)；paths 缺省注入。"""
    def handler(ctx, payload):
        payload = dict(payload or {})
        if "paths" not in payload:
            payload["paths"] = _cfg_paths(ctx)
        return fn(payload)
    return handler
