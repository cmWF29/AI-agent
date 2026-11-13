#!/usr/bin/env python3
"""状态机与网页一致性测试。

用法：python tests/test_state_machine.py
它不启动服务、不依赖 mock LLM；只校验 web/state-machine.json、app.js、index.html 三者。
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from hive.webstate import validate  # noqa: E402


def main():
    ok, errors = validate()
    if ok:
        print("PASS web state machine consistency")
        return 0
    for e in errors:
        print("FAIL " + e)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
