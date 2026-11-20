"""把部署意图编译成运行时通信绑定：代码是模板，绑定是产物。

模板：模块里永远只写 `ctx.api.call("module.fn", payload, caller)` —— 逻辑调用。
产物：这条调用实际走"直接调用 / 内存队列 / 网络 RPC"，由本模块生成的
`data/gen/bindings.json` 决定。换部署拓扑只重跑编译，模板代码一行不改。

部署意图写在 `data/deploy.json`（可选）：

    {
      "default": "direct",
      "nodes": {"worker-a": "http://127.0.0.1:8790"},
      "modules": {"tickets": {"kind": "http", "node": "worker-a"},
                  "ops": {"kind": "memory"}}
    }

没有这份文件 = 全直连，等于单进程跑，与单机行为完全一致。

它是 api 模块的能力，不是根目录下的脚本：
    服务：`POST /api/api/transport_compile`（运行中的系统也能重编绑定）
    入口：`python agent_start.py --compile-transport`（装配之前就能编，只读文件）
"""
from __future__ import annotations

import ast
import yaml
from pathlib import Path

MODULES_DIR = Path("ai_new") / "modules"
DEFAULT_OUT = Path("gen") / "bindings.yaml"
DEFAULT_DEPLOY = Path("deploy.yaml")


def data_dir():
    """api 自己的数据目录（编译可以在装配之前跑，所以纯路径推导）。"""
    import os
    module = Path(__file__).resolve().parents[1]
    external = os.environ.get("AI_NEW_DATA")
    return Path(external) / module.parent.name / module.name if external else module / "data"
KINDS = ("direct", "unix", "tcp", "shm")


def groups_of(root):
    """模块组：优先按给定 root 找；root 不是仓库布局（如测试的临时数据根）时退回源码树。"""
    base = Path(root) / MODULES_DIR
    if not base.is_dir():
        base = Path(__file__).resolve().parents[3]
    return sorted(p for p in base.iterdir() if p.is_dir() and not p.name.startswith("__"))


def modules_of(root):
    """模块清单：组下面的一层目录，组本身不是模块。"""
    names = []
    for group in groups_of(root):
        for entry in sorted(group.iterdir()):
            if entry.is_dir() and (entry / "__init__.py").is_file():
                names.append(entry.name)
    return sorted(names)


def route_literals(root, modules):
    """源码里出现的、形如 `模块.函数` 的字符串（用来核对编译结果是否覆盖调用）。"""
    found = set()
    for path in sorted((Path(root) / MODULES_DIR).rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                head, _, rest = node.value.partition(".")
                if head in modules and rest and (rest.isidentifier() or rest == "*"):
                    found.add(node.value)
    return sorted(found)


def build(root, deploy_path=None):
    """返回绑定记录（纯函数：同一输入必得同一输出）。"""
    root = Path(root).resolve()
    modules = modules_of(root)
    deploy_file = Path(deploy_path) if deploy_path else data_dir() / DEFAULT_DEPLOY
    deploy = yaml.safe_load(deploy_file.read_text(encoding="utf-8")) if deploy_file.is_file() else {}

    routes = {}

    listen = deploy.get("listen") or {}

    def _bind(label, spec):
        spec = spec or {}
        kind = spec.get("kind") or "direct"
        if kind not in KINDS:
            raise ValueError("%s 的通道非法: %s（可选 %s）" % (label, kind, KINDS))
        if kind == "unix" and not (listen.get("unix") or {}).get("path"):
            raise ValueError("%s 走 unix 但 deploy.yaml 没给 listen.unix.path" % label)
        if kind == "tcp" and not (listen.get("tcp") or {}).get("port"):
            raise ValueError("%s 走 tcp 但 deploy.yaml 没给 listen.tcp" % label)
        if kind == "shm" and not (listen.get("shm") or {}).get("dir"):
            raise ValueError("%s 走 shm 但 deploy.yaml 没给 listen.shm.dir" % label)
        return {"kind": kind}

    # 模块级：整组路由换通道
    for module, spec in sorted((deploy.get("modules") or {}).items()):
        if module not in modules:
            raise ValueError("deploy.yaml 里的模块不存在: %s" % module)
        routes[module + ".*"] = _bind("模块 " + module, spec)

    # 路由级：单条能力换通道（同名时覆盖模块级）
    for route, spec in sorted((deploy.get("routes") or {}).items()):
        module, _, fn = route.partition(".")
        if not fn or module not in modules:
            raise ValueError("deploy.yaml 里的路由不存在: %s" % route)
        routes[route] = _bind("路由 " + route, spec)

    default_kind = deploy.get("default") or "direct"
    if default_kind not in KINDS:
        raise ValueError("default 通道非法: %s" % default_kind)

    return {
        "generated_by": "ai_new/modules/agent_common/api/private/_gen.py",
        "default": {"kind": default_kind},
        "listen": listen,
        "routes": routes,
        "stats": {"modules": len(modules),
                  "route_literals": len(route_literals(root, modules)),
                  "bound": len(routes)},
    }


def compile_transport(ctx, out=None, deploy=None):
    """把部署意图编译成绑定文件；返回统一的 envelope（服务与命令行共用）。"""
    record = build(ctx.root, deploy)
    target = Path(out) if out else data_dir() / DEFAULT_OUT
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(yaml.safe_dump(record, allow_unicode=True, sort_keys=True, default_flow_style=False) + "\n",
                      encoding="utf-8")
    return {"path": str(target), "default": record["default"]["kind"],
            "routes": record["routes"], "stats": record["stats"]}
