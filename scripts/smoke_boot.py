#!/usr/bin/env python3
"""装配烟测：临时数据目录里把全部模块 import + setup 起来，验证 Win/Linux 都能装配。

不驻留服务、不跑需求闭环：只证明模块可导入、装配不崩、plat 能力上报成形、
HTTP 端能起来。CI 的 Windows 作业用它替代长跑 ``agent_start.py``。

退出码：0 装配通过；1 装配/断言失败。
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ai_new.modules.agent_common.boot.private._boot import _build  # noqa: E402
from ai_new.modules.agent_common.boot.private._context import Context  # noqa: E402
from ai_new.modules.agent_test.private import _fixtures  # noqa: E402

EXPECTED_MODULES = 39


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
        loaded = _build(ctx)

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
            print("  平台: %s | 传输: %s | 锁: %s" % (
                cap["platform"], cap["transport"]["transport"],
                cap["lock"]["cross_process"]["mechanism"]))

        http = getattr(ctx, "http", None)
        if http is None:
            problems.append("http 模块未装配")
        else:
            live = ctx.api.call("health.live", {}, caller="platform:smoke", direct=True)
            if not live.get("ok"):
                problems.append("health.live 未报到: %s" % live)

        print("  模块: %d" % len(loaded))
        if problems:
            for problem in problems:
                print("  !! %s" % problem)
            print("  装配烟测: 失败")
            return 1
        print("  装配烟测通过")
        return 0
    finally:
        if http is not None:
            try:
                http.shutdown()
                http.server_close()
            except Exception:  # noqa: BLE001 — 收尾不掀翻退出码
                pass
        os.environ.pop("AI_NEW_DATA", None)
        shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
