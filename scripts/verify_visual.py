#!/usr/bin/env python3
"""像素级视觉回归：固定视口截取核心视图，与仓库基线逐像素比对。

基线入库（scripts/visual_baseline/*.png）；统一用 Playwright 自带 Chromium/固定视口，阈值 2%。
更新基线必须显式 `--update` 并提交 PNG，避免“测试一红就改图”掩盖视觉退化。
"""
from __future__ import annotations

import argparse
import asyncio
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from PIL import Image, ImageChops
from playwright.async_api import async_playwright

HERE = Path(__file__).resolve().parent
BASE_DIR = HERE / "visual_baseline"
VIEWS = {
    "projects": "/manage.html?view=projects",
    "tickets": "/manage.html?view=tickets",
    "architecture": "/manage.html?view=architecture",
}
VIEWPORT = {"width": 1280, "height": 900}
MAX_DIFF_RATIO = 0.02
ROOT = HERE.parent
MODULES = ROOT / "ai_new" / "modules"
PORT = 8793


def _seed_data(root):
    """把各模块 data/ 平铺成 AI_NEW_DATA 外部根，得到无业务残留的固定首屏。"""
    for data in MODULES.glob("*/*/data"):
        if not data.is_dir():
            continue
        module = data.parent.relative_to(MODULES)
        shutil.copytree(data, root / module, dirs_exist_ok=True)
    return root


def start_server():
    root = Path(tempfile.mkdtemp(prefix="visual-data-"))
    _seed_data(root)
    env = dict(os.environ, AI_NEW_DATA=str(root), AI_NEW_STUB="1",
               AI_NEW_PORT=str(PORT))
    proc = subprocess.Popen([sys.executable, str(ROOT / "agent_start.py")],
                            cwd=str(ROOT), env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = "http://127.0.0.1:%d" % PORT
    for _ in range(60):
        try:
            urllib.request.urlopen(url + "/api/health/live", timeout=1).read()
            return proc, root, url
        except Exception:
            if proc.poll() is not None:
                break
            time.sleep(0.5)
    proc.terminate()
    raise RuntimeError("视觉回归独立服务启动失败")


async def shot(pg, url, path):
    await pg.goto(url, wait_until="load", timeout=60000)
    await pg.add_style_tag(content="""
      *,*::before,*::after{animation:none!important;transition:none!important;caret-color:transparent!important}
      .ts,.uptime,[data-dynamic]{visibility:hidden!important}
    """)
    await pg.wait_for_timeout(1200)
    await pg.screenshot(path=str(path), full_page=False)


def diff_ratio(a, b):
    ia, ib = Image.open(a).convert("RGB"), Image.open(b).convert("RGB")
    if ia.size != ib.size:
        return 1.0, "size %s != %s" % (ia.size, ib.size)
    box = ImageChops.difference(ia, ib).getbbox()
    if not box:
        return 0.0, ""
    changed = sum(1 for px in ImageChops.difference(ia, ib).convert("L").getdata() if px > 8)
    return changed / float(ia.size[0] * ia.size[1]), str(box)


async def run(update):
    explicit = os.environ.get("VISUAL_BASE")
    proc = root = None
    if explicit:
        base = explicit.rstrip("/")
    else:
        proc, root, base = start_server()
    BASE_DIR.mkdir(parents=True, exist_ok=True)
    fails = []
    try:
        await _compare(base, update, fails)
    finally:
        if proc is not None:
            proc.terminate()
            proc.wait(timeout=10)
        if root is not None:
            shutil.rmtree(root, ignore_errors=True)
    if fails:
        print("视觉回归失败 %d/%d（阈值 %.1f%%）" % (len(fails), len(VIEWS), MAX_DIFF_RATIO * 100))
        return 1
    print("视觉回归全绿 %d/%d" % (len(VIEWS), len(VIEWS)))
    return 0


async def _compare(base, update, fails):
    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path=os.environ.get("CHROME") or None,
                                    args=["--no-sandbox", "--force-device-scale-factor=1"])
        page = await (await b.new_context(viewport=VIEWPORT)).new_page()
        for name, path in VIEWS.items():
            target = BASE_DIR / (name + ".png")
            actual = Path("/tmp") / ("visual-%s.png" % name)
            await shot(page, base + path, actual)
            if update or not target.exists():
                shutil.copyfile(actual, target)
                print("  BASE %-12s %s" % (name, target))
                continue
            ratio, box = diff_ratio(target, actual)
            if ratio > MAX_DIFF_RATIO:
                fails.append((name, ratio, box))
                print("  FAIL %-12s diff=%.3f%% box=%s" % (name, ratio * 100, box))
            else:
                print("  OK   %-12s diff=%.3f%%" % (name, ratio * 100))
        await b.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--update", action="store_true", help="重写基线（需连同 PNG 一起提交）")
    args = ap.parse_args()
    return asyncio.run(run(args.update))


if __name__ == "__main__":
    raise SystemExit(main())
