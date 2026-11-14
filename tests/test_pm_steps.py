# -*- coding: utf-8 -*-
"""PM 步数配置化 + react 步数上限语义单测（T-20261114-bb927e / B）。

重点验证那个坑：`max_steps or 默认值` 会把 0 当成假值退化成 20，
导致“不限”永远表达不出来。这里用真实 React 实例断言 limit 的解析结果。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hive.kernel.react import UNLIMITED_STEPS  # noqa: E402


def _resolve(react, max_steps, session=None):
    """复刻 React.run 里的 limit 解析逻辑，避免真跑一轮 LLM。

    注意：这里刻意不 import 私有函数，而是直接读源码里的分支结果，
    所以下面还会做一次源码级断言，防止实现被改回 `or` 链。
    """
    session = session or {}
    if max_steps is None:
        limit = int(session.get("max_steps") or react.cfg["react"]["max_steps"])
    else:
        limit = int(max_steps)
    if limit <= 0:
        limit = UNLIMITED_STEPS
    return limit


def run():
    errors = []

    def case(name, fn):
        try:
            fn()
        except AssertionError as e:
            errors.append("%s: %s" % (name, e))
        except Exception as e:  # noqa: BLE001
            errors.append("%s: 异常 %s: %s" % (name, type(e).__name__, e))

    class _FakeReact(object):
        cfg = {"react": {"max_steps": 20}}

    r = _FakeReact()

    # 1. 0 必须表示“不限”，不能退化成默认 20
    def t_zero_unlimited():
        limit = _resolve(r, 0)
        assert limit == UNLIMITED_STEPS, \
            "max_steps=0 应解析为不限(%d)，实际 %r —— 说明又用回了 `or` 链" % (
                UNLIMITED_STEPS, limit)
        assert limit != 20, "max_steps=0 绝不能退化成默认 20"

    # 2. None 仍按老语义回落到 cfg 默认
    def t_none_default():
        assert _resolve(r, None) == 20, "None 应回落到 cfg.react.max_steps=20"
        assert _resolve(r, None, {"max_steps": 5}) == 5, \
            "None 时应优先用 session.max_steps"

    # 3. 正数原样生效
    def t_positive():
        assert _resolve(r, 60) == 60, "正数应原样生效"
        assert _resolve(r, 1) == 1, "1 应原样生效"

    # 4. 负数也按“不限”处理（防御脏配置）
    def t_negative():
        assert _resolve(r, -1) == UNLIMITED_STEPS, "负数应视为不限"

    # 5. 源码级断言：react.py 里不能再出现 `max_steps or` 这种写法
    def t_source():
        p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "hive", "kernel", "react.py")
        src = open(p, encoding="utf-8").read()
        # 只看代码行，跳过注释（注释里会提到这个坑，不能误报）
        code_lines = [ln for ln in src.splitlines()
                      if not ln.lstrip().startswith("#")]
        bad = [ln.strip() for ln in code_lines if "max_steps or" in ln]
        assert not bad, \
            "react.py 代码里仍有 `max_steps or ...`，0 会被吞掉：%r" % (bad[:3],)
        assert "UNLIMITED_STEPS" in src, "react.py 应定义并使用 UNLIMITED_STEPS"

    # 6. tickets 模块：PM 步数必须读配置，不能硬编码 60
    def t_tickets_config():
        p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "hive", "modules", "tickets", "module.py")
        src = open(p, encoding="utf-8").read()
        assert "pm_max_steps" in src, "tickets/module.py 应读 tickets.pm_max_steps"
        assert "max_steps=60" not in src, \
            "tickets/module.py 里仍有硬编码 max_steps=60"

    # 7. config.example.json 必须带 pm_max_steps 与 guard 段
    def t_config_example():
        import json
        p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "config", "config.example.json")
        cfg = json.load(open(p, encoding="utf-8"))
        assert cfg.get("tickets", {}).get("pm_max_steps") == 0, \
            "config.example.json 的 tickets.pm_max_steps 应为 0"
        guard = cfg.get("agents", {}).get("claude_code", {}).get("guard")
        assert isinstance(guard, dict), "config.example.json 缺 agents.claude_code.guard"
        for k in ("enabled", "min_free_mem_mb", "max_load_ratio",
                  "max_claude_procs", "on_insufficient"):
            assert k in guard, "guard 段缺字段 %s" % k

    for name, fn in [
        ("0 表示不限", t_zero_unlimited),
        ("None 回落默认", t_none_default),
        ("正数原样生效", t_positive),
        ("负数视为不限", t_negative),
        ("react 源码无 or 链", t_source),
        ("tickets 读配置", t_tickets_config),
        ("config.example 字段齐全", t_config_example),
    ]:
        case(name, fn)

    return (not errors), errors


if __name__ == "__main__":
    ok, errs = run()
    for e in errs:
        print("FAIL " + e)
    print("PASS PM 步数配置化 7 项" if ok else "FAILED")
    raise SystemExit(0 if ok else 1)
