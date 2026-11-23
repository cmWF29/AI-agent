"""主机资源能力：内存、磁盘、负载这类"这台机器怎样了"的读数。

health 以前自己 `import shutil`、读 `/proc/meminfo` —— 这就是把"机器观测"
这件公共能力塞进业务模块。收编后只调 `host.info`。
"""
from __future__ import annotations

import os

from .private import _probe
from .private import _profile


def setup(ctx):
    ctx.host = _probe
    ctx.api.register("host.info", lambda c, p: _probe.info(c),
                     "内存/磁盘/负载读数", module="host")
    ctx.api.register("host.which", lambda c, p: _probe.which(c, p),
                     "探测 CLI 命令是否在 PATH", module="host")
    ctx.api.register("host.importable", lambda c, p: _probe.importable(c, p),
                     "探测 Python 包当前解释器可否导入", module="host")
    ctx.api.register("host.env", lambda c, p: _probe.env((p or {}).get("name")),
                     "读一个环境变量", module="host")
    ctx.api.register("host.executable", lambda c, p: _probe.executable(c),
                     "当前 Python 解释器路径", module="host")
    ctx.api.register("host.profile", _route_profile,
                     "只读：节点环境 profile 快照（OS/CLI/包/环境变量/解释器）", module="host")
    ctx.api.register("host.readiness", _route_readiness,
                     "工具就绪度：按依赖声明 vs 节点探针判 ready/missing_deps，缺依赖不静默放行",
                     module="host")
    return True


def _route_profile(ctx, payload):
    payload = payload or {}
    cli = {c: ctx.api.call("host.which", {"name": c}, caller=None).get("found")
           for c in payload.get("cli") or []}
    pkgs = {p: ctx.api.call("host.importable", {"name": p}, caller=None).get("importable")
            for p in payload.get("pip") or []}
    env = {v: ctx.api.call("host.env", {"name": v}, caller=None).get("value")
           for v in payload.get("env") or []}
    exe = ctx.api.call("host.executable", {}, caller=None).get("path")
    profile = _profile.build_profile(
        {"os": os.name, "executable": exe, "cli": cli, "pkgs": pkgs, "env": env},
        node=payload.get("node") or "")
    return {"ok": True, "profile": profile}


def _route_readiness(ctx, payload):
    """按工具依赖声明对照节点探针判就绪度；缺依赖列具体缺失项，不静默放行。"""
    tool = payload.get("tool") or {}
    deps = tool.get("deps") or {}
    cli, pkgs, env = {}, {}, {}
    for cmd in deps.get("cli") or []:
        cli[cmd] = bool(ctx.api.call("host.which", {"name": cmd}, caller=None).get("found"))
    for pkg in deps.get("pip") or []:
        pkgs[pkg] = bool(ctx.api.call("host.importable", {"name": pkg}, caller=None).get("importable"))
    for var in deps.get("env") or []:
        env[var] = ctx.api.call("host.env", {"name": var}, caller=None).get("value")
    return _profile.readiness(tool, {"cli": cli, "pkgs": pkgs, "env": env})


def info(ctx):
    return _probe.info(ctx)
