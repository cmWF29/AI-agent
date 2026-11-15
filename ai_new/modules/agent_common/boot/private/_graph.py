"""装配图扫描（组合根的私有实现）。

零声明：这张图完全从代码里读出来，不依赖任何模块级标签。

各条关系分别从哪里来：

- **谁提供 ctx.X**      ← setup 可达代码里的赋值 `ctx.X = ...`
- **谁依赖谁**          ← setup 可达代码里读到的 `ctx.X` + `ctx.api.call("模块.fn")`
- **组合根是谁**        ← 没有 `setup` 的模块（恰好一个）
- **启动阶段**          ← `__init__.py` 里导出 `start(ctx)` 的模块，组合根在全部 setup 后调用

为什么只算 setup 阶段：装配顺序只由 setup 期间真正执行的代码决定。运行期调用
（例如 ctx.api.call("knowledge.compose")）必然发生在所有模块装配完之后，把它当成
依赖边只会制造假环。

扫描器只跟模块内部显式调用（`_file.fn` / `_fn`），不跟嵌套函数、类体和 λ ——
它们不在 setup 期执行。动态拼出来的路由名也不会被识别，所以 `api.call` 的实参
请写字面量。
"""
from __future__ import annotations

import ast
import heapq
import json
from collections import defaultdict
from pathlib import Path

# Context 自己就带的属性，不算任何模块的提供物，也不许被模块改写
BASELINE = frozenset({"root", "loaded"})

# 嵌套函数/类/λ 的体在 setup 期不执行，扫描时整段跳过
_SKIP = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)


def plan(module_dirs, data_dir=None):
    """扫描并返回装配计划。

    `module_dirs` 是一个或多个**模块组**目录（`modules/agent_common`、`modules/agent` …）：
    组只是目录，不是层级特权 —— 同一个扫描器、同一套规则，换一组目录就换一套装配。

    返回 dict：
        roots       组合根模块（没有 setup 的那个，不参与装配）
        order       装配顺序（不含组合根）
        edges       {模块: [它依赖的模块]}（= 必须比它先装配）
        reasons     {"a -> b": ["ctx.api", "api.call(x.y)"]}
        providers   {ctx 属性: 赋值它的模块}
        packages    {模块: 真实包路径}（组合根按它动态加载，不猜路径）
        warnings    未知 ctx 面 / 未知路由 / 改写 Context 自带属性 / 需求接线问题
        stash       模块私有的 ctx 状态（如 ctx._session_sem）
        cycle       如果成环，环路径；否则 None
        hooks       静态 hook 图：声明 / 触发 / 需求接线，见 _hook_graph()
        stats       每个模块 setup 可达面（读写/路由/私有状态）
    """
    bases = [Path(module_dirs)] if isinstance(module_dirs, (str, Path)) else [Path(p) for p in module_dirs]
    for base in bases:
        if not base.is_dir():
            raise RuntimeError("模块组目录不存在: %s" % base)

    funcs_by_module = {}
    packages = {}
    for base in bases:
        for entry in sorted(base.iterdir()):
            if entry.is_dir() and not entry.name.startswith("_") and (entry / "__init__.py").is_file():
                funcs_by_module[entry.name] = (_load_module(entry), entry)
                packages[entry.name] = "ai_new.modules.%s.%s" % (base.name, entry.name)
    if not funcs_by_module:
        raise RuntimeError("模块组里没有发现任何模块: %s" % ", ".join(str(b) for b in bases))

    roots = sorted(name for name, (funcs, _) in funcs_by_module.items()
                   if ("__init__", "setup") not in funcs)
    if len(roots) > 1:
        raise RuntimeError("只能有一个组合根（没有 setup 的模块），发现: %s" % roots)
    meta = {name: {"funcs": funcs, "dir": path}
            for name, (funcs, path) in funcs_by_module.items() if name not in roots}

    # 第一遍：每模块在 setup 期读什么、写什么、注册什么
    for name, item in meta.items():
        reach = _reachable(item["funcs"])
        surface = _surface(item["funcs"], reach)
        item["reach"] = reach
        item.update(surface)

    # 提供关系：谁在 setup 期写了 ctx.X，谁就是 X 的提供方
    providers = {}
    warnings = []
    for name, item in meta.items():
        for attr in sorted(item["writes"]):
            if attr in BASELINE:
                warnings.append("%s 在 setup 里改写了 Context 自带的 ctx.%s" % (name, attr))
                continue
            if attr in providers:
                raise RuntimeError("ctx.%s 被两个模块同时装填: %s / %s"
                                   % (attr, providers[attr], name))
            providers[attr] = name

    edges = {name: set() for name in meta}
    reasons = defaultdict(list)
    stash = []

    for name, item in meta.items():
        for attr in sorted(item["reads"]):
            if attr in BASELINE:
                continue
            owner = providers.get(attr)
            if owner is None:
                if not attr.startswith("_"):
                    warnings.append("%s 在 setup 里读了 ctx.%s，但没有模块装填它" % (name, attr))
                continue
            if owner != name:
                edges[name].add(owner)
                reasons["%s -> %s" % (name, owner)].append("ctx." + attr)

        for route in sorted(item["routes"]):
            owner = route.split(".")[0]
            if owner == name:
                continue
            if owner in meta:
                edges[name].add(owner)
                reasons["%s -> %s" % (name, owner)].append("api.call(%s)" % route)
            else:
                warnings.append("%s 在 setup 里调用了没有对应模块的路由 %s" % (name, route))

        for attr in sorted(item["stash"]):
            stash.append("%s 把私有状态挂在 ctx.%s" % (name, attr))

        item["stats"] = {"setup_reach": len(item["reach"]),
                         "reads": sorted(item["reads"]), "writes": sorted(item["writes"]),
                         "routes": sorted(item["routes"])}

    order, leftover = _toposort(meta, edges)
    cycle = _find_cycle(edges, leftover) if leftover else None

    hooks, hook_warnings = _hook_graph(funcs_by_module, roots, data_dir)
    warnings.extend(hook_warnings)

    return {
        "roots": roots,
        "order": order,
        "edges": {name: sorted(deps) for name, deps in edges.items()},
        "reasons": dict(reasons),
        "providers": providers,
        "warnings": warnings,
        "stash": stash,
        "cycle": cycle,
        "hooks": hooks,
        "packages": dict(sorted(packages.items())),
        "stats": {name: item["stats"] for name, item in meta.items()},
    }


def _hook_graph(funcs_by_module, roots, data_dir):
    """静态需求图：模块声明了哪个点、谁触发、需求把它接到了哪些服务。

    这是"业务结构化"的落点：不看运行日志，直接从源码 + `data/demands/*.json`
    得出 "模块 → hook 点 → 需求 → 服务" 的接线并对账。

    对账口径（全部是硬错误，装配前就能发现）：
    - 触发的点必须已声明；声明者必须是名字前缀那个模块；
    - 需求的 on 必须是已声明的点，do 的每条服务必须在目标模块真的注册过；
    - 触发过的点必须有需求订阅（没有需求，就不该留这个点）；
    - 声明过的点必须有需求使用（否则连同 emit 一起删）。
    """
    declared = {}
    emitted = {}
    for module, (funcs, _) in funcs_by_module.items():
        for node in funcs.values():
            for call in ast.walk(node):
                hit = _hook_call(call)
                if not hit:
                    continue
                kind, name = hit
                if kind == "point":
                    declared.setdefault(name, module)
                else:
                    emitted.setdefault(name, set()).add(module)

    demands = _read_demands(data_dir)

    demand_emits = set()
    for rec in demands:
        _demand_emit_points(rec["do"], demand_emits)
    for name in demand_emits:
        emitted.setdefault(name, set()).add("demand")

    warnings = []
    for name, mods in sorted(emitted.items()):
        if name not in declared:
            warnings.append("模块 %s 触发了未声明的 hook 点: %s"
                            % ("/".join(sorted(mods)), name))
        for module in sorted(mods):
            if module != "demand" and name.split(".")[0] != module:
                warnings.append("%s 触发了别的模块的 hook 点: %s" % (module, name))

    for name in sorted(declared):
        if name in emitted or declared[name] in roots:
            continue
        warnings.append("hook 点声明了但没有任何代码触发: %s" % name)

    texts = {}
    for module, (_, path) in funcs_by_module.items():
        sources = sorted(path.glob("*.py")) + sorted((path / "private").glob("*.py"))
        texts[module] = "\n".join(p.read_text(encoding="utf-8") for p in sources)

    covered = {}
    for rec in demands:
        if not rec.get("enabled", True):
            continue
        if rec.get("callable"):
            if rec.get("on"):
                warnings.append("需求 %s 是 callable，不该再挂 hook 点" % rec["id"])
        elif not rec.get("on"):
            warnings.append("需求 %s 没有声明任何 hook 点" % rec["id"])
        if not rec.get("do"):
            warnings.append("需求 %s 没有声明任何服务调用" % rec["id"])
        routes = []
        for hook in rec.get("on") or []:
            if hook not in declared:
                warnings.append("需求 %s 订阅了未声明的 hook 点: %s" % (rec["id"], hook))
            covered.setdefault(hook, []).append(rec["id"])
        for step in rec.get("do") or []:
            routes.extend(_demand_routes(step))
        for step in rec.get("do") or []:
            warnings.extend(_check_stmt(step, rec["id"]))
        for route in routes:
            if "." not in route:
                warnings.append("需求 %s 的调用不是 '模块.服务' 形式: %r" % (rec["id"], route))
                continue
            owner = route.split(".")[0]
            quoted = {'"%s"' % route, "'%s'" % route}
            if owner not in texts:
                warnings.append("需求 %s 调用了不存在的模块: %s" % (rec["id"], route))
            elif not any(q in texts[owner] for q in quoted):
                warnings.append("需求 %s 调用了 %s 模块没注册过的服务: %s"
                                % (rec["id"], owner, route))

    for name, mods in sorted(emitted.items()):
        if name not in covered:
            warnings.append("hook 点 %s 被 %s 触发，但没有任何需求订阅它"
                            % (name, "/".join(sorted(mods))))

    for name in sorted(declared):
        if name not in covered and declared[name] not in roots:
            warnings.append("hook 点 %s 没有任何需求使用，可以连同 emit 一起删掉" % name)

    detail = {
        "declared": dict(sorted(declared.items())),
        "emitted": {name: sorted(mods) for name, mods in sorted(emitted.items())},
        "demands": demands,
        "warnings": warnings,
    }
    return detail, warnings


def _read_demands(data_dir):
    if not data_dir:
        return []
    base = Path(data_dir) / "demands"
    if not base.is_dir():
        return []
    items = []
    for path in sorted(base.glob("*.json")):
        rec = json.loads(path.read_text(encoding="utf-8"))
        rec.setdefault("id", path.stem)
        rec.setdefault("enabled", True)
        rec.setdefault("do", [])
        items.append({"id": rec["id"], "title": rec.get("title", ""),
                      "enabled": bool(rec.get("enabled", True)),
                      "on": _as_hooks(rec.get("on")), "do": list(rec["do"]),
                      "callable": bool(rec.get("callable"))})
    return items


def _as_hooks(value):
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(v) for v in value]
    return []


def _demand_routes(node):
    """需求语句树里所有的服务调用（需求语言由 demand_engine 解释）。"""
    found = []
    if isinstance(node, dict):
        if isinstance(node.get("call"), str):
            found.append(node["call"])
        for value in node.values():
            found.extend(_demand_routes(value))
    elif isinstance(node, list):
        for value in node:
            found.extend(_demand_routes(value))
    return found


def _demand_emit_points(node, out):
    """需求里经 hooks.emit 触发的点（模块不自己 emit，触发由需求编排）。"""
    if isinstance(node, dict):
        if node.get("call") == "hooks.emit":
            args = node.get("with") or {}
            name = (((args.get("point") or args.get("name")) or {}).get("lit"))
            if isinstance(name, str):
                out.add(name)
        for value in node.values():
            _demand_emit_points(value, out)
    elif isinstance(node, list):
        for value in node:
            _demand_emit_points(value, out)


_STMT_KEYS = ({"call"}, {"when"}, {"let"}, {"each"},
              {"until"}, {"wait"}, {"fail"})


def _check_stmt(stmt, demand_id):
    """需求语言的语法检查：语句必须是 call / when / let / each 之一。"""
    warnings = []
    if not isinstance(stmt, dict):
        return ["需求 %s 里有非对象语句: %r" % (demand_id, stmt)]
    keys = set(stmt.keys())
    if not any(keys & form for form in _STMT_KEYS):
        warnings.append("需求 %s 有未知语句（只支持 call/when/let/each）: %s"
                        % (demand_id, sorted(keys)))
    for key in ("then", "else", "do"):
        for child in stmt.get(key) or []:
            warnings.extend(_check_stmt(child, demand_id))
    return warnings


def _hook_call(call):
    """识别 `ctx.hooks.point("name")` / `ctx.hooks.emit("name", ...)`。"""
    if not isinstance(call, ast.Call):
        return None
    func = call.func
    if not (isinstance(func, ast.Attribute) and func.attr in ("point", "emit")):
        return None
    owner = func.value
    if not (isinstance(owner, ast.Attribute) and owner.attr == "hooks"):
        return None
    if not (isinstance(owner.value, ast.Name) and owner.value.id == "ctx"):
        return None
    if not call.args:
        return None
    arg = call.args[0]
    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
        return (func.attr, arg.value)
    return None


# ---------------------------------------------------------------- 扫描实现

def _load_module(path):
    """聚合模块的公开文件与 private/ 下所有 .py 的函数定义，键是 (文件主名, 函数名)。"""
    funcs = {}
    sources = sorted(path.glob("*.py")) + sorted((path / "private").glob("*.py"))
    for source in sources:
        stem = source.stem
        if stem.startswith("__"):
            stem = "__init__"
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                funcs[(stem, node.name)] = node
    return funcs


def _exec_nodes(node):
    """setup 期会真正执行的节点（不进嵌套 def/class/λ 的体）。"""
    stack = list(ast.iter_child_nodes(node))
    while stack:
        current = stack.pop()
        yield current
        if not isinstance(current, _SKIP):
            stack.extend(ast.iter_child_nodes(current))


def _reachable(funcs):
    """从 __init__.setup 出发，沿模块内部调用（_file.fn / _fn）做可达分析。"""
    seen = set()
    stack = [("__init__", "setup")]
    while stack:
        key = stack.pop()
        if key in seen:
            continue
        node = funcs.get(key)
        if node is None:
            continue
        seen.add(key)
        stem = key[0]
        for child in _exec_nodes(node):
            target = _local_target(child, stem, funcs)
            if target:
                stack.append(target)
    return seen


def _local_target(node, stem, funcs):
    if not isinstance(node, ast.Call):
        return None
    func = node.func
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        if func.value.id == "ctx":
            return None
        key = (func.value.id, func.attr)
        return key if key in funcs else None
    if isinstance(func, ast.Name):
        key = (stem, func.id)
        return key if key in funcs else None
    return None


def _surface(funcs, reach):
    """setup 期摸到的 ctx 面：读了什么、写了什么、调了哪些路由、挂了哪些私有状态。"""
    reads, writes, routes, stash = set(), set(), set(), set()
    for key in reach:
        for node in _exec_nodes(funcs[key]):
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                if node.value.id == "ctx":
                    if node.attr.startswith("_"):
                        stash.add(node.attr)
                    else:
                        reads.add(node.attr)
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                for target in _assign_targets(node):
                    if (isinstance(target, ast.Attribute)
                            and isinstance(target.value, ast.Name)
                            and target.value.id == "ctx"):
                        writes.add(target.attr)
            if isinstance(node, ast.Call):
                route = _api_call_route(node)
                if route:
                    routes.add(route)
    return {"reads": reads - writes, "writes": writes, "routes": routes, "stash": stash}


def _assign_targets(node):
    if isinstance(node, ast.Assign):
        return list(node.targets)
    if isinstance(node, ast.AnnAssign) and node.target is not None:
        return [node.target]
    return []


def _api_call_route(call):
    func = call.func
    if not isinstance(func, ast.Attribute) or func.attr != "call":
        return None
    owner = func.value
    if not (isinstance(owner, ast.Attribute) and owner.attr == "api"):
        return None
    if not (isinstance(owner.value, ast.Name) and owner.value.id == "ctx"):
        return None
    if not call.args:
        return None
    first = call.args[0]
    if isinstance(first, ast.Constant) and isinstance(first.value, str) and "." in first.value:
        return first.value
    return None


# ---------------------------------------------------------------- 排序实现

def _toposort(meta, edges):
    indegree = {name: len(deps) for name, deps in edges.items()}
    dependents = defaultdict(set)
    for name, deps in edges.items():
        for dep in deps:
            dependents[dep].add(name)
    ready = list(indegree)  # 并列时按名字定序，保证可复现
    ready = [name for name in ready if indegree[name] == 0]
    heapq.heapify(ready)
    order = []
    while ready:
        name = heapq.heappop(ready)
        order.append(name)
        for dependent in sorted(dependents[name]):
            indegree[dependent] -= 1
            if indegree[dependent] == 0:
                heapq.heappush(ready, dependent)
    leftover = sorted(name for name in meta if indegree[name] > 0)
    return order, leftover


def _find_cycle(edges, candidates):
    """在成环的节点里找一条具体环路径，用于报错。"""
    white, grey, black = 0, 1, 2
    color = {}
    path = []

    def visit(node):
        color[node] = grey
        path.append(node)
        for dep in sorted(edges.get(node, ())):
            state = color.get(dep, white)
            if state == grey:
                return path[path.index(dep):] + [dep]
            if state == white:
                found = visit(dep)
                if found:
                    return found
        path.pop()
        color[node] = black
        return None

    for start in candidates:
        if color.get(start, white) == white:
            found = visit(start)
            if found:
                return found
    return list(candidates)
