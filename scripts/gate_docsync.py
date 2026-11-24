#!/usr/bin/env python3
"""代码-文档同步门禁：源码与 docs/code 镜像文档的哈希、符号清单双向闭合。

规则（每次全仓动态扫，不读缓存、不依赖 mtime）：
  1. 每个源码文件（Python / JS / scripts/*.py / data 下 yaml）都有对应文档；
  2. 源码内容哈希与文档头登记哈希不一致 → 红；
  3. 文档符号清单没覆盖新增/改名/删除的函数 → 红；
  4. 只改时间戳不改哈希/符号不能蒙混：门禁只认哈希 + 符号清单；
  5. 文档登记的符号必须能在当前源码符号集合里找到（幽灵符号 → 红）；
  6. 源码删/改名后残留的旧文档 → 孤儿文档，报红。

结构化结果见 scan()；支持 --json 机读输出。生成器见 scripts/gen_docs.py。
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
sys.path.insert(0, str(ROOT / "scripts"))

import gen_docs  # noqa: E402


def scan(root: Path | None = None) -> dict:
    root = root or ROOT
    started = time.perf_counter()
    result = gen_docs.generate(root=root, write=False)
    elapsed = time.perf_counter() - started

    problems: list[dict] = []
    for rel in result["missing"]:
        problems.append({
            "kind": "missing-doc", "file": rel, "line": 0, "symbol": "",
            "reason": "源码文件缺对应文档（docs/code 镜像未生成）",
            "evidence": ["docs/code/<镜像路径>.md 文档头"],
        })
    for rel in result["stale_hash"]:
        problems.append({
            "kind": "stale-hash", "file": rel, "line": 0, "symbol": "",
            "reason": "源码内容哈希与文档头登记哈希不一致（源码改动未同步文档）",
            "evidence": ["文档头 hash 字段", "源码字节 sha256"],
        })
    for rel in result["stale_symbols"]:
        problems.append({
            "kind": "stale-symbols", "file": rel, "line": 0, "symbol": "",
            "reason": "符号清单过期：新增/改名/删除函数未同步到文档头",
            "evidence": ["文档头 symbols 清单", "源码 ast/JS 解析符号集合"],
        })
    for rel in result["orphans"]:
        problems.append({
            "kind": "orphan-doc", "file": rel, "line": 0, "symbol": "",
            "reason": "孤儿文档：源码已删除或改名，旧文档残留",
            "evidence": ["docs/code 文档", "当前源码清单"],
        })
    if result.get("index_error"):
        problems.append({
            "kind": "stale-index", "file": "ai_new/modules/agent_common/demand_engine/data/code-docs.json",
            "line": 0, "symbol": "",
            "reason": "源码-文档机读索引与 docs/code 不一致: %s" % result["index_error"],
            "evidence": ["code-docs.json", "docs/code 文档头"],
        })
    for rel, err in result["parse_errors"]:
        problems.append({
            "kind": "parse-error", "file": rel, "line": 0, "symbol": "",
            "reason": "源码解析失败（并发改动/语法问题），该文件文档未纳入符号闭合: %s" % err,
            "evidence": ["源码 YAML 解析"],
        })

    stats = dict(result["stats"])
    stats["problems"] = len(problems)
    stats["elapsed_ms"] = round(elapsed * 1000, 1)
    return {"problems": problems, "stats": stats,
            "tiers": {"docsync": "static"}}


def problems() -> list[str]:
    return [format_problem(p) for p in scan()["problems"]]


def format_problem(p: dict) -> str:
    return "%s — %s" % (p["file"], p["reason"])


def main(argv: list[str] | None = None) -> int:
    argv = list(argv or sys.argv[1:])
    as_json = "--json" in argv
    result = scan()

    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if not result["problems"] else 1

    s = result["stats"]
    print("代码-文档同步：源码 %d，缺文档 %d，哈希过期 %d，符号过期 %d，孤儿文档 %d，耗时 %.1fms"
          % (s["sources"], s["missing"], s["stale_hash"], s["stale_symbols"],
             s["orphans"], s["elapsed_ms"]))
    if result["problems"]:
        print("\n代码-文档同步门禁未通过：")
        for p in result["problems"]:
            print("  - " + format_problem(p))
        return 1
    print("代码-文档同步门禁通过：文档与源码哈希、符号清单一致")
    return 0


if __name__ == "__main__":
    sys.exit(main())
