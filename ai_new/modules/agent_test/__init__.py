"""验证模块：和被测系统**同构**，但不是它的一部分。

为什么它是个模块？
- 测试自己也有需求（验哪些条款、静态还是运行时、失败算不算致命），
  所以它有自己的清单数据 `data/checks.json`，而不是把清单写在代码里。
- 它和别的模块同构（`__init__.py` + `private/`），所以"模块"这套规矩对它也成立。

为什么它不在 agent 的装配里？
- `data/profiles.json` 决定了每个入口装配哪些组：`agent` 只装
  `agent_common + agent`；本模块所在的 `agent_test` 只在 `test_start.py` 下被跑。
- 换句话说，它"不是模块"这件事没有任何特例：换一个 profile 就换一套装配。

它对被测系统的耦合是**单向且公开**的：评审者可以看被评审者，反过来不行。
"""
from __future__ import annotations

import yaml
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent / "private"


def checks():
    """验收清单：agent_test 自己的数据（<模块>/data/checks.json）。"""
    path = Path(__file__).resolve().parent / "data" / "checks.yaml"
    external = os.environ.get("AI_NEW_DATA")
    if external:
        path = Path(external) / "agent_test" / "agent_test" / "checks.yaml"
    if not path.is_file():
        return []
    record = yaml.safe_load(path.read_text(encoding="utf-8"))
    return [c for c in record.get("checks") or [] if c.get("enabled", True)]


def main(argv=None):
    """跑验收：python test_start.py [--only id]；返回退出码。"""
    argv = list(argv or [])
    only = None
    for i, item in enumerate(argv):
        if item == "--only" and i + 1 < len(argv):
            only = argv[i + 1]

    if str(HERE) not in sys.path:
        sys.path.insert(0, str(HERE))
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))

    selected = [c for c in checks() if not only or c["id"] == only]
    if not selected:
        print("没有可跑的检查（data/checks.json），或用 --only 指定的不存在")
        return 2

    failures = []
    for check in selected:
        print("\n== %s（%s）%s" % (check["id"], check.get("kind", "static"),
                                   check.get("title", "")))
        suite = unittest.defaultTestLoader.loadTestsFromName(check["module"])
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        if not result.wasSuccessful():
            failures.append(check["id"])

    print("\n验收结果：%d 组，失败 %s" % (len(selected), failures or "无"))
    return 0 if not failures else 1
