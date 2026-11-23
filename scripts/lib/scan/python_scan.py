"""Python 源码结构化扫描：定义、引用、导入、注册表绑定、路由/工具登记。

被两道门禁（deadcode / docsync）与上层测试金字塔复用；只产出结构化结果，
不做终端打印。引用证据只来自可执行代码与数据清单，不维护人工名单。
"""
from __future__ import annotations

import ast
from pathlib import Path

EXCLUDE_PARTS = {"__pycache__", ".git", "node_modules", "assets"}

ENTRY_FUNCS = {"setup", "start"}
LIFECYCLE = {"setUp", "tearDown", "setUpClass", "tearDownClass",
             "setUpModule", "tearDownModule"}
# http.server.BaseHTTPRequestHandler 按名反射分发的方法
HTTP_VERB_PREFIX = "do_"


def _target_name(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _callee_base(callee):
    """取注册/调用方法的所属对象：ctx.tools.register → tools，ctx.api.register → api。"""
    if isinstance(callee, ast.Attribute) and isinstance(callee.value, ast.Attribute):
        return callee.value.attr
    return None


# 这些调用方法的第一个字符串参是路由名/工具名，纳入字符串路由引用
ROUTE_METHODS = {"call", "acall", "notify", "send"}


def parse_python(path: Path, src: str) -> dict:
    """解析单个 Python 文件，返回定义/引用/导入/绑定等中间结果。"""
    tree = ast.parse(src)
    defs, refs, imports = [], set(), []
    bindings, api_routes, tool_names = [], [], []
    call_routes, getattr_names, strings = [], [], []
    in_test = "/agent_test/" in str(path)

    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            strings.append(node.value)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            refs.add(node.id)
        if isinstance(node, ast.Attribute):
            refs.add(node.attr)
        if isinstance(node, ast.Import):
            for a in node.names:
                imports.append({
                    "alias": a.asname or a.name.split(".")[0],
                    "module": a.name, "name": a.name.split(".")[-1],
                    "lineno": node.lineno, "kind": "import",
                })
        if isinstance(node, ast.ImportFrom):
            for a in node.names:
                imports.append({
                    "alias": a.asname or a.name,
                    "module": node.module or "", "name": a.name,
                    "lineno": node.lineno, "kind": "from",
                })
        if isinstance(node, ast.Call):
            callee = node.func
            method = callee.attr if isinstance(callee, ast.Attribute) else None
            base = _callee_base(callee)
            args = node.args
            if method in ("register", "register_demand"):
                if args and isinstance(args[0], ast.Constant) and isinstance(args[0].value, str):
                    name = args[0].value
                    if base == "tools" or method == "register_demand":
                        tool_names.append(name)
                    else:
                        api_routes.append(name)
                    if method == "register" and len(args) >= 4:
                        tgt = _target_name(args[3])
                        if tgt:
                            bindings.append((name, tgt))
                if method == "register_demand":
                    for kw in node.keywords:
                        if kw.arg == "demand" and isinstance(kw.value, ast.Constant):
                            call_routes.append(str(kw.value.value))
            if method in ROUTE_METHODS:
                if args and isinstance(args[0], ast.Constant) and isinstance(args[0].value, str):
                    call_routes.append(args[0].value)
            if method == "getattr" and len(args) >= 2:
                if isinstance(args[1], ast.Constant) and isinstance(args[1].value, str):
                    getattr_names.append(args[1].value)
        if isinstance(node, ast.Tuple) and len(node.elts) == 2:
            a, b = node.elts
            if isinstance(a, ast.Constant) and isinstance(a.value, str):
                tgt = _target_name(b)
                if tgt:
                    bindings.append((a.value, tgt))

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            defs.append({"name": node.name, "lineno": node.lineno,
                         "kind": "function", "cls": None, "top": True,
                         "docstring": ast.get_docstring(node)})
        elif isinstance(node, ast.ClassDef):
            for m in node.body:
                if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    defs.append({"name": m.name, "lineno": m.lineno,
                                 "kind": "method", "cls": node.name, "top": False,
                                 "docstring": ast.get_docstring(m)})

    return {
        "path": str(path), "defs": defs, "refs": refs, "imports": imports,
        "bindings": bindings, "api_routes": api_routes, "tool_names": tool_names,
        "call_routes": call_routes, "getattr_names": getattr_names,
        "strings": strings, "in_test": in_test,
    }


def collect_python_files(root: Path) -> list[Path]:
    """收集源码 Python 文件；data/ 子树是运行期数据，遍历中直接剪枝。"""
    import os

    modules = root / "ai_new" / "modules"
    out: list[Path] = []
    if not modules.is_dir():
        return out
    for dirpath, dirnames, filenames in os.walk(modules):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_PARTS and d != "data"]
        for fn in filenames:
            if fn.endswith(".py"):
                out.append(Path(dirpath) / fn)
    return sorted(out)


def analyze(root: Path, sources: dict[str, str] | None = None) -> dict:
    """全量 Python 分析。sources 可注入合成源码 {rel_path: src}（自测用）。"""
    files = {}
    errors = []
    if sources:
        for rel, src in sources.items():
            try:
                files[rel] = parse_python(Path(rel), src)
            except SyntaxError as e:
                errors.append({"file": rel, "error": str(e)})
    else:
        for p in collect_python_files(root):
            rel = str(p.relative_to(root))
            try:
                files[rel] = parse_python(p, p.read_text(encoding="utf-8"))
            except SyntaxError as e:
                errors.append({"file": rel, "error": str(e)})

    global_refs: set[str] = set()
    strings: set[str] = set()
    for info in files.values():
        global_refs |= info["refs"]
        strings |= set(info["strings"])

    binding_targets = {t for info in files.values() for _, t in info["bindings"]}
    # 测试夹具/桩里注册的工具是测试局部件，不参与孤儿判定
    api_routes = [r for info in files.values() if not info["in_test"]
                  for r in info["api_routes"]]
    tool_names = [t for info in files.values() if not info["in_test"]
                  for t in info["tool_names"]]
    call_routes = {r for info in files.values() for r in info["call_routes"]}
    getattr_names = {n for info in files.values() for n in info["getattr_names"]}

    return {
        "files": files,
        "errors": errors,
        "global_refs": global_refs,
        "strings": strings,
        "binding_targets": binding_targets,
        "api_routes": api_routes,
        "tool_names": tool_names,
        "call_routes": call_routes,
        "getattr_names": getattr_names,
    }


def liveness(defn: dict, info: dict, global_refs: set, binding_targets: set,
             referenced_routes: set, getattr_names: set) -> tuple[bool, str, list[str]]:
    """判定定义是否存活。返回 (live, 依据, 证据链)。

    证据链列出在哪些注册表/需求/页面/反射渠道里找过引用，供人工复核。
    """
    name = defn["name"]
    evidence = [
        "模块内直调/self 调用", "跨文件属性/直接调用", "注册表注册点绑定",
        "需求 do 树路由 / api.call 字符串", "getattr 按名反射", "前端/HTML 绑定",
    ]
    if name.startswith("__"):
        return True, "dunder/协议方法，按框架约定存活", evidence
    if defn["top"] and name in ENTRY_FUNCS:
        return True, "框架生命周期入口 setup/start", evidence
    if defn["kind"] == "method" and name in LIFECYCLE:
        return True, "unittest 生命周期方法（setUp/tearDown 等）", evidence
    if defn["kind"] == "method" and name.startswith(HTTP_VERB_PREFIX):
        return True, "http.server 按名反射分发的 HTTP 动词方法", evidence
    if defn["kind"] == "method" and name in ("log_message", "log_request"):
        return True, "http.server 访问日志回调，按名反射调用", evidence
    if name.startswith("test_"):
        return True, "unittest 用例方法，由测试发现机制调用", evidence
    if name in binding_targets:
        return True, "注册表注册点绑定的处理函数（register 入参 / 路由元组）", evidence
    if name in info["refs"]:
        return True, "模块内进程内直调或 self/cls 调用", evidence
    if name in global_refs:
        return True, "跨文件引用（属性调用或直接调用）", evidence
    if name in getattr_names:
        return True, "getattr(..., \"%s\") 按名反射调用" % name, evidence
    for route in referenced_routes:
        if route.rsplit(".", 1)[-1] == name:
            return True, "需求/调用方按路由 %s 点名，末段与函数名同名" % route, evidence
    why = ("定义后全仓无引用：未在模块内被直调/self 调，未出现在注册表字符串、需求 do 树路由、"
           "工具表、getattr 反射或前端绑定中")
    return False, why, evidence
