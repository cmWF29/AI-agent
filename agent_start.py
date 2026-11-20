"""AI_NEW 启动入口：python agent_start.py

进程入口只做一件事 —— 把装配交给组合根，然后等它返回退出码。
真正的装配、顺序推导、启动都在 ai_new/modules/agent_common/boot/private/_boot.py。

桩模式：环境变量 ``AI_NEW_STUB=1`` 时，先在本进程起本地桩 LLM 服务，再把
``llm.base_url`` 经环境变量指到桩；全程不连真实上游、不烧额度，供演示/自测使用。
桩实现归测试侧（agent_test），组合根与生产模块不感知桩的存在。
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def _maybe_start_stub():
    """桩模式：起本地桩服务并把 base_url 指过去，返回桩 server（持有引用防回收）。

    非桩模式直接返回 None。桩策略是演示装配参数，集中在外壳这里声明。
    """
    if os.environ.get("AI_NEW_STUB") != "1":
        return None
    from ai_new.modules.agent_test.private import stub_llm

    policy = stub_llm.StubPolicy(tool_rate=1.0, spawn_rate=1.0, delay_base=0.01,
                                 role_rounds=1, filler_words=120, max_role_steps=2)
    server, _thread, url = stub_llm.start_stub(policy)
    os.environ["AI_NEW_LLM_BASE_URL"] = url
    return server


def main():
    stub = _maybe_start_stub()
    from ai_new.modules.agent_common.boot import main as boot_main
    return boot_main(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
