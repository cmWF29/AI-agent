"""浏览器业务 E2E：真页面 → 真后端 → 真浏览器。

覆盖两条最短但关键的业务闭环：
  project：新建项目 → 列表出现 → 清理；
  ticket ：新建项目 → 新建工单 → 发消息 → 岗位派发/模型回复 → 状态回 idle → 清理。

不是截图冒烟：每一步都点真实 DOM、走真实 RPC，失败直接非零退出。
"""
from __future__ import annotations
import argparse, asyncio, os, sys, time
from playwright.async_api import async_playwright

BASE = "http://127.0.0.1:8787"
CHROME = os.environ.get("CHROME", "/usr/local/bin/chromium")


async def new_page(b):
    c = await b.new_context(viewport={"width": 1100, "height": 1000}, ignore_https_errors=True)
    token = os.environ.get("HIVE_TOKEN", "")
    if token:
        await c.add_cookies([{"name": "hive_token", "value": token,
                              "domain": "127.0.0.1", "path": "/"}])
    return c, await c.new_page()


async def open_projects(pg):
    await pg.goto(BASE + "/manage.html?view=projects", wait_until="load", timeout=60000)
    await pg.wait_for_selector("#view-body .view-head", timeout=30000)


async def create_project(pg, name):
    await open_projects(pg)
    btn = pg.locator("#view-body .view-head sl-button", has_text="新建项目").first
    await btn.wait_for(state="visible", timeout=10000)
    await btn.click()
    await pg.wait_for_timeout(400)
    state = await pg.evaluate("""() => {
      const d=document.querySelector('#modal');
      return {open:!!(d&&d.open), fields:document.querySelectorAll('#modal-form sl-input').length};
    }""")
    if not (state["open"] and state["fields"] >= 1):
        raise AssertionError("新建项目弹窗未打开: %s" % state)
    await pg.evaluate("""name => {
      const el=document.querySelector('#modal-form sl-input');
      el.value=name; el.dispatchEvent(new Event('sl-input', {bubbles:true}));
      document.querySelector('#modal-ok').click();
    }""", name)
    await pg.wait_for_function(
        """name => document.querySelector('#view-body')?.innerText.includes(name)""",
        arg=name, timeout=20000)


async def open_project(pg, name):
    clicked = await pg.evaluate("""name => {
      const c=[...document.querySelectorAll('#view-body .pcard')].find(x=>x.innerText.includes(name));
      if(!c) return false; c.click(); return true;
    }""", name)
    if not clicked:
        raise AssertionError("项目卡未找到: %s" % name)
    await pg.wait_for_timeout(1200)
    await pg.wait_for_selector("#view-body .view-head", timeout=20000)


async def create_ticket(pg, title, goal):
    await pg.locator("#view-body .view-head sl-button", has_text="新建工单").first.click()
    await pg.wait_for_timeout(400)
    state = await pg.evaluate("""() => {
      const d=document.querySelector('#modal');
      return {open:!!(d&&d.open), label:(d&&d.label)||''};
    }""")
    if not state["open"] or state["label"] != "新建工单":
        raise AssertionError("新建工单弹窗未打开: %s" % state)
    await pg.evaluate("""p => {
      const t=document.querySelector('#modal-form sl-input[name=title]'); t.value=p.title;
      const g=document.querySelector('#modal-form sl-textarea[name=goal]'); g.value=p.goal;
      document.querySelector('#modal-ok').click();
    }""", {"title": title, "goal": goal})
    await pg.wait_for_selector("#view-body .composer textarea", timeout=20000)
    return await pg.evaluate("() => new URLSearchParams(location.search).get('ticket')")


async def send_and_wait(pg, tid, text):
    before = await pg.evaluate("""async id => {
      const r=await run('ticket-thread',{id}); return (r.thread.messages||[]).length;
    }""", tid)
    await pg.evaluate("""text => {
      const ta=document.querySelector('#view-body .composer textarea');
      ta.value=text; ta.dispatchEvent(new Event('input', {bubbles:true}));
      const b=[...document.querySelectorAll('.composer-actions sl-button')]
        .find(x=>x.textContent.includes('发送'));
      b.click();
    }""", text)
    last = {}
    for _ in range(60):
        await pg.wait_for_timeout(1000)
        last = await pg.evaluate("""async id => {
          const r=await run('ticket-thread',{id});
          const msgs=r.thread.messages||[];
          return {n:msgs.length, status:r.thread.status,
                  roles:(r.members||[]).length,
                  answered:msgs.some(m=>m.role==='assistant' && (m.content||'').trim())};
        }""", tid)
        if last.get("n", 0) > before and last.get("status") == "idle" and last.get("answered"):
            return before, last
    raise AssertionError("发消息后未在 60s 内收口: %s" % last)


async def cleanup(pg, name):
    return await pg.evaluate("""async name => {
      const r=await run('project-tree',{});
      const items=r.items||[];
      const n=items.find(x=>((x.project||{}).name)===name);
      if(!n) return false;
      await run('projects-delete',{id:n.project.id,purge:true});
      return true;
    }""", name)


async def scenario_project(pg):
    name = "e2e-project-%d" % int(time.time())
    try:
        await create_project(pg, name)
        return {"name": name, "created": True}
    finally:
        await cleanup(pg, name)


async def scenario_ticket(pg):
    name = "e2e-ticket-%d" % int(time.time())
    try:
        await create_project(pg, name)
        await open_project(pg, name)
        tid = await create_ticket(pg, "E2E 工单", "验证建单→发消息→岗位接收→模型回复闭环")
        if not tid:
            raise AssertionError("建单后地址里没有 ticket 参数")
        before, after = await send_and_wait(pg, tid, "请给出这次工单的三步执行计划")
        if after["roles"] < 1:
            raise AssertionError("发消息后没有 PM 会话成员: %s" % after)
        return {"name": name, "ticket": tid, "before": before, "after": after}
    finally:
        await cleanup(pg, name)


async def main() -> int:
    global BASE
    ap = argparse.ArgumentParser()
    ap.add_argument("base", nargs="?", default=BASE)
    ap.add_argument("--scenario", choices=("project", "ticket", "all"), default="all")
    args = ap.parse_args()
    BASE = args.base.rstrip("/")
    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])
        c, pg = await new_page(b)
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        try:
            if args.scenario in ("project", "all"):
                out = await scenario_project(pg)
                print("  OK  项目 E2E：新建项目→列表出现→清理 %s" % out["name"])
            if args.scenario in ("ticket", "all"):
                out = await scenario_ticket(pg)
                print("  OK  工单 E2E：建单→发消息→PM 回复→回 idle→清理 %s %s（消息 %s→%s，会话成员 %s）"
                      % (out["name"], out["ticket"], out["before"], out["after"]["n"],
                         out["after"]["roles"]))
            if errs:
                print("  FAIL 页面 JS 异常: %s" % errs)
                return 1
            return 0
        except Exception as exc:
            print("  FAIL %s" % exc)
            if errs:
                print("  FAIL 页面 JS 异常: %s" % errs)
            return 1
        finally:
            await b.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
