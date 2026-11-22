#!/usr/bin/env python3
"""可点位置清点：逐页打开控制台，数出所有真正可点的元素，并检查每个都有控件 id。

回答的是"页面上到底有多少按钮"，不是"有几种按钮"：
  - total   ：当前页可点元素个数（button / data-act / data-clk / summary / details）
  - ctl     ：其中带 data-ctl（进了状态机）的个数
  - no_ctl  ：没有控件 id 的可点元素（门禁失败项，逐条打印选择器与文本）
用法：python3 scripts/inventory_ui.py [base_url]
"""
import asyncio
import os
import re
import sys

from playwright.async_api import async_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8787"
CHROME = os.environ.get("CHROME", "/usr/local/bin/chromium")
PAGES = ["projects", "project&project=%s" % os.environ.get("P", "验收项目"), "positions",
         "position&position=architect", "skills", "tools", "user", "ops", "arch",
         "click-machine", "traces", "knowledge", "logs", "artifacts"]


async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])
        c = await b.new_context(viewport={"width": 430, "height": 900})
        pg = await c.new_page()
        total = ctl = 0
        bad = []
        for q in PAGES:
            await pg.goto("%s/manage.html?view=%s" % (BASE, q), wait_until="load")
            await pg.wait_for_timeout(1200)
            row = await pg.evaluate("""() => {
              const sel = 'button,[data-act],[data-clk],[data-cube],summary,details.tool-call';
              const els = [...document.querySelectorAll(sel)].filter((e) => {
                if (e.closest('[hidden]')) return false;
                const r = e.getBoundingClientRect();
                return r.width > 0 && r.height > 0;
              });
              return {total: els.length,
                      ctl: els.filter((e) => e.dataset && e.dataset.ctl).length,
                      no: els.filter((e) => !(e.dataset && e.dataset.ctl))
                        .map((e) => '#' + (e.id || e.tagName) + ':' + (e.textContent || '').trim().slice(0, 12)).slice(0, 8)};
            }""")
            total += row["total"]; ctl += row["ctl"]
            print("  %-28s 可点 %3d 有控件id %3d 缺 %2d" % (q, row["total"], row["ctl"], len(row["no"])))
            if row["no"]:
                bad.append((q, row["no"]))
        print("合计：可点元素 %d，其中进状态机 %d" % (total, ctl))
        await b.close()
        if bad:
            print("没有控件 id 的可点元素（必须补 data-ctl 或在 controls 登记）：")
            for q, items in bad:
                print("  %s -> %s" % (q, items))
            return 1
        return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
