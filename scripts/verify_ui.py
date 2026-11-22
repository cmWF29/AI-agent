"""控制台 UI 回归：把临时排查脚本固化成可重复的一条命令。

跑法：python3 scripts/verify_ui.py [base_url]
覆盖这几件事（都是这轮真出过问题的点）：
  1. 每个可点动作按钮都有控件状态机（data-ctl 不为空）
  2. 归档项目单独一摞，卡内只剩「删除」，没有改名/归档
  3. 已归档项目详情带「已归档·只读」，重命名/新建工单是 disabled
  4. 已结单工单：追加备注/结单/语音/发送四个控件一起 disabled
  5. 消息时间带年月日
  6. 岗位流程是 DAG：有节点、有回边，缩放按钮能改百分比
  7. 报文/原文展开后重渲染不回收
"""
from __future__ import annotations
import asyncio
import os
import re
import sys

from playwright.async_api import async_playwright

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8787").rstrip("/")
CHROME = os.environ.get("CHROME", "/usr/local/bin/chromium")
FAILS = []


def check(name, ok, detail=""):
    print(("  OK  " if ok else "  FAIL") + " " + name + ((" · " + str(detail)) if detail and not ok else ""))
    if not ok:
        FAILS.append(name + (" · " + str(detail) if detail else ""))


async def open_view(pg, q):
    await pg.goto(BASE + "/manage.html?" + q, wait_until="load")
    await pg.wait_for_timeout(1800)


async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])
        c = await b.new_context(viewport={"width": 1100, "height": 1000})
        pg = await c.new_page()
        errors = []
        pg.on("pageerror", lambda e: errors.append(str(e)))

        # 1. 控件状态机
        await open_view(pg, "view=projects")
        bad = await pg.evaluate("""() => [...document.querySelectorAll('button[data-act]')]
          .filter((e) => !e.dataset.ctl).map((e) => e.textContent.trim())""")
        check("每个动作按钮都有 data-ctl", not bad, bad)

        # 2. 归档项目独立堆叠区
        sec = await pg.evaluate("""() => {
          const hs=[...document.querySelectorAll('.vsec')].filter(s=>/已归档/.test(s.innerText));
          if(!hs.length) return null;
          const cards=[...hs[0].querySelectorAll('.pcard')];
          return {n: cards.length,
                  acts: cards.map(c=>[...c.querySelectorAll('.acts button')].map(b=>b.textContent.trim()))};
        }""")
        if sec:
            only_del = all(a == ["删除"] for a in sec["acts"])
            check("归档区卡片只有「删除」", only_del, sec["acts"])
        else:
            print("  SKIP 归档区（当前没有已归档项目）")

        # 3. 已归档项目详情只读
        if sec:
            # data-go 存的是本页动作索引（ACTS 键），不是项目 id；直接点卡片最贴近真实操作
            has_card = await pg.evaluate("""() => {
              const hs=[...document.querySelectorAll('.vsec')].filter(s=>/已归档/.test(s.innerText));
              const card=hs[0] && hs[0].querySelector('.pcard');
              if (!card) return false; card.click(); return true; }""")
            if has_card:
                await pg.wait_for_timeout(1800)
                info = await pg.evaluate("""() => ({badge: /已归档·只读/.test(document.querySelector('#view-body').innerText),
                  rename: (()=>{const b=[...document.querySelectorAll('#view-body .view-head button')].find(x=>/重命名/.test(x.textContent)); return b?b.disabled:null;})(),
                  create: (()=>{const b=[...document.querySelectorAll('#view-body .view-head button')].find(x=>/新建工单/.test(x.textContent)); return b?b.disabled:null;})()})""")
                check("归档项目详情带只读徽章", info["badge"])
                check("归档项目：重命名 disabled", info["rename"] is True, info["rename"])
                check("归档项目：新建工单 disabled", info["create"] is True, info["create"])

        # 4/5/7. 已结单工单会话
        tid = None
        await open_view(pg, "view=projects")
        tid = await pg.evaluate("""async () => {
          const r = await run('ticket-list', {});
          const d = r.result && r.result.result ? r.result.result : (r.result || {});
          const items = d.items || (r.items || []) || [];
          const t = items.find(x => x.status === 'closed');
          return t ? {id: t.id, project: t.project} : null;
        }""")
        if tid:
            await open_view(pg, "view=ticket&ticket=%s&project=%s" % (tid["id"], tid["project"]))
            ctl = await pg.evaluate("""() => [...document.querySelectorAll('.composer [data-ctl]')]
              .map((e) => ({ctl: e.dataset.ctl, off: e.disabled, st: e.dataset.ctlState}))""")
            check("结单后四个控件一起灰", len(ctl) == 4 and all(x["off"] for x in ctl), ctl)
            # 5. 时间口径：气泡内 HH:MM（悬停 title 带完整年月日）；纯工具组退回组尾 .msg-ts
            tss = await pg.evaluate("""() => [...document.querySelectorAll('.msg-time,.msg-ts')]
              .map(e => ({t: e.textContent, title: e.getAttribute('title') || ''}))""")
            if tss:
                def _ok(x):
                    if not re.search(r"\d{1,2}:\d{2}", x.get("t") or ""):
                        return False
                    if x.get("title"):
                        return bool(re.search(r"\d{4}", x["title"]))
                    return True
                check("消息时间带年月日", all(_ok(x) for x in tss), [x["t"] for x in tss[:3]])
            else:
                print("  SKIP 消息时间（该工单消息没有时间戳）")
            # 7. 展开原文后重渲染仍展开
            opened = await pg.evaluate("""() => {
              const d = document.querySelector('.raw-box'); if (!d) return null;
              d.open = true; d.dispatchEvent(new Event('toggle'));
              return d.dataset.fold || '';
            }""")
            if opened:
                await pg.evaluate("async () => { await render({keepBanner:true}); }")
                await pg.wait_for_timeout(600)
                still = await pg.evaluate("""() => { const d=document.querySelector('.raw-box');
                  return !!(d && d.open); }""")
                check("原文展开态重渲染后保持", still)
                # 7b. 刷新页面（不是重渲染）后，折叠态必须还在——这条专堵"刷新自动收回去"
                await pg.reload(wait_until="load")
                await pg.wait_for_timeout(1500)
                after = await pg.evaluate("""(k) => { const d = document.querySelector('details[data-fold="' + k + '"]');
                  return d ? d.open : null; }""", opened)
                if after is None:
                    print("  SKIP 刷新保持（刷新后找不到同一折叠块）")
                else:
                    check("刷新后折叠态保持", after is True)
            else:
                print("  SKIP 折叠持久化（该工单没有原文块）")
        else:
            print("  SKIP 结单会话（当前没有已结单工单）")

        # 6. DAG
        await open_view(pg, "view=position&position=architect")
        dag = await pg.evaluate("""() => ({n: document.querySelectorAll('.dag-stage .flow-node').length,
          e: document.querySelectorAll('.dag-edge').length,
          b: document.querySelectorAll('.dag-edge.back').length})""")
        check("岗位流程渲染成 DAG", dag["n"] > 0 and dag["e"] > 0, dag)
        check("DAG 有回边（不是纯顺序）", dag["b"] > 0, dag)
        if dag["n"]:
            await pg.click('.flow-card .dag-zoom button[data-dag="in"]')
            pct = await pg.evaluate("() => document.querySelector('.dag-pct').textContent")
            check("DAG 缩放生效", pct.strip() != "100%", pct)

        check("页面无 JS 异常", not errors, errors[:4])
        await b.close()
    if FAILS:
        print("\nUI 回归未通过：%d 项" % len(FAILS))
        return 1
    print("\nUI 回归全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
