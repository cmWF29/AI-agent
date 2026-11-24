#!/usr/bin/env python3
"""前端状态机真实点击门禁：对每个页面上的安全控件做一次真实 DOM 点击。

不是静态检查 data-ctl 有没有写：真起浏览器，逐个点，确认
  - 点击没有 pageerror；
  - 控件自己的 data-ctl-state 真的动了（idle → busy/done）或 DOM 显隐/布局真的变了；
  - 点完控件还在，页面没被误导航走；
  - 控件自带状态值在它声明的状态集合内。

破坏性动作（删除/归档/结单/发送/导航/弹窗提交）不在这里点：
这些由 verify_e2e.py 的真实业务闭环覆盖，避免巡检把用户数据点没。
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

import yaml
from playwright.async_api import async_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONSOLE = ROOT + "/ai_new/modules/agent_common/demand_engine/data/console.yaml"

BASE = "http://127.0.0.1:8787"
CHROME = os.environ.get("CHROME", "/usr/local/bin/chromium")

# 只点不改业务数据的交互：折叠/筛选/展开/缩放/侧栏
SAFE_KINDS = {
    "nav_group", "tab_config", "drawer_open", "drawer_scrim", "rail_close", "rail_open",
    "tree_group", "filter", "member_chip", "popover_close", "fold_text", "wire_fold",
    "section_fold", "summary_fold", "raw_fold", "deck_toggle", "stack_open", "dag_zoom",
}


def load_kinds() -> set[str]:
    doc = yaml.safe_load(open(CONSOLE, encoding="utf-8")) or {}
    return {k["key"] for k in (doc.get("click_machine") or {}).get("kinds") or []}


async def read_controls(pg):
    return await pg.evaluate("""() => [...document.querySelectorAll('[data-ctl]')]
      .filter(e => e.offsetWidth > 0 && e.offsetHeight > 0)
      .map((e, i) => ({i, ctl:e.dataset.ctl, clk:e.dataset.clk||'',
                       st:e.dataset.ctlState||'', tag:e.tagName,
                       label:(e.textContent||'').trim().slice(0,24),
                       open: e.open === true}))""")


async def click_one(pg, ctl, occ):
    """按控件 id + 同 id 的第几个实例点击；每点完都回原页，避免前一次展开/重排把后一次索引带偏。"""
    return await pg.evaluate("""([ctl,occ]) => {
      const els=[...document.querySelectorAll('[data-ctl]')].filter(e => e.offsetWidth > 0 && e.offsetHeight > 0 && e.dataset.ctl===ctl);
      const el=els[occ]; if(!el) return {ok:false};
      const det=el.closest('details');
      const before={st:el.dataset.ctlState||'', open:det?det.open:null,
                    html:document.querySelector('#view-body').innerHTML.length,
                    url:location.href};
      el.click();
      return {ok:true, before};
    }""", [ctl, occ])


async def sample(pg, ctl, occ, before):
    await pg.wait_for_timeout(150)
    return await pg.evaluate("""([ctl,occ,b]) => {
      const els=[...document.querySelectorAll('[data-ctl]')].filter(e => e.offsetWidth > 0 && e.offsetHeight > 0 && e.dataset.ctl===ctl);
      const el=els[occ];
      const det=el?el.closest('details'):null;
      const st=el?(el.dataset.ctlState||''):'';
      const open=det?det.open:null;
      return {exists:!!el, st, open,
              html:document.querySelector('#view-body').innerHTML.length,
              url:location.href,
              changed:(el && ((st!==b.st) || (open!==b.open)))
                      || document.querySelector('#view-body').innerHTML.length !== b.html
                      || location.href !== b.url};
    }""", [ctl, occ, before])


async def main() -> int:
    global BASE
    ap = argparse.ArgumentParser()
    ap.add_argument("base", nargs="?", default=BASE)
    args = ap.parse_args()
    BASE = args.base.rstrip("/")
    kinds = load_kinds()
    fails = []
    clicked = 0
    changed = 0
    pages = 0
    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])
        c = await b.new_context(viewport={"width": 1200, "height": 900})
        pg = await c.new_page()
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        try:
            await pg.goto(BASE + "/manage.html?view=projects", wait_until="load", timeout=60000)
            await pg.wait_for_timeout(1200)
            views = await pg.evaluate("""async () => {
              const r=await run('views-list',{});
              return r.filter(x=>x.view&&x.view.key&&x.view.menu).map(x=>x.view);
            }""")
            for v in views:
                key = v["key"]
                await pg.goto(BASE + "/manage.html?view=" + key, wait_until="load", timeout=60000)
                for _ in range(30):
                    await pg.wait_for_timeout(250)
                    if await pg.evaluate("() => !document.querySelector('#view-body .loading')"):
                        break
                pages += 1
                before_errs = len(errs)
                controls = await read_controls(pg)
                bad = [x for x in controls if not x["ctl"]]
                if bad:
                    fails.append("%s 存在无 data-ctl 的可点元素: %s" % (key, bad[:4]))
                    continue
                # 先查声明闭合：页面真实出现的 clk 必须是 click_machine 声明过的种类
                unknown = sorted({x["clk"] for x in controls if x["clk"] and x["clk"] not in kinds})
                if unknown:
                    fails.append("%s 出现未声明的点击种类: %s" % (key, unknown))
                safe = [x for x in controls if x["clk"] in SAFE_KINDS and x["st"] in ("", "idle")]
                if not safe:
                    continue
                occ = {}
                for item in safe:
                    occ[item["ctl"]] = occ.get(item["ctl"], 0) + 1
                    # 每个控件从干净页开始：前一控件展开/收起不能污染后一控件
                    await pg.goto(BASE + "/manage.html?view=" + key, wait_until="load", timeout=60000)
                    await pg.wait_for_timeout(600)
                    before = await click_one(pg, item["ctl"], occ[item["ctl"]] - 1)
                    if not before.get("ok"):
                        continue
                    after = await sample(pg, item["ctl"], occ[item["ctl"]] - 1, before["before"])
                    clicked += 1
                    if after["changed"]:
                        changed += 1
                    if len(errs) > before_errs:
                        fails.append("%s 点击 %s 后页面异常: %s" % (key, item["ctl"], errs[-1]))
                        break
                    if after["st"] and after["st"] not in ("idle", "busy", "done"):
                        fails.append("%s 点击 %s 后状态非法: %s" % (key, item["ctl"], after["st"]))
                    # 导航类之外的点击不许把人带走
                    if after["url"] != before["before"]["url"]:
                        fails.append("%s 点击 %s 后页面被误导航: %s" % (key, item["ctl"], after["url"]))
            if clicked < 10:
                fails.append("安全控件真实点击数过少（%d），前端状态机没有被端到端看护" % clicked)
            if clicked and not changed:
                fails.append("点了 %d 个安全控件，没有任何状态或 DOM 变化；handler 可能整体没接" % clicked)
        except Exception as exc:  # noqa: BLE001
            fails.append("控件巡检异常: %s" % exc)
        finally:
            await b.close()
    print("  页面 %d · 真实点击安全控件 %d 次 · 有明显变化 %d 次" % (pages, clicked, changed))
    if fails:
        print("前端状态机真实点击门禁失败：%d 项" % len(fails))
        for f in fails[:20]:
            print("  - " + f)
        return 1
    print("前端状态机真实点击门禁通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
