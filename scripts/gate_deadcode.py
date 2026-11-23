#!/usr/bin/env python3
"""死代码静态扫描门禁：定义后从未被引用/调用的函数、方法、未使用 import、孤儿注册路由/工具。

口径（每次执行全仓动态扫描，不读缓存、不维护人工豁免清单）：
  1. 先建「注册表 / 需求 DSL / 字符串路由 / 工具表 / 前端绑定」引用集合，再判未引用；
  2. 引用证据只来自可执行代码、注册表与数据清单，不靠人工补名单；
  3. 宁可多报不漏报：每条命中附依据链（在哪些注册表/需求/页面里找不到引用）；
  4. 动态前端档（--ui）起桩 + 浏览器真实渲染取控件绑定；起不来则降级静态解析，
     打印「前端部分未动态验证」，不把装配期并发改动算成本门禁失败。

结构化结果见 scan()；人类可读汇总是薄薄一层格式化。支持 --json 机读输出。
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from scan import demand as demand_scan  # noqa: E402
from scan import js_scan, python_scan  # noqa: E402

PLATFORM_ROUTES = ROOT / "ai_new/modules/agent_common/api/data/platform-routes.yaml"
TOOLS_YAML = ROOT / "ai_new/modules/agent_common/tools/data/tools.yaml"
SESSION_TOOLS = ROOT / "ai_new/modules/agent/sessions/data/session-tools.yaml"


def _load_yaml(path: Path) -> dict:
    if not path.is_file():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _session_tool_names() -> set[str]:
    doc = _load_yaml(SESSION_TOOLS)
    names: set[str] = set()
    if isinstance(doc, dict):
        for items in doc.values():
            if isinstance(items, list):
                names.update(str(x) for x in items)
    return names


def scan(root: Path | None = None, py_sources: dict[str, str] | None = None,
         js_sources: dict[str, str] | None = None, html_text: str | None = None) -> dict:
    """跑全仓扫描，返回 {problems, stats, tiers}。

    py_sources / js_sources / html_text 可注入合成源码做自测；
    每条 problem 为 {kind, file, line, symbol, reason, evidence}。
    """
    root = root or ROOT
    started = time.perf_counter()

    platform = _load_yaml(PLATFORM_ROUTES)
    platform_routes = set((platform.get("routes") or {}).keys())
    tools_doc = _load_yaml(TOOLS_YAML)
    tools_names = set(tools_doc.keys()) if isinstance(tools_doc, dict) else set()
    session_tool_names = _session_tool_names()

    demands = demand_scan.load_demands(root)
    demand_routes = demand_scan.demand_routes(demands)

    py = python_scan.analyze(root, sources=py_sources)
    referenced_routes = demand_routes | py["call_routes"] | platform_routes

    problems: list[dict] = []

    # ---- Python 死函数/方法 ----
    for rel, info in py["files"].items():
        for defn in info["defs"]:
            live, why, evidence = python_scan.liveness(
                defn, info, py["global_refs"], py["binding_targets"],
                referenced_routes, py["getattr_names"])
            if not live:
                problems.append({
                    "kind": "dead-function", "file": rel, "line": defn["lineno"],
                    "symbol": defn["name"], "reason": why, "evidence": evidence,
                })

    # ---- 未使用 import（__init__.py 的导入可能是对外导出，不纳入此项）----
    for rel, info in py["files"].items():
        if Path(rel).name == "__init__.py":
            continue
        for imp in info["imports"]:
            if imp["module"] == "__future__":
                continue
            if imp["alias"] not in info["refs"]:
                problems.append({
                    "kind": "unused-import", "file": rel, "line": imp["lineno"],
                    "symbol": imp["alias"],
                    "reason": "import %s 未在本文件使用" % imp["module"],
                    "evidence": ["文件内标识符引用集合"],
                })

    # ---- 孤儿注册路由 / 工具 ----
    # 工具名在代码目录串里出现 ≥2 个文件（注册点 + 目录/桩目录）视为有引用；
    # 仅注册点单点出现才算孤儿。
    tool_files: dict[str, set[str]] = {}
    for rel, info in py["files"].items():
        if info["in_test"]:
            continue
        for t in info["tool_names"]:
            tool_files.setdefault(t, set()).add(rel)
    tool_string_files: dict[str, set[str]] = {}
    for rel, info in py["files"].items():
        if info["in_test"]:
            continue
        for s in set(info["strings"]):
            tool_string_files.setdefault(s, set()).add(rel)

    orphan_routes = sorted(set(py["api_routes"]) - referenced_routes)
    orphan_tools = []
    for t in sorted(set(py["tool_names"])):
        if t in tools_names or t in session_tool_names or t in demands:
            continue
        files = tool_string_files.get(t, set()) - tool_files.get(t, set())
        if files:
            continue  # 在注册点之外的代码目录/目录清单里被引用
        orphan_tools.append(t)
    for route in orphan_routes:
        problems.append({
            "kind": "orphan-route", "file": "-", "line": 0, "symbol": route,
            "reason": "注册后无调用方：不在需求 do 树、不在 api.call 字符串、不在平台清单",
            "evidence": ["需求 do 树 call/send", "api.call 字符串路由", "platform-routes.yaml 平台清单"],
        })
    for tool in orphan_tools:
        problems.append({
            "kind": "orphan-tool", "file": "-", "line": 0, "symbol": tool,
            "reason": "注册后无引用：不在工具表、不在会话工具名单、不对应任何需求",
            "evidence": ["tools.yaml 工具表", "session-tools.yaml 会话名单", "需求 id 集合"],
        })

    # ---- JS 死函数 ----
    js = js_scan.analyze(root, sources=js_sources, html=html_text)
    for rel, info in js["files"].items():
        for defn in info["defs"]:
            live = (defn["name"] in js["global_refs"]
                    or defn["name"] in js["html_tokens"]
                    or defn["name"] in js["mounted"])
            if not live:
                problems.append({
                    "kind": "dead-js-function", "file": rel, "line": defn["lineno"],
                    "symbol": defn["name"],
                    "reason": "JS 函数定义后全仓无引用（跨文件/HTML 绑定/window 挂载均未命中）",
                    "evidence": ["跨文件标识符引用", "manage.html HTML 绑定", "window.* 挂载"],
                })

    elapsed = time.perf_counter() - started
    stats = {
        "py_files": len(py["files"]),
        "js_files": len(js["files"]),
        "py_symbols": sum(len(i["defs"]) for i in py["files"].values()),
        "js_symbols": sum(len(i["defs"]) for i in js["files"].values()),
        "reference_edges": sum(len(i["refs"]) for i in py["files"].values())
        + sum(len(i["refs"]) for i in js["files"].values()),
        "problems": len(problems),
        "elapsed_ms": round(elapsed * 1000, 1),
    }
    return {"problems": problems, "stats": stats,
            "tiers": {"python": "static", "javascript": "static",
                      "frontend-dynamic": "degraded"}}


def problems() -> list[str]:
    """兼容既有门禁约定：返回格式化后的命中条目字符串列表。"""
    return [format_problem(p) for p in scan()["problems"]]


def format_problem(p: dict) -> str:
    loc = "%s:%d" % (p["file"], p["line"]) if p["line"] else p["file"]
    return "%s %s — %s" % (loc, p["symbol"], p["reason"])


# ---------------------------------------------------------------- 动态前端档

def probe_frontend(base_url: str | None = None) -> dict:
    """起桩 + 浏览器真实渲染取页面控件绑定；失败返回降级说明。

    动态档只做前端绑定验证，不单独产生死代码判定。
    """
    tier = "degraded"
    controls: list[dict] = []
    errors: list[str] = []
    note = ""
    try:
        from playwright.async_api import async_playwright  # noqa: F401
    except ImportError:
        note = "未安装 playwright，前端部分未动态验证（静态解析档继续）"
        return {"tier": tier, "controls": controls, "errors": errors, "note": note}

    base = base_url or os.environ.get("BASE_URL")
    proc = None
    try:
        if not base:
            port = _free_port()
            workdir = Path(tempfile.mkdtemp(prefix="ai_new_deadcode_"))
            env = dict(os.environ, AI_NEW_STUB="1", AI_NEW_DATA=str(workdir),
                       AI_NEW_PORT=str(port))
            proc = subprocess.Popen([sys.executable, str(ROOT / "agent_start.py")],
                                    cwd=str(ROOT), env=env,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            base = "http://127.0.0.1:%d" % port
            _wait_live(base, proc)

        import asyncio

        async def _collect():
            nonlocal controls, errors
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    executable_path=os.environ.get("CHROME", "/usr/local/bin/chromium"),
                    args=["--no-sandbox"])
                ctx = await browser.new_context(viewport={"width": 1100, "height": 1000})
                page = await ctx.new_page()
                page.on("pageerror", lambda e: errors.append(str(e)))
                await page.goto(base + "/manage.html", wait_until="load")
                await page.wait_for_timeout(1500)
                controls = await page.evaluate(
                    """() => [...document.querySelectorAll('[data-ctl],[data-act],[data-clk],button,[data-go]')]
                       .map(e => ({tag: e.tagName, ctl: e.dataset.ctl || '', act: e.dataset.act || '',
                                   clk: e.dataset.clk || '', go: e.dataset.go || '',
                                   text: (e.textContent || '').trim().slice(0, 20)}))""")
                await browser.close()
        asyncio.run(_collect())
        tier = "dynamic"
    except Exception as e:  # noqa: BLE001 — 装配期并发改动导致起不来时降级不判死
        note = "前端动态档启动失败，已降级静态解析：%s" % e
        if proc is not None and proc.poll() is None:
            proc.terminate()
    return {"tier": tier, "controls": controls, "errors": errors, "note": note}


def _free_port() -> int:
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_live(base: str, proc: subprocess.Popen, timeout: int = 15) -> None:
    import time
    import urllib.request
    for _ in range(timeout * 10):
        if proc.poll() is not None:
            out, err = proc.communicate(timeout=2)
            raise RuntimeError("桩进程退出：\n%s\n%s" % (out[-800:], err[-800:]))
        try:
            urllib.request.urlopen(base + "/api/health/live", timeout=2).read()
            return
        except Exception:  # noqa: BLE001
            time.sleep(0.1)
    raise RuntimeError("桩进程 %ds 内未报到" % timeout)


# ---------------------------------------------------------------- 入口

def main(argv: list[str] | None = None) -> int:
    argv = list(argv or sys.argv[1:])
    use_ui = "--ui" in argv or os.environ.get("DEADCODE_UI") == "1"
    as_json = "--json" in argv

    result = scan()
    if use_ui:
        fe = probe_frontend()
        result["tiers"]["frontend-dynamic"] = fe["tier"]
        if as_json:
            result["frontend"] = fe
        else:
            print("前端动态档：%s" % fe["tier"])
            if fe["note"]:
                print("  - " + fe["note"])
            if fe["errors"]:
                print("  - 页面 JS 异常：%s" % fe["errors"][:3])
            print("  - 真实渲染控件 %d 个" % len(fe["controls"]))

    if as_json:
        import json
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if not result["problems"] else 1

    s = result["stats"]
    print("死代码扫描：Python 文件 %d / 符号 %d，JS 文件 %d / 符号 %d，"
          "引用边 %d，命中 %d，耗时 %.1fms" % (
              s["py_files"], s["py_symbols"], s["js_files"], s["js_symbols"],
              s["reference_edges"], s["problems"], s["elapsed_ms"]))

    if result["problems"]:
        print("\n死代码门禁未通过：")
        for p in result["problems"]:
            print("  - " + format_problem(p))
        return 1
    print("死代码门禁通过：未发现定义后无引用的函数/方法/导入/注册项")
    return 0


if __name__ == "__main__":
    sys.exit(main())
