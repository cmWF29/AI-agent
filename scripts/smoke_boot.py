#!/usr/bin/env python3
"""装配烟测：临时数据目录里把全部模块 import + setup 起来，验证 Win/Linux 都能装配。

纯装配口径：只跑 setup 段，不起常驻 HTTP 服务、不拉后台线程/定时器/续跑需求，
装配完即返回。健康探针走进程内直连（``direct=True``），不经过本机通道。
CI 的 Windows 作业用它替代长跑 ``agent_start.py``；任何后台驻留都可能拖住进程
退出，烟测阶段一律不允许。

退出码：0 装配通过；1 装配/断言失败。
"""
import faulthandler
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# 120s 后自动 dump 全线程栈并重复：CI 挂死时日志里能拿到真实卡点，不靠猜。
faulthandler.enable()
faulthandler.dump_traceback_later(120, repeat=True)

from ai_new.modules.agent_common.boot.private._boot import _build  # noqa: E402
from ai_new.modules.agent_common.boot.private._context import Context  # noqa: E402
from ai_new.modules.agent_test.private import _fixtures  # noqa: E402

EXPECTED_MODULES = 39


def _log(msg):
    """打印并立刻 flush：CI 日志按行落盘，缓冲不会把最后一段卡住的输出藏掉。"""
    print(msg, flush=True)


def main():
    workdir = Path(tempfile.mkdtemp(prefix="ai_new_smoke_"))
    data = workdir / "data"
    ctx = None
    http = None
    try:
        _fixtures.stage(data)
        _fixtures.write_config(data, {
            "server": {"host": "127.0.0.1", "port": 0, "token": ""},
            "llm": {"base_url": "http://stub.local/v1", "api_key": "k", "model": "stub"},
            "tickets": {"stall_check": {"enabled": False}},
        })
        os.environ["AI_NEW_DATA"] = str(data)
        ctx = Context(data)
        # start_phase=False：只装配，不起服务/后台线程；烟测不驻留。
        loaded = _build(ctx, start_phase=False)

        problems = []
        if len(loaded) != EXPECTED_MODULES:
            problems.append("模块数不是 %d: %s" % (EXPECTED_MODULES, len(loaded)))
        if not hasattr(ctx, "plat"):
            problems.append("ctx.plat 未装填")
        else:
            cap = ctx.plat.capability()
            for facet in ("lock", "transport", "proc"):
                if not cap.get(facet, {}).get("ok"):
                    problems.append("plat %s 能力未就绪" % facet)
            _log("  平台: %s | 传输: %s | 锁: %s" % (
                cap["platform"], cap["transport"]["transport"],
                cap["lock"]["cross_process"]["mechanism"]))

        http = getattr(ctx, "http", None)
        if http is None:
            problems.append("http 模块未装配")
        # 健康探针走进程内直连：不经过本机通道，不依赖监听端口。
        live = ctx.api.call("health.live", {}, caller="platform:smoke", direct=True)
        if not live.get("ok"):
            problems.append("health.live 未报到: %s" % live)

        _log("  模块: %d" % len(loaded))
        if problems:
            for problem in problems:
                _log("  !! %s" % problem)
            _log("  装配烟测: 失败")
            return 1
        _log("  装配烟测通过")
        return 0
    finally:
        # 装配段没有 serve_forever 线程：只关闭 setup 阶段绑定的监听 socket，
        # 不调 shutdown()（shutdown 等待从未进入的常驻循环，本身就是挂死源之一）。
        if http is not None:
            try:
                http.server_close()
            except Exception:  # noqa: BLE001 — 收尾不掀翻退出码
                pass
        os.environ.pop("AI_NEW_DATA", None)
        shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
