"""浏览器业务 E2E：真页面 → 真后端 → 真浏览器。

覆盖两条完整业务闭环，不是截图冒烟：
  project：新建项目 → 改名 → 归档 → 删除；
  ticket ：新建项目 → 新建工单 → 发消息 → PM 回复 → 结单 → 项目归档 → 删除。

每一步都点真实 DOM、走真实 RPC；列表出现/状态迁移/只读回收都要看到，
失败直接非零退出。所有夹具在 finally 清理，不往用户数据里留垃圾。
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
    await pg.wait_for_function(
        "() => document.querySelectorAll('#view-body .pcard').length > 0", timeout=20000)


async def card_exists(pg, name):
    return await pg.evaluate(
        "n => [...document.querySelectorAll('#view-body .pcard')].some(c => c.innerText.includes(n))",
        name)


async def wait_card(pg, name, timeout=20000):
    try:
        await pg.wait_for_function(
            "n => [...document.querySelectorAll('#view-body .pcard')].some(c => c.innerText.includes(n))",
            arg=name, timeout=timeout)
    except Exception:
        raise AssertionError("项目卡未出现: %s" % name)


async def click_card_action(pg, name, label):
    return await pg.evaluate("""([name,label]) => {
      const c=[...document.querySelectorAll('#view-body .pcard')].find(x=>x.innerText.includes(name));
      if(!c) return false;
      const b=[...c.querySelectorAll('.acts sl-button')].find(x=>x.textContent.trim()===label);
      if(!b || b.disabled) return false;
      b.click(); return true;
    }""", [name, label])


async def create_project(pg, name):
    await open_projects(pg)
    await pg.locator("#view-body .view-head sl-button", has_text="新建项目").first.click()
    await pg.wait_for_timeout(300)
    state = await pg.evaluate("""() => {
      const d=document.querySelector('#modal');
      return {open:!!(d&&d.open), label:(d&&d.label)||'',
              fields:document.querySelectorAll('#modal-form [name]').length};
    }""")
    if not (state["open"] and state["label"] == "新建项目" and state["fields"] >= 1):
        raise AssertionError("新建项目弹窗未打开: %s" % state)
    await pg.evaluate("""name => {
      const el=document.querySelector('#modal-form [name=name]');
      el.value=name; el.dispatchEvent(new Event('input',{bubbles:true})); el.dispatchEvent(new Event('sl-input', {bubbles:true}));
      document.querySelector('#modal-ok').click();
    }""", name)
    await wait_card(pg, name)
    return name


async def rename_project(pg, old, new):
    await open_projects(pg)
    clicked = await click_card_action(pg, old, "改名")
    if not clicked:
        raise AssertionError("项目卡没有可用的「改名」: %s" % old)
    await pg.wait_for_function(
        "() => { const d=document.querySelector('#modal'); return !!(d&&d.open&&d.label==='重命名项目'); }",
        timeout=10000)
    await pg.evaluate("""name => {
      const el=document.querySelector('#modal-form [name=name]');
      el.value=name; el.dispatchEvent(new Event('input',{bubbles:true})); el.dispatchEvent(new Event('sl-input', {bubbles:true}));
      document.querySelector('#modal-ok').click();
    }""", new)
    # 改名的 then 是进入项目详情，不是回列表：按详情标题核对，别拿列表当判据
    try:
        await pg.wait_for_function("""n => {
          const h=document.querySelector('#view-body .view-head h2');
          return !!(h && h.textContent.trim()===n);
        }""", arg=new, timeout=15000)
    except Exception:
        raise AssertionError("改名后详情标题未更新: %s" % new)
    return new


async def archive_project(pg, name):
    await open_projects(pg)
    clicked = await click_card_action(pg, name, "归档")
    if not clicked:
        raise AssertionError("项目卡没有可用的「归档」: %s" % name)
    try:
        await pg.wait_for_function("""n => {
          const c=[...document.querySelectorAll('#view-body .pcard')].find(x=>x.innerText.includes(n));
          return !!(c && /已归档/.test(c.innerText) && !/改名/.test(c.innerText));
        }""", arg=name, timeout=15000)
    except Exception:
        raise AssertionError("归档后项目卡未进入只读区: %s" % name)
    return True


async def delete_project_ui(pg, name):
    await open_projects(pg)
    clicked = await click_card_action(pg, name, "删除")
    if not clicked:
        raise AssertionError("项目卡没有可用的「删除」: %s" % name)
    try:
        await pg.wait_for_function(
            "n => ![...document.querySelectorAll('#view-body .pcard')].some(c => c.innerText.includes(n))",
            arg=name, timeout=15000)
    except Exception:
        raise AssertionError("删除后项目卡仍在列表中: %s" % name)
    return True


async def open_project(pg, name):
    clicked = await pg.evaluate("""name => {
      const c=[...document.querySelectorAll('#view-body .pcard')].find(x=>x.innerText.includes(name));
      if(!c) return false; c.click(); return true;
    }""", name)
    if not clicked:
        raise AssertionError("项目卡未找到: %s" % name)
    await pg.wait_for_selector("#view-body .view-head", timeout=20000)
    await pg.wait_for_timeout(600)


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
      const t=document.querySelector('#modal-form [name=title]'); t.value=p.title;
      t.dispatchEvent(new Event('input',{bubbles:true})); t.dispatchEvent(new Event('sl-input', {bubbles:true}));
      const g=document.querySelector('#modal-form [name=goal]'); g.value=p.goal;
      g.dispatchEvent(new Event('input',{bubbles:true})); g.dispatchEvent(new Event('sl-input', {bubbles:true}));
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


async def close_ticket(pg, tid):
    clicked = await pg.evaluate("""() => {
      const b=[...document.querySelectorAll('.chat-head-actions sl-button')]
        .find(x=>/结单/.test(x.textContent || ''));
      if(!b || b.disabled) return false; b.click(); return true;
    }""")
    if not clicked:
        raise AssertionError("工单头部没有可用的「结单」")
    await pg.wait_for_function(
        "() => { const d=document.querySelector('#modal'); return !!(d&&d.open&&d.label==='结单'); }",
        timeout=10000)
    await pg.evaluate("""() => {
      const s=document.querySelector('#modal-form [name=summary]');
      s.value='E2E 验收：建单、发消息、PM 回复、状态回 idle 全部通过。';
      s.dispatchEvent(new Event('input',{bubbles:true})); s.dispatchEvent(new Event('sl-input', {bubbles:true}));
      const v=document.querySelector('#modal-form [name=verdict]');
      if(v){ v.value='accepted'; v.dispatchEvent(new Event('sl-change', {bubbles:true})); }
      document.querySelector('#modal-ok').click();
    }""")
    last = {}
    for _ in range(30):
        await pg.wait_for_timeout(1000)
        last = await pg.evaluate("""async id => {
          const r=await run('ticket-thread',{id});
          return {session:r.thread.status, status:(r.ticket||{}).status,
                  locked:r.locked, lock:r.lock_reason||''};
        }""", tid)
        if last.get("status") == "closed" and last.get("locked") is True:
            break
    else:
        raise AssertionError("结单后状态未迁移为 closed: %s" % last)
    # 后端已 closed 后前端还要走一次 reload（then.reload），给它最多 10s 落地
    ui = {}
    for _ in range(20):
        await pg.wait_for_timeout(500)
        ui = await pg.evaluate("""() => ({
          badge:/已结单|closed/.test(document.querySelector('#view-body').innerText),
          controls:[...document.querySelectorAll('.composer-actions [data-ctl], .chat-head-actions [data-ctl]')]
            .filter(x=>/结单|发送|追加备注|语音/.test(x.textContent||''))
            .map(x=>({text:(x.textContent||'').trim(), disabled:!!x.disabled}))
        })""")
        if ui.get("badge") and ui.get("controls") and all(x["disabled"] for x in ui["controls"]):
            return last, ui
    raise AssertionError("结单后界面未进入只读: %s" % ui)


async def cleanup(pg, name):
    try:
        await pg.evaluate("""async name => {
          const r=await run('project-tree',{});
          const items=(r.items||[]).concat(r.archived||[]);
          const n=items.find(x=>((x.project||{}).name)===name);
          if(!n) return false;
          await run('projects-delete',{id:n.project.id,purge:true});
          return true;
        }""", name)
    except Exception:
        pass


async def scenario_project(pg):
    name = "e2e-project-%d" % int(time.time())
    renamed = None
    try:
        await create_project(pg, name)
        renamed = "e2e-renamed-%d" % int(time.time())
        await rename_project(pg, name, renamed)
        await archive_project(pg, renamed)
        await delete_project_ui(pg, renamed)
        return {"name": renamed, "created": True, "renamed": True,
                "archived": True, "deleted": True}
    finally:
        await cleanup(pg, name)
        if renamed:
            await cleanup(pg, renamed)


async def scenario_ticket(pg):
    name = "e2e-ticket-%d" % int(time.time())
    try:
        await create_project(pg, name)
        await open_project(pg, name)
        tid = await create_ticket(pg, "E2E 工单", "验证建单→发消息→岗位接收→模型回复→结单闭环")
        if not tid:
            raise AssertionError("建单后地址里没有 ticket 参数")
        before, after = await send_and_wait(pg, tid, "请给出这次工单的三步执行计划")
        if after["roles"] < 1:
            raise AssertionError("发消息后没有 PM 会话成员: %s" % after)
        closed, ui = await close_ticket(pg, tid)
        await archive_project(pg, name)
        await delete_project_ui(pg, name)
        return {"name": name, "ticket": tid, "before": before, "after": after,
                "closed": closed, "ui": ui}
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
        pg.on("dialog", lambda d: asyncio.create_task(d.accept()))
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        try:
            if args.scenario in ("project", "all"):
                out = await scenario_project(pg)
                print("  OK  项目 E2E：新建→改名→归档→删除 %s" % out["name"])
            if args.scenario in ("ticket", "all"):
                out = await scenario_ticket(pg)
                print("  OK  工单 E2E：建单→发消息→PM 回复→结单→项目归档→删除 %s %s"
                      "（消息 %s→%s，会话成员 %s）"
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
