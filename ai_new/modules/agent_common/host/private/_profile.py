"""节点环境 profile 与工具就绪度纯计算；不读盘、不取时钟、不调服务。

节点事实（OS、可用 CLI、可导入包、选定环境变量、解释器路径）是主机实时
探测结果，由 host 探针取；这里只做装配与判定。与主机无关的业务约定
不进节点 profile。
"""
from __future__ import annotations


def build_profile(probes, node=""):
    """把探针结果装配成节点 profile。

    probes: {os, shell, executable, cli:{name:found}, pkgs:{name:importable},
             env:{name:value}}。
    """
    return {
        "node": str(node or ""),
        "os": str(probes.get("os") or ""),
        "shell": str(probes.get("shell") or ""),
        "executable": str(probes.get("executable") or ""),
        "cli": dict(probes.get("cli") or {}),
        "pkgs": dict(probes.get("pkgs") or {}),
        "env": dict(probes.get("env") or {}),
    }


def readiness(tool, profile):
    """按依赖声明 vs 节点 profile 判定工具就绪度。

    缺任一依赖即 ``missing_deps``，并列出具体缺失项；缺依赖判不可用，
    不静默放行执行。
    """
    deps = (tool or {}).get("deps") or {}
    missing = {"cli": [], "pip": [], "env": []}
    cli = (profile or {}).get("cli") or {}
    pkgs = (profile or {}).get("pkgs") or {}
    env = (profile or {}).get("env") or {}
    for cmd in deps.get("cli") or []:
        if not cli.get(cmd):
            missing["cli"].append(cmd)
    for pkg in deps.get("pip") or []:
        if not pkgs.get(pkg):
            missing["pip"].append(pkg)
    for var in deps.get("env") or []:
        if env.get(var) in (None, ""):
            missing["env"].append(var)
    ready = not (missing["cli"] or missing["pip"] or missing["env"])
    return {"ready": ready,
            "status": "ready" if ready else "missing_deps",
            "missing": missing}


def resolve_layered(layers):
    """分层配置解析：layers 由泛化到具体 [public, node, project, ticket]。

    后层覆盖前层（最具体覆盖最泛化）；project/ticket 归属层覆盖节点级，节点级覆盖公共。
    """
    out = {}
    for layer in layers or []:
        out.update(layer or {})
    return out
