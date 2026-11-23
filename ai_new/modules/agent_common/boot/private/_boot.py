"""组合根：扫描装配依赖图，动态加载并按 DAG 装配所有模块。

装配分成两段，第二段由「模块是否导出 start(ctx)」决定，不靠任何标签：

    setup(ctx)  按拓扑序调用：装填自己的 ctx 面、注册路由、声明 hook 点
    start(ctx)  全部 setup 完成后调用：开始接收请求、拉起后台线程

顺序不手写：`_plan()` 扫描每个模块 setup 阶段真正读写的 ctx 面，推导 DAG。
组合根自己不写任何 import 语句，按图用 importlib 动态加载。

它自己也不写日志：装配计划同样是一个 hook 点（boot.plan/boot.ready/boot.failed），
由运维业务订阅记录；连钩子机制都没装起来时，退回进程 stderr 兜底。
"""
from __future__ import annotations

import importlib
import threading
import yaml
import os
import time
import traceback
from pathlib import Path

from ai_new.modules.agent_common.plat.private import _proc as plat_proc

from ._context import Context
from ._graph import plan as _scan

MODULES_ROOT = Path(__file__).resolve().parents[3]   # ai_new/modules
ROOT_DIR = MODULES_ROOT.parents[1]                   # 项目根


def _profile(name="agent"):
    """装配用哪些模块组：读 data/profiles.yaml，不写在代码里。

    组只是目录，不是层级：`agent` 跑系统，`agent_test` 跑验收，同一个扫描器。
    """
    path = Path(__file__).resolve().parents[1] / "data" / "profiles.yaml"
    external = os.environ.get("AI_NEW_DATA")
    if external:
        path = Path(external) / "agent_common" / "boot" / "profiles.yaml"
    record = {}
    if path.is_file():
        record = yaml.safe_load(path.read_text(encoding="utf-8")).get("profiles") or {}
    return [MODULES_ROOT / group for group in (record.get(name) or ["agent_common", "agent"])]


def _demands_dir():
    """需求数据在 demand_engine 模块自己的 data 下；扫描器用它算需求接线图。"""
    base = MODULES_ROOT / "agent_common" / "demand_engine" / "data"
    external = os.environ.get("AI_NEW_DATA")
    return Path(external) / "agent_common" / "demand_engine" if external else base


def _plan(module_dirs=None):
    """扫描装配 DAG，返回计划（roots / order / edges / reasons / warnings / hooks / packages）。"""
    dirs = module_dirs or _profile()
    return _scan(dirs, data_dir=_demands_dir())

def _build(ctx, module_dirs=None):
    """按扫描出来的顺序装配所有模块，返回已装配模块名列表。"""
    result = _plan(module_dirs)
    if result["cycle"]:
        raise RuntimeError("模块装配依赖成环，无法排序: %s"
                           % " -> ".join(result["cycle"]))
    packages = result["packages"]
    loaded = []
    timings = []
    for name in result["order"]:
        started_at = time.perf_counter()
        module = importlib.import_module(packages[name])
        module.setup(ctx)
        ctx.loaded[name] = module
        loaded.append(name)
        timings.append({"module": name, "ms": round((time.perf_counter() - started_at) * 1000, 2)})

    # 部署意图在装配末尾编成通信绑定：换拓扑只改 api/data/deploy.yaml，重启即生效。
    # 编译是纯路径推导（不依赖服务），放在这里就不会出现"改了配置但跑的还是旧绑定"。
    api_module = ctx.loaded.get("api")
    if api_module is not None:
        api_module.compile_transport(ctx)

    # 钩子机制此时才就位（hooks 在装配序列里）。组合根声明自己的点：
    # 名字必须写字面量，静态扫描靠这几行才能把 boot 的诊断也算进需求图。
    # 第二段：只有导出 start(ctx) 的模块需要，此时全体都已就位
    started = []
    for name in loaded:
        starter = getattr(ctx.loaded[name], "start", None)
        if callable(starter):
            starter(ctx)
            started.append(name)

    return loaded


def main(argv=None):
    root = ROOT_DIR
    ctx = Context(root)
    argv = list(argv or [])
    if "--compile-transport" in argv:
        # 装配之前就能重编通信绑定：只读源码与部署意图，不碰运行中的进程
        api = importlib.import_module("ai_new.modules.agent_common.api")
        record = api.compile_transport(ctx)
        print("绑定写入 %s" % record["path"])
        print("  默认通道: %s" % record["default"])
        print("  模块绑定: %s" % (record["routes"] or "无（全直连）"))
        print("  模块 %d 个，路由字面量 %d 个"
              % (record["stats"]["modules"], record["stats"]["route_literals"]))
        return 0
    try:
        _build(ctx)
        _await_serve(ctx)
        return 0
    except Exception:
        # 组合根不做"记录失败"这种业务，失败就原样打到 stderr 让进程退出码说话
        traceback.print_exc()
        return 1


def _await_serve(ctx):
    """常驻模式：装配完成后主线程驻留，直到收到终止信号。

    HTTP 服务跑在非 daemon 后台线程。若 main 直接返回，主线程结束会触发解释器
    关闭序列：atexit 先把各桥接线程池关闭，后台线程随后接到的请求再向已关闭的
    执行器提交任务，就抛 "cannot schedule new futures after interpreter
    shutdown"。主线程驻留才能让解释器保持存活；收到 SIGINT/SIGTERM 后再优雅
    关停服务。
    """
    server = getattr(ctx, "http", None)
    if server is None:
        return
    stopped = threading.Event()

    def _stop(signum, frame):  # noqa: ARG001 —— 信号处理器签名固定
        stopped.set()

    # 信号档位按 OS 收口到 plat：POSIX 注册 SIGINT/SIGTERM；Windows 只注册
    # SIGINT（SIGTERM 经 TerminateProcess 直达进程，不跑 Python 处理器）。
    plat_proc.install_stop_handler(_stop)
    stopped.wait()
    try:
        server.shutdown()
    finally:
        server.server_close()
