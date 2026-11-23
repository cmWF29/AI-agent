#!/usr/bin/env python3
"""运维页复核：桌面 1440 / 移动 390 双视口截图 + 展示断言。

复核口径（只动 console 运维页相关文件；本脚本是验收驱动，不改业务源码）：
- 节点归属角色（入口 / 执行）、项目归属、备份状态、脱敏地址展示正常；
- 脱敏视图不含真实内网 IP / 端口；
- ``pageerror = 0``，页面无横向溢出（scrollWidth 不超过 clientWidth）。

用法：
    python3 scripts/verify_ops_page.py [base_url] [--shots DIR]

默认 ``http://127.0.0.1:8787``；截图写到 ``console-acceptance/round4/``。
任一断言失败退出码非 0。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SHOTS = ROOT.parent / "console-acceptance" / "round4"

IP_RE = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")
PORT_RE = re.compile(r":\d{4,5}\b")

SEED_NODES = [
    {"id": "entry-1", "endpoint": "https://10.0.0.8:8443", "role": "entry",
     "public_exposed": True, "transport": "direct",
     "capacity": {"cpu": 4, "memory_mb": 4096}},
    {"id": "exec-1", "endpoint": "http://10.0.0.5:8790", "role": "executor",
     "public_exposed": False, "transport": "direct",
     "capacity": {"cpu": 2, "memory_mb": 2048}},
]
SEED_PROJECT = "demo-proj"


def rpc(base, route, payload):
    req = urllib.request.Request(
        base + "/api/rpc/" + route.replace(".", "/"),
        data=json.dumps(payload or {}).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=5) as resp:
        resp.read()


def seed(base):
    """播种两个节点 + 一个归属 + 一条备份台账（桩内存态，不落源码树）。"""
    for node in SEED_NODES:
        rpc(base, "nodes.register", node)
    rpc(base, "nodes.acquire", {"project": SEED_PROJECT, "node": "exec-1",
                                "tier": "weak"})
    rpc(base, "nodes.backup_record", {"project": SEED_PROJECT,
        "snapshot": {"snapshot_id": "snap-demo", "created_at": 1795414800.0,
                     "state": "verified", "entries": ["tickets/demo.yaml"]}})


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("base", nargs="?", default="http://127.0.0.1:8787")
    ap.add_argument("--shots", default=str(DEFAULT_SHOTS))
    ap.add_argument("--keep-seed", action="store_true",
                    help="播种后不清空（默认仅本次会话有效）")
    args = ap.parse_args(argv)
    base = args.base.rstrip("/")
    shots = Path(args.shots)
    shots.mkdir(parents=True, exist_ok=True)

    seed(base)

    from playwright.async_api import async_playwright

    fails = []
    viewports = [("desktop-1440", 1440, 1000), ("mobile-390", 390, 844)]
    report = {"base": base, "viewports": []}

    import asyncio

    async def run():
        nonlocal fails
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                executable_path="/usr/local/bin/chromium", args=["--no-sandbox"])
            for label, width, height in viewports:
                ctx = await browser.new_context(viewport={"width": width,
                                                          "height": height})
                pg = await ctx.new_page()
                errors = []
                pg.on("pageerror", lambda e: errors.append(str(e)))
                await pg.goto(base + "/manage.html?view=ops", wait_until="load")
                await pg.wait_for_selector("#ops-insight [data-role='nodes']",
                                          timeout=4000)
                await pg.wait_for_timeout(800)

                metrics = await pg.evaluate("""() => {
                  const root = document.getElementById('ops-insight');
                  const body = document.getElementById('view-body');
                  return {
                    text: root ? root.innerText : '',
                    scrollW: document.documentElement.scrollWidth,
                    clientW: document.documentElement.clientWidth,
                    bodyScrollW: body ? body.scrollWidth : 0,
                    bodyClientW: body ? body.clientWidth : 0,
                    hasEntry: /入口/.test(root ? root.innerText : ''),
                    hasExecutor: /执行/.test(root ? root.innerText : ''),
                    hasProject: /demo-proj/.test(root ? root.innerText : ''),
                    hasBackup: /verified|已备份|备份/.test(root ? root.innerText : ''),
                    masked: (root ? root.innerText : '').includes('***')
                  };
                }""")

                ip_leaks = IP_RE.findall(metrics["text"])
                port_leaks = PORT_RE.findall(metrics["text"])
                overflow = metrics["scrollW"] > metrics["clientW"] + 1
                body_overflow = metrics["bodyScrollW"] > metrics["bodyClientW"] + 1

                checks = {
                    "pageerror=0": len(errors) == 0,
                    "无横向溢出": not overflow and not body_overflow,
                    "展示入口角色": metrics["hasEntry"],
                    "展示执行角色": metrics["hasExecutor"],
                    "展示项目归属": metrics["hasProject"],
                    "展示备份状态": metrics["hasBackup"],
                    "脱敏地址展示": metrics["masked"],
                    "无真实 IP 泄漏": not ip_leaks,
                    "无真实端口泄漏": not port_leaks,
                }
                for name, ok in checks.items():
                    if not ok:
                        fails.append("%s · %s" % (label, name))

                shot = shots / ("ops-%s.png" % label)
                await pg.screenshot(path=str(shot), full_page=True)
                report["viewports"].append({
                    "viewport": label, "width": width, "height": height,
                    "checks": checks, "pageerrors": errors,
                    "scrollWidth": metrics["scrollW"],
                    "clientWidth": metrics["clientW"],
                    "ip_leaks": ip_leaks, "port_leaks": port_leaks,
                    "screenshot": str(shot),
                })
                await ctx.close()
            await browser.close()

    asyncio.run(run())

    print(json.dumps(report, ensure_ascii=False, indent=2))
    if fails:
        print("\n运维页复核未通过：%d 项" % len(fails))
        for f in fails:
            print("  - " + f)
        return 1
    print("\n运维页复核全部通过（1440 / 390）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
