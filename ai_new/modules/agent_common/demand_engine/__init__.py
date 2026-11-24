"""需求引擎：业务是结构化的语言，引擎负责让它跑起来。

- **模块**（别处）只提供能力：服务 + 扩展点。
- **需求** 是 `data/demands/*.json`：一段可插拔的业务，用结构化语句写（on / when / do），
  语法见 `private/_lang.py`。

引擎只做装载、路由、解释执行，不认识任何业务名词。需求里所有服务调用都写在语句树的
`call` 字段中，所以既能跑，又能被静态扫描读全 —— 业务不再是运行时的浆糊。
"""
from __future__ import annotations

from .private import _engine


async def _route_run(ctx, payload):
    return await ctx.demand_engine.arun_callable(
        payload.get("id"), payload.get("input") or {})


async def _route_batch(ctx, payload):
    """一次往返跑多条需求：控制台每翻一页要好几份数据，跨公网每条一个 RTT 就是几秒。

    calls 是同层可并行的 [{id, input}]；同一层的依赖关系由调用方（前端）算好，
    这里只负责并发跑、按序回。任一条失败只把那条标错，不拖垮同批其它数据。
    """
    import asyncio

    calls = payload.get("calls") or []
    if not isinstance(calls, list):
        raise ctx.ApiError("calls 必须是列表", code="bad_calls", status=400)

    async def one(call):
        try:
            out = await ctx.demand_engine.arun_callable(
                (call or {}).get("id"), (call or {}).get("input") or {})
            return {"ok": True, "result": out}
        except Exception as exc:  # noqa: BLE001 — 单条失败单独回报
            return {"ok": False, "error": str(exc), "code": getattr(exc, "code", "") or "demand_fail"}

    items = await asyncio.gather(*[one(c) for c in calls])
    return {"items": list(items)}


import re

_REF = re.compile(r"\{([^{}]+)\}")


def _dig(obj, path):
    cur = obj
    for part in str(path or "").split("."):
        if not part:
            continue
        if isinstance(cur, dict):
            if part not in cur:
                return None
            cur = cur[part]
        elif isinstance(cur, list):
            try:
                cur = cur[int(part)]
            except (ValueError, IndexError):
                return None
        else:
            return None
    return cur


def _value(expr, route, data, cache):
    """一条取值表达式的实际值：只认 route / data / cache 三种来源。"""
    expr = expr.strip()
    if expr.startswith("route."):
        return route.get(expr[6:])
    if expr.startswith("data."):
        rest = expr[5:]
        head = rest.split(".")[0]
        return _dig(data.get(head), rest[len(head) + 1:])
    if expr.startswith("cache."):
        rest = expr[6:]
        head = rest.split(".")[0]
        return _dig(cache.get(head), rest[len(head) + 1:])
    head = expr.split(".")[0]
    if head in data:
        return _dig(data.get(head), expr[len(head) + 1:])
    if head in cache:
        return _dig(cache.get(head), expr[len(head) + 1:])
    return None


def _fill(tpl, route, data, cache):
    """把规格里的参数模板填成实际值（与前端 spec.fill 同一套语义）。"""
    if isinstance(tpl, str):
        if "{" in tpl:
            def one(m):
                v = _value(m.group(1).split("|")[0], route, data, cache)
                return "" if v is None else str(v)
            return _REF.sub(one, tpl)
        if re.match(r"^[A-Za-z_$][\w$]*(\.[\w$]+)+$", tpl):
            v = _value(tpl, route, data, cache)
            return "" if v is None else v
        return tpl
    if isinstance(tpl, list):
        return [_fill(x, route, data, cache) for x in tpl]
    if isinstance(tpl, dict):
        return {k: _fill(v, route, data, cache) for k, v in tpl.items()}
    return tpl


def _refs(tpl):
    """规格里引用到的数据源名：只有 data./cache. 才是"要等别的数据源"，route/row 上手就有。"""
    acc = set()
    if isinstance(tpl, str):
        if "{" not in tpl and re.match(r"^[A-Za-z_$][\w$]*(\.[\w$]+)+$", tpl) \
                and tpl.startswith(("data.", "cache.")):
            acc.add(tpl.split(".")[1])     # 不带花括号的裸路径同样是依赖
        for m in _REF.findall(tpl):
            p = m.split("|")[0].strip()
            if p.startswith("data.") or p.startswith("cache."):
                parts = p.split(".")
                if len(parts) > 1 and parts[1]:
                    acc.add(parts[1])
    elif isinstance(tpl, list):
        for x in tpl:
            acc |= _refs(x)
    elif isinstance(tpl, dict):
        for x in tpl.values():
            acc |= _refs(x)
    return acc


def _unwrap(val):
    """需求返回外面套了一层 {ok, demand, result, calls}，页面只认里面的 result。"""
    if isinstance(val, dict) and "result" in val and "demand" in val:
        out = val.get("result")
        if isinstance(out, dict) and "result" in out and "ok" in out:
            return out.get("result")   # 需求内部又调了一条，多套一层
        return out
    return val


async def _route_views_index(ctx, payload):
    return ctx.demand_engine.view_index()


async def _route_view_spec(ctx, payload):
    return ctx.demand_engine.view_spec(payload.get("key"))


async def _route_resolve(ctx, payload):
    """整页取数：前端只报"看哪一页、什么参数"，依赖与并发都由视图规格自己决定。

    一页要五份数据时，让浏览器算依赖就是把业务上下游搬到前端；这里按规格 data 声明的
    data./cache. 引用分层，同层 asyncio.gather，一次往返回整页。
    """
    import asyncio

    view_key = str(payload.get("view") or "")
    params = payload.get("params") or {}
    want_shell = bool(payload.get("shell"))
    only = {str(x) for x in (payload.get("only") or []) if x}   # 只补其中几份（局部刷新用）
    if not isinstance(params, dict):
        raise ctx.ApiError("params 必须是对象", code="bad_params", status=400)

    # 首屏只取“视图目录 + 当前页规格”，不再把全部页面的 sections 一次搬过来。
    views, shell = await asyncio.gather(
        ctx.demand_engine.arun_callable("views-index", {}),
        ctx.demand_engine.arun_callable("console-shell", {}) if want_shell else _noop())
    views, shell = _unwrap(views), _unwrap(shell)
    views = views if isinstance(views, list) else (views.get("items") if isinstance(views, dict) else []) or []

    specs, order = {}, []
    for it in views or []:
        v = (it or {}).get("view") or {}
        k = v.get("key")
        if k:
            specs[k] = v
            order.append(k)
    if not view_key:
        view_key = next((k for k in order if specs[k].get("default")), order[0] if order else "")
    spec = None
    requested, fell_back = view_key, False
    if view_key not in specs:
        # 链接里带了不认识的视图（旧书签、写错的参数）：退回默认页，并在同一次往返里
        # 把目录与外壳一起给前端，不留"报错 → 再补两次请求"的路径。
        view_key = next((k for k in order if specs[k].get("default")), order[0] if order else "")
        requested, fell_back = requested, True
        if view_key not in specs:
            raise ctx.ApiError("视图不存在：" + (requested or "（空）"), code="no_view", status=404)

    # 当前页完整规格单独取：首屏渲染要它，索引只负责解析 URL 与菜单。
    full = _unwrap(await ctx.demand_engine.arun_callable("view-spec", {"key": view_key}))
    spec = full if isinstance(full, dict) else {}

    route = dict(params)
    out = {"view": view_key, "spec": spec, "data": {}, "cache": {},
           "missing": [k for k in (spec.get("require") or []) if not route.get(k)]}
    if fell_back:
        out["fallback_from"] = requested
    if want_shell:
        out["views"] = list(views or [])
        out["shell"] = shell or {}
    if out["missing"]:
        return out   # 缺必填参数：没有对象的页面不发请求，直接空态

    data, cache = {}, {}
    sources = list(spec.get("data") or [])
    if only:
        sources = [s for s in sources if str(s.get("as")) in only]
    done, pending = set(), sources

    async def one(src):
        try:
            return True, _unwrap(await ctx.demand_engine.arun_callable(str(src.get("demand") or ""), args_of(src)))
        except Exception as exc:  # noqa: BLE001 — 单条失败要指名到源
            return False, str(exc) or repr(exc)

    def args_of(src):
        return _fill(src.get("params") or {}, route, data, cache)

    while pending:
        ready, wait = [], []
        for src in pending:
            (ready if _refs(src.get("params") or {}) <= done else wait).append(src)
        if not ready:
            ready = [wait.pop(0)]   # 环或引用未声明：按声明顺序先跑一个，避免死等
        results = await asyncio.gather(*[one(s) for s in ready])
        for src, (ok, val) in zip(ready, results):
            name = str(src.get("as") or src.get("demand") or "")
            if not ok:
                raise ctx.ApiError("%s：%s" % (name, val), code="data_fail", status=502)
            data[name] = val or {}
            if src.get("cache"):
                cache[str(src["cache"])] = val or {}
                done.add(str(src["cache"]))
        for src in ready:
            done.add(str(src.get("as") or src.get("demand") or ""))
        pending = wait

    out.update({"data": data, "cache": cache})
    return out


def _all_docs(raw):
    """把生成器按模块分组的索引摊平成文件行；路径树自己再按目录重组。"""
    out = []
    for group in (raw.get("groups") or []):
        if not isinstance(group, dict):
            continue
        for doc in (group.get("docs") or []):
            if isinstance(doc, dict) and doc.get("source"):
                out.append(doc)
    return out


def _path_nodes(raw, prefix=""):
    """按源文件真实路径切目录树：目录节点带 group=路径前缀，文件节点带源码+镜像文档。

    只发当前一层的节点；用户展开目录时再用前缀拉下一层，避免 508 份文件一次性进 DOM。
    """
    rows = _all_docs(raw)
    if prefix:
        rows = [d for d in rows if str(d.get("source") or "").startswith(prefix + "/")]
    dirs, files = {}, []
    for doc in rows:
        src = str(doc.get("source") or "")
        rest = src[len(prefix) + 1:] if prefix else src
        if "/" in rest:
            dirs.setdefault(rest.split("/", 1)[0], []).append(doc)
        else:
            files.append(doc)
    nodes = []
    for seg in sorted(dirs, key=lambda x: (x.lower(), x)):
        child = (prefix + "/" + seg) if prefix else seg
        nodes.append({"label": seg, "group": child, "badge": "%d" % len(dirs[seg]),
                      "count": len(dirs[seg]), "children": []})
    for doc in sorted(files, key=lambda d: str(d.get("source") or "").lower()):
        src = str(doc.get("source") or "")
        doc_path = str(doc.get("doc") or "")
        nodes.append({
            "name": src.rsplit("/", 1)[-1],
            "source": src,
            "doc": doc_path,
            "kind": doc.get("kind") or "file",
            "symbols": int(doc.get("symbols") or 0),
            "hash": str(doc.get("hash") or ""),
            "path": "源码 %s · 文档 %s" % (src, doc_path),
        })
    return nodes


def _find_doc(raw, path):
    for doc in _all_docs(raw):
        if path in (str(doc.get("source") or ""), str(doc.get("doc") or "")):
            return doc
    return None


async def _route_code_docs(ctx, payload):
    """源码 ↔ docs/code 映射：首屏给第一层目录，展开时按路径前缀取下一层。

    不是按模块拍脑袋分组：目录节点来自源文件真实路径，点开哪层只取哪层。
    """
    raw = ctx.storage.own(__file__).yaml_read("code-docs.json", {}) or {}
    want = str((payload or {}).get("group") or "")
    if want:
        rows = _path_nodes(raw, want)
        return {"label": want, "count": len(rows), "children": rows}
    groups = _path_nodes(raw, "")
    return {"total": int(raw.get("total") or 0), "generated": raw.get("generated") or "",
            "groups": groups}


async def _route_code_docs_read(ctx, payload):
    """按索引里的精确路径读源码与镜像文档；只认索引登记过的路径，不接受任意文件。"""
    raw = ctx.storage.own(__file__).yaml_read("code-docs.json", {}) or {}
    path = str((payload or {}).get("path") or "")
    doc = _find_doc(raw, path)
    if doc is None:
        return {"ok": False, "path": path, "error": "路径不在源码文档索引里"}
    src_rel, doc_rel = str(doc.get("source") or ""), str(doc.get("doc") or "")
    return {
        "ok": True, "path": path, "title": src_rel.rsplit("/", 1)[-1],
        "source": src_rel, "doc": doc_rel,
        "kind": doc.get("kind") or "file",
        "symbols": int(doc.get("symbols") or 0),
        "hash": str(doc.get("hash") or ""),
        "source_text": ctx.storage.repo_text(src_rel),
        "doc_text": ctx.storage.repo_text(doc_rel),
    }


async def _route_click_machine(ctx, payload):
    """点击状态机规格：前端按它做门禁，架构页按它显示，测试按它做全覆盖。"""
    shell = ctx.demand_engine.console() or {}
    spec = dict(shell.get("click_machine") or {})
    # 边数是迁移表自己算出来的，不手工维护：加一条迁移，展示页的数字自动跟着变
    spec["edges"] = sum(len(v or []) for v in (spec.get("transitions") or {}).values())
    return {"click_machine": spec, "screen_machine": ctx.demand_engine.screens(),
            "inventory": ctx.demand_engine.inventory()}


async def _noop():
    return None


def setup(ctx):
    """装配入口：装填 ctx.demand_engine（需求装载 + 解释执行）。"""
    ctx.demand_engine = _engine.Engine(ctx)
    ctx.api.register("demand_engine.run", _route_run, "按名跑一段编排需求", module="demand_engine")
    ctx.api.register("demand_engine.batch", _route_batch, "同层多条需求一次往返", module="demand_engine")
    ctx.api.register("demand_engine.resolve", _route_resolve,
                     "整页取数：按视图规格的依赖分层并发跑完，一次往返回整页", module="demand_engine")
    ctx.api.register("demand_engine.views_index", _route_views_index,
                     "视图目录：只给 key/params/default/nav/menu，不带整页 sections", module="demand_engine")
    ctx.api.register("demand_engine.view_spec", _route_view_spec,
                     "当前视图完整规格：按 key 只回一页", module="demand_engine")
    ctx.api.register("demand_engine.list", lambda c, p: ctx.demand_engine.items(),
                     "当前需求（on/do/enabled）", module="demand_engine")
    ctx.api.register("demand_engine.manifest", lambda c, p: ctx.demand_engine.manifest(),
                     "全量需求的可视化形状（执行链 + 树节点）", module="demand_engine")
    ctx.api.register("demand_engine.console", lambda c, p: ctx.demand_engine.console(),
                     "控制台外壳（品牌、词表、配色、导航菜单）", module="demand_engine")
    ctx.api.register("demand_engine.code_docs_read", _route_code_docs_read,
                     "按索引路径读源码与 docs/code 镜像", module="demand_engine")
    ctx.api.register("demand_engine.code_docs", _route_code_docs,
                     "源码与 docs/code 镜像文档的映射索引（按模块分组）", module="demand_engine")
    ctx.api.register("demand_engine.click_machine", _route_click_machine,
                     "点击状态机规格（状态/迁移/每种可点控件的门禁）", module="demand_engine")
    ctx.api.register("demand_engine.chrome", lambda c, p: ctx.demand_engine.chrome(),
                     "登录页外壳（只回品牌与登录文案，未登录可读）", module="demand_engine")
    return ctx.demand_engine


def dispatch(ctx, hook, envelope):
    """把一次 hook 触发交给需求引擎。"""
    return ctx.demand_engine.dispatch(hook, envelope)
