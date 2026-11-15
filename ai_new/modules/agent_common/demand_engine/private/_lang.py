"""需求语言：表达式 + 语句 + 解释器。

语言是**数据**（JSON AST），不是代码。这是需求层的语法，`demand_engine` 负责跑它。

表达式：
    {"get": "event.data.layer"}                 从作用域取值（点号路径）
    {"lit": 任意 JSON}                          字面量
    {"op": "==" | "!=" | "in" | "and" | "or" | "not" | "len" | "+" | ">" | "<" | ">=" | "<=",
     "a": 表达式, "b": 表达式}                   运算（not/len 只用 a）
    裸字符串 / 数字 / 布尔 / 列表 / 普通字典       字面量

语句：
    {"call": "module.fn", "with": {"k": 表达式}, "as": "变量"}   调服务，结果可留作变量
    {"when": 表达式, "then": [语句], "else": [语句]}              守卫
    {"let": "name", "eq": 表达式}                                绑定局部变量
    {"each": 表达式, "as": "x", "do": [语句]}                     遍历
    {"until": 表达式, "do": [语句], "max": 次数}                  循环到表达式为真（默认 200 次上限）
    {"wait": 表达式}                                             等待若干秒（走 clock.sleep）
    {"fail": {"code": 表达式, "message": 表达式, "status": 表达式}} 显式失败（转成 ApiError）

解释器对失败零容忍但不外溢：任何一条语句出错只记结果，不影响触发它的模块。
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
    a = eval_expr(expr.get("a"), scope, depth + 1)
    b = eval_expr(expr.get("b"), scope, depth + 1)
    if op == "==":
        return a == b
    if op == "!=":
        return a != b
    if op == "in":
        try:
            return a in b
        except TypeError:
            return False
    if op == "and":
        return bool(a) and bool(b)
    if op == "or":
        return bool(a) or bool(b)
    if op == "not":
        return not a
    if op == "len":
        try:
            return len(a)
        except TypeError:
            return 0
    if op == "+":
        return a + b
    if op == ">":
        return a > b
    if op == "<":
        return a < b
    if op == ">=":
        return a >= b
    if op == "<=":
        return a <= b
    if op == "append":
        return list(a or []) + [b]
    raise ValueError("未知运算符: %r" % (op,))


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
        for value in node.values():
            found.extend(routes_of(value))
    elif isinstance(node, list):
        for value in node:
            found.extend(routes_of(value))
    return found


def run(stmts, scope, api, ctx, demand_id="", results=None):
    """跑一段语句树，返回每条服务调用的结果（不抛异常）。"""
    results = [] if results is None else results
    for stmt in stmts or []:
        try:
            _run_one(stmt, scope, api, ctx, demand_id, results)
        except Exception as exc:  # noqa: BLE001 —— 需求出错不许外溢
            results.append({"demand": demand_id, "ok": False,
                            "error": "%s: %s" % (type(exc).__name__, exc)})
    return results


def _run_one(stmt, scope, api, ctx, demand_id, results):
    if not isinstance(stmt, dict):
        raise ValueError("语句必须是对象: %r" % (stmt,))

    if "call" in stmt:
        route = stmt["call"]
        payload = dict(scope.get("event") or {})
        for key, expr in (stmt.get("with") or {}).items():
            payload[key] = eval_expr(expr, scope)
        result = api.call(route, payload, caller=scope.get("caller"))
        if stmt.get("as"):
            scope[stmt["as"]] = result
        results.append({"demand": demand_id, "call": route, "ok": True, "result": result})
        return

    if "when" in stmt:
        branch = stmt.get("then") if eval_expr(stmt["when"], scope) else stmt.get("else")
        run(branch, scope, api, ctx, demand_id, results)
        return

    if "let" in stmt:
        scope[stmt["let"]] = eval_expr(stmt.get("eq"), scope)
        return

    if "until" in stmt:
        limit = int(stmt.get("max") or 200)
        for _ in range(limit):
            if eval_expr(stmt.get("until"), scope):
                return
            run(stmt.get("do"), scope, api, ctx, demand_id, results)
        raise ValueError("循环超过上限 %d" % limit)

    if "wait" in stmt:
        seconds = float(eval_expr(stmt.get("wait"), scope) or 0)
        api.call("clock.sleep", {"seconds": seconds}, caller=scope.get("caller"))
        return

    if "fail" in stmt:
        spec = stmt.get("fail") or {}
        code = eval_expr(spec.get("code"), scope)
        message = eval_expr(spec.get("message"), scope)
        status = int(eval_expr(spec.get("status"), scope) or 400)
        raise ctx.ApiError(str(message or code or "需求失败"), code=str(code or "failed"),
                           status=status)

    if "each" in stmt:
        items = eval_expr(stmt.get("each"), scope)
        for item in items or []:
            scope[stmt.get("as") or "item"] = item
            run(stmt.get("do"), scope, api, ctx, demand_id, results)
        return

    raise ValueError("未知语句: %s" % sorted(stmt.keys()))
