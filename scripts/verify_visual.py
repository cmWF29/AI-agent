#!/usr/bin/env python3
"""像素级视觉回归：固定视口截取核心视图，与仓库基线逐像素比对。

基线入库（scripts/visual_baseline/*.png）；CI 用同一 Chromium/视口跑，阈值 0.3%。
更新基线必须显式 `--update` 并提交 PNG，避免“测试一红就改图”掩盖视觉退化。
"""
from __future__ import annotations

import argparse
import asyncio
import os
import shutil
import sys
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
MAX_DIFF_RATIO = 0.003


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
    base = os.environ.get("VISUAL_BASE", "http://127.0.0.1:8787").rstrip("/")
    BASE_DIR.mkdir(parents=True, exist_ok=True)
    fails = []
    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path=os.environ.get("CHROME", "/usr/local/bin/chromium"),
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
    if fails:
        print("视觉回归失败 %d/%d（阈值 %.1f%%）" % (len(fails), len(VIEWS), MAX_DIFF_RATIO * 100))
        return 1
    print("视觉回归全绿 %d/%d" % (len(VIEWS), len(VIEWS)))
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--update", action="store_true", help="重写基线（需连同 PNG 一起提交）")
    args = ap.parse_args()
    return asyncio.run(run(args.update))


if __name__ == "__main__":
    raise SystemExit(main())
