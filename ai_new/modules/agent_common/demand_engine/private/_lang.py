"""需求语言：表达式 + 语句 + 解释器。

语言是**数据**（JSON AST），不是代码。这是需求层的语法，`demand_engine` 负责跑它。

**需求树只允许顺序执行**：`call`（顺序调用）。
分支、遍历、循环、等待一律下沉到模块功能函数内部——需求层不再有控制流语法。

表达式：
    {"get": "event.data.layer"}                 从作用域取值（点号路径）
    {"lit": 任意 JSON}                          字面量
    裸字符串 / 数字 / 布尔 / 列表 / 普通字典       字面量

比较、逻辑、集合、度量、字符串/列表拼装运算符不在本语言内：路径、命名、
文本与列表装配一律下沉模块纯函数，需求层不再做任何拼接。

语句：
    {"call": "module.fn", "with": {"k": 表达式}, "as": "变量"}   调服务，结果可留作变量
    {"send": "module.fn", "with": {"k": 表达式}}                单向通知，不取结果
                                                              （内存通道只认这一种）

解释器对外不溢出，对内分两类失败：语句标了 required 的（守卫/路径/权限）
失败即停，后面的写步骤不得继续；未标 required 的失败只记录，允许编排走
既定的兜底/收尾路径（例如 react 无回复仍要 finish 落盘）。
"""
from __future__ import annotations

_MAX_DEPTH = 12


def is_expr(value):
    return isinstance(value, dict) and bool({"get", "lit", "op"} & set(value.keys()))


def eval_expr(expr, scope, depth=0):
    if depth > _MAX_DEPTH:
        raise ValueError("表达式嵌套过深")
    if isinstance(expr, list):
        return [eval_expr(item, scope, depth + 1) for item in expr]
    if isinstance(expr, dict) and not is_expr(expr):
        return {key: eval_expr(value, scope, depth + 1) for key, value in expr.items()}
    if not is_expr(expr):
        return expr
    if "lit" in expr:
        return expr["lit"]
    if "get" in expr:
        return _get(scope, str(expr["get"]))
    op = expr.get("op")
    eval_expr(expr.get("a"), scope, depth + 1)
    eval_expr(expr.get("b"), scope, depth + 1)
    # 比较（== != > < >= <=）、逻辑（and or not）、集合（in）、度量（len）、
    # 字符串/列表拼装（+ append）都是业务装配，必须下沉到模块纯函数内用 Python 完成；
    # 需求层不保留这些运算符，避免编排树变成一门小语言。
    raise ValueError("需求层不支持运算符 %r：判断/兜底/度量/拼装请下沉模块纯函数" % (op,))


def _get(scope, path):
    value = scope
    for part in path.split("."):
        if isinstance(value, dict):
            value = value.get(part)
        elif isinstance(value, (list, tuple)):
            try:
                value = value[int(part)]
            except (ValueError, IndexError):
                return None
        else:
            return None
    return value


def routes_of(node):
    """语句树里所有的服务调用（给静态分析和可见性用）。"""
    found = []
    if isinstance(node, dict):
        if isinstance(node.get("call"), str):
            found.append(node["call"])
        if isinstance(node.get("send"), str):
            found.append(node["send"])
        for value in node.values():
            found.extend(routes_of(value))
    elif isinstance(node, list):
        for value in node:
            found.extend(routes_of(value))
    return found


def run(stmts, scope, api, ctx, demand_id="", results=None):
    """同步轨：顺序跑语句树，首个失败立即终止，失败原因留在结果里。"""
    results = [] if results is None else results
    failed = False
    for stmt in stmts or []:
        route = stmt.get("call") if isinstance(stmt, dict) else None
        required = bool(stmt.get("required")) if isinstance(stmt, dict) else False
        # runtime.apply 是需求唯一的落盘口：失败能力可以携带审计/补偿 effects，
        # 必须让它落盘后再收口；其余语句首错即停。
        if failed and route != "runtime.apply":
            break
        try:
            ok = _run_one(stmt, scope, api, ctx, demand_id, results)
        except Exception as exc:  # noqa: BLE001 —— 需求出错不许外溢
            results.append({"demand": demand_id, "ok": False,
                            "call": route,
                            "error": "%s: %s" % (type(exc).__name__, exc)})
            # 语法/执行异常是编排自身坏了，必须停；业务 ok:false 才看 required。
            failed = True
            continue
        if not ok and required:
            failed = True
    return results


async def arun(stmts, scope, api, ctx, demand_id="", results=None):
    """异步轨：顺序 await 语句服务调用，首个失败立即终止。"""
    results = [] if results is None else results
    failed = False
    for stmt in stmts or []:
        route = stmt.get("call") if isinstance(stmt, dict) else None
        required = bool(stmt.get("required")) if isinstance(stmt, dict) else False
        if failed and route != "runtime.apply":
            break
        try:
            ok = await _arun_one(stmt, scope, api, ctx, demand_id, results)
        except Exception as exc:  # noqa: BLE001 —— 需求出错不许外溢
            results.append({"demand": demand_id, "ok": False,
                            "call": route,
                            "error": "%s: %s" % (type(exc).__name__, exc)})
            # 语法/执行异常是编排自身坏了，必须停；业务 ok:false 才看 required。
            failed = True
            continue
        if not ok and required:
            failed = True
    return results


def _mark(results, demand_id, route, result, send=False):
    """记录一条调用：业务失败（ok:false）必须被识别，后续顺序语句随即终止。"""
    ok = not (isinstance(result, dict) and result.get("ok") is False)
    row = {"demand": demand_id, "call": route, "ok": ok, "result": result}
    if send:
        row["send"] = True
    if not ok:
        row["code"] = str(result.get("code") or "")
        row["error"] = str(result.get("error") or "")
        row["status"] = result.get("status")
    results.append(row)
    return ok


def _run_one(stmt, scope, api, ctx, demand_id, results):
    if not isinstance(stmt, dict):
        raise ValueError("语句必须是对象: %r" % (stmt,))

    if "call" in stmt:
        route = stmt["call"]
        payload = dict(scope.get("event") or {})
        for key, expr in (stmt.get("with") or {}).items():
            payload[key] = eval_expr(expr, scope)
        if route == "demand_engine.run":
            # 嵌套需求在同步轨内递归跑完，不回投事件循环占线等待。
            result = ctx.demand_engine.run_callable(
                payload.get("id"), payload.get("input") or {})
        else:
            result = api.call(route, payload, caller=scope.get("caller"))
        if stmt.get("as"):
            scope[stmt["as"]] = result
        return _mark(results, demand_id, route, result)

    if "send" in stmt:
        route = stmt["send"]
        payload = dict(scope.get("event") or {})
        for key, expr in (stmt.get("with") or {}).items():
            payload[key] = eval_expr(expr, scope)
        result = api.notify(route, payload, caller=scope.get("caller"))
        return _mark(results, demand_id, route, result, send=True)

    raise ValueError("未知语句: %s" % sorted(stmt.keys()))


async def _arun_one(stmt, scope, api, ctx, demand_id, results):
    if not isinstance(stmt, dict):
        raise ValueError("语句必须是对象: %r" % (stmt,))

    if "call" in stmt:
        route = stmt["call"]
        payload = dict(scope.get("event") or {})
        for key, expr in (stmt.get("with") or {}).items():
            payload[key] = eval_expr(expr, scope)
        if route == "demand_engine.run":
            result = await ctx.demand_engine.arun_callable(
                payload.get("id"), payload.get("input") or {})
        else:
            result = await api.acall(route, payload, caller=scope.get("caller"))
        if stmt.get("as"):
            scope[stmt["as"]] = result
        return _mark(results, demand_id, route, result)

    if "send" in stmt:
        route = stmt["send"]
        payload = dict(scope.get("event") or {})
        for key, expr in (stmt.get("with") or {}).items():
            payload[key] = eval_expr(expr, scope)
        result = api.notify(route, payload, caller=scope.get("caller"))
        return _mark(results, demand_id, route, result, send=True)

    raise ValueError("未知语句: %s" % sorted(stmt.keys()))
