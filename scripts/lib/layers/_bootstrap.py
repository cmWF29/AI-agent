"""分层用例共享的装配引导。

L2/L4 都需要一份「临时数据目录 + 真装配 + 真 HTTP 闸」，这里集中引导，
口径与 ``agent_test/private/test_core.py`` 的 setUpClass 一致：
按模块拷数据、写配置、Context(root)、build(ctx)，net 用 FakeNet 替身不联网。
"""
from __future__ import annotations

import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
MODULES = ROOT / "ai_new" / "modules"

# 让本层能直接 import 共享库（report / assert.recorder）
_LIB = ROOT / "scripts" / "lib"
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))
if str(_LIB / "assert") not in sys.path:
    sys.path.insert(0, str(_LIB / "assert"))

from ai_new.modules.agent_common.boot.private._boot import _build as build  # noqa: E402
from ai_new.modules.agent_common.boot.private._context import Context  # noqa: E402

sys.path.insert(0, str(MODULES / "agent_test" / "private"))
from _fixtures import stage, write_config  # noqa: E402


class FakeNet:
    """不联网的传输替身：按 OpenAI SSE 形状回一段事件，编排与编解码真跑。"""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, ctx, payload):
        self.calls += 1
        return {"ok": True, "status": 200, "headers": {},
                "items": [{"choices": [{"delta": {"content": "（测试）已完成。"},
                                        "finish_reason": "stop"}]}]}


@dataclass
class BootHandle:
    ctx: object
    server: object
    port: int
    tmp: tempfile.TemporaryDirectory | None
    root: Path

    def stop(self) -> None:
        """只停服务、留数据目录：重启恢复/迁移这类用例要在同一份根上再装一次。"""
        try:
            self.server.shutdown()
            self.server.server_close()
        except Exception:  # noqa: BLE001
            pass
        os.environ.pop("AI_NEW_DATA", None)

    def cleanup(self) -> None:
        self.stop()
        if self.tmp is not None:
            self.tmp.cleanup()


def default_config() -> dict:
    return {
        "server": {"host": "127.0.0.1", "port": 0, "token": "t"},
        "llm": {"base_url": "http://stub.local/v1", "api_key": "k", "model": "stub"},
        "tickets": {"stall_check": {"enabled": False}},
    }


def boot(overrides: dict | None = None, stub_net: bool = True,
         root: str | Path | None = None) -> BootHandle:
    """装配一份系统。root 为空就新建临时目录并拷贝模块数据；给了就原地复用。

    复用同一份 root 是「服务中断后恢复」与「换机器迁移」的唯一真做法：
    进程可以重来，数据目录必须还是那一份，否则断言不到任何持久化语义。
    """
    tmp = None
    if root is None:
        tmp = tempfile.TemporaryDirectory(prefix="ai_new_layer_")
        root = Path(tmp.name)
        stage(root)
    root = Path(root)
    if not (root / "agent").is_dir():
        # 给了空目录（如「搬走后的新家」）也要把模块数据铺进去，否则需求全 404。
        stage(root)
    cfg = default_config()
    if overrides:
        for k, v in overrides.items():
            if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                cfg[k].update(v)
            else:
                cfg[k] = v
    write_config(root, cfg)
    os.environ["AI_NEW_DATA"] = str(root)

    ctx = Context(root)
    build(ctx)
    if stub_net:
        # 默认不联网：编排/编解码真跑，出站报文由替身回，快且可控。
        fake = FakeNet()
        ctx.api.substitute("net.request", fake)
        ctx.api.substitute("net.request_stream", fake)
    # stub_net=False 时保留真实 net：上游故障、断连、超时这类东西只有真网卡能演。
    server = ctx.http
    port = server.server_address[1]
    return BootHandle(ctx=ctx, server=server, port=port, tmp=tmp, root=root)
