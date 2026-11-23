"""render.js 分栏回归：有 lane 区块时，没有 lane 的区块不能被丢掉。

跑法：CHROME=/usr/local/bin/chromium python3 scripts/test_render_lane.py
做法：把 render.js 原文注入一个空页面，直接调纯函数 groupSections / composeBody，
      断言 single 区块在三个边界（有 lane / 全无 lane / 全 lane）下都被保留且顺序稳定。
"""
from __future__ import annotations
import os
import sys

from playwright.async_api import async_playwright

ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "ai_new", "modules", "agent", "web", "data", "console")
CHROME = os.environ.get("CHROME", "/usr/local/bin/chromium")
FAILS = []


def check(name, ok, detail=""):
    print(("  OK  " if ok else "  FAIL") + " " + name + ((" · " + str(detail)) if detail and not ok else ""))
    if not ok:
        FAILS.append(name + (" · " + str(detail) if detail else ""))


def src(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as f:
        return f.read()


async def main():
    js = src("render.js")
    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])
        pg = await b.new_page()
        errors = []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        await pg.set_content("<!doctype html><html><body></body></html>")
        await pg.add_script_tag(content=js)

        # 1) 混合：一个 left + 一个无 lane + 一个 right
        g = await pg.evaluate("() => groupSections([{lane:'left',k:'L'},{k:'S1'},{lane:'right',k:'R'},{k:'S2'}])")
        check("混合时无 lane 区块归 single", [i["sec"]["k"] for i in g["single"]] == ["S1", "S2"], g)
        check("lane 区块归位", [i["sec"]["k"] for i in g["left"]] == ["L"]
              and [i["sec"]["k"] for i in g["right"]] == ["R"], g)
        check("索引保留原序位", [i["i"] for i in g["single"]] == [1, 3], g)

        body = await pg.evaluate("""() => composeBody({
            single:['<p>S1</p>','<p>S2</p>'],
            left:['<p>L</p>'], right:['<p>R</p>']})""")
        check("拼装后 single 仍在", "<p>S1</p>" in body and "<p>S2</p>" in body, body[:120])
        check("拼装后三路都在", "<p>L</p>" in body and "<p>R</p>" in body, body[:120])
        check("single 排在双列之前", body.find("<p>S1</p>") < body.find("ticket-grid"), body[:120])

        # 2) 全无 lane：纯 single，不产生空网格
        body2 = await pg.evaluate("""() => {
            const g = groupSections([{k:'A'},{k:'B'}]);
            return composeBody({single: g.single.map((it) => '<p>' + it.sec.k + '</p>'), left: [], right: []});
        }""")
        check("全无 lane 不出现空网格", "ticket-grid" not in body2 and "<p>A</p>" in body2, body2[:120])

        # 3) 全 lane：单侧时 solo（另一列不占位）
        body3 = await pg.evaluate("""() => composeBody({single:[], left:['<p>L</p>'], right:[]})""")
        check("单侧有内容走 solo", "solo" in body3 and "lane-right" not in body3, body3[:160])

        # 4) 真实页面不报错（秘书页/项目详情用到了 lane）
        check("注入 render.js 无 JS 异常", not errors, errors[:3])
        await b.close()
    if FAILS:
        print("render 分栏回归：%d 项失败" % len(FAILS))
        sys.exit(1)
    print("render 分栏回归：全部通过")


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
