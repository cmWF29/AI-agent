"""需求语言：表达式 + 语句 + 解释器。

语言是**数据**（JSON AST），不是代码。这是需求层的语法，`demand_engine` 负责跑它。

**需求树只允许顺序执行**：`call`（顺序调用）。
分支、遍历、循环、等待一律下沉到模块功能函数内部——需求层不再有控制流语法。

表达式：
    {"get": "event.data.layer"}                 从作用域取值（点号路径）
    {"lit": 任意 JSON}                          字面量
    {"op": "+" | "append", "a": 表达式, "b": 表达式}
                                                仅保留薄数据装配：+ 拼路径/文本，append 拼列表
    裸字符串 / 数字 / 布尔 / 列表 / 普通字典       字面量

比较、逻辑、集合、度量运算符不在本语言内：判断与兜底一律下沉模块纯函数。

语句：
    {"call": "module.fn", "with": {"k": 表达式}, "as": "变量"}   调服务，结果可留作变量

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
    if op == "+":
        return a + b
    if op == "append":
        return list(a or []) + [b]
    # 比较（== != > < >= <=）、逻辑（and or not）、集合（in）、度量（len）都是业务判断，
    # 必须下沉到模块纯函数内用 Python 完成；需求层不保留这些运算符，避免编排树变成一门小语言。
    raise ValueError("需求层不支持运算符 %r：判断/兜底/度量请下沉模块纯函数" % (op,))


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

    raise ValueError("未知语句: %s" % sorted(stmt.keys()))
