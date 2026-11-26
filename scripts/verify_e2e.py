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
    await pg.wait_for_timeout(800)


async def card_exists(pg, name):
    return await pg.evaluate(
        "n => [...document.querySelectorAll('#view-body .pcard')].some(c => c.innerText.includes(n))",
        name)


async def wait_card(pg, name, timeout=30000):
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
    await pg.wait_for_function("""() => {
      const d=document.querySelector('#modal');
      return !!(d && d.open && d.label === '新建项目'
                && document.querySelectorAll('#modal-form [name]').length >= 1);
    }""", timeout=20000)
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
        timeout=20000)
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
        }""", arg=new, timeout=25000)
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
        }""", arg=name, timeout=25000)
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
            arg=name, timeout=25000)
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
    # 点卡片只改地址，详情数据还要异步取一轮；等标题真正换成项目名，别拿列表页的头当详情。
    await pg.wait_for_function(
        "n => { const h=document.querySelector('#view-body .view-head h2');"
        " return !!(h && h.textContent.trim()===n); }", arg=name, timeout=20000)
    await pg.wait_for_function(
        "() => [...document.querySelectorAll('#view-body .view-head sl-button')]"
        ".some(b => /新建工单/.test(b.textContent || ''))", timeout=20000)


async def create_ticket(pg, title, goal):
    # 页面刚 reload/切换视图时按钮可能被整页替换掉：按「按钮在且可用 → 点 → 弹窗真开」重试，
    # 单次 locator.click 会把这种时序抖动直接判成功能失败。
    opened = False
    for _ in range(6):
        try:
            await pg.wait_for_function("""() => {
              const b=[...document.querySelectorAll('#view-body .view-head sl-button')]
                .find(x=>/新建工单/.test(x.textContent || ''));
              return !!(b && !b.disabled);
            }""", timeout=8000)
        except Exception:
            await pg.wait_for_timeout(500)
            continue
        clicked = await pg.evaluate("""() => {
          const b=[...document.querySelectorAll('#view-body .view-head sl-button')]
            .find(x=>/新建工单/.test(x.textContent || ''));
          if(!b || b.disabled) return false; b.click(); return true;
        }""")
        if not clicked:
            await pg.wait_for_timeout(500)
            continue
        try:
            await pg.wait_for_function("""() => {
              const d=document.querySelector('#modal');
              return !!(d && d.open && d.label === '新建工单'
                        && document.querySelectorAll('#modal-form [name]').length >= 2);
            }""", timeout=6000)
            opened = True
            break
        except Exception:
            await pg.wait_for_timeout(500)
    if not opened:
        raise AssertionError("「新建工单」弹窗未打开（按钮/页面状态未就绪）")
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
    await pg.wait_for_selector("#view-body .composer textarea", timeout=30000)
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
    # 发送/回复后页面会 reload 一轮，控件与页面状态机都可能还没回到 idle；
    # 点击会被吞。这里按控件+页面状态重试，直到结单弹窗真的打开。
    opened = False
    for _ in range(4):
        try:
            await pg.wait_for_function("""() => {
              const b=[...document.querySelectorAll('.chat-head-actions sl-button')]
                .find(x=>/结单/.test(x.textContent || ''));
              const ui=window.uiSnapshot ? window.uiSnapshot() : {state:'idle'};
              return !!(b && !b.disabled && (b.dataset.ctlState || 'idle') === 'idle'
                        && (ui.state === 'idle' || ui.state === 'press'));
            }""", timeout=10000)
        except Exception:
            await pg.wait_for_timeout(500)
            continue
        clicked = await pg.evaluate("""() => {
          const b=[...document.querySelectorAll('.chat-head-actions sl-button')]
            .find(x=>/结单/.test(x.textContent || ''));
          if(!b || b.disabled) return false; b.click(); return true;
        }""")
        if not clicked:
            await pg.wait_for_timeout(500)
            continue
        for _ in range(12):
            await pg.wait_for_timeout(300)
            if await pg.evaluate("""() => {
              const d=document.querySelector('#modal');
              return !!(d && d.open && d.label === '结单');
            }"""):
                opened = True
                break
        if opened:
            break
        await pg.wait_for_timeout(500)
    if not opened:
        raise AssertionError("结单弹窗未打开（按钮/页面状态机未就绪）")
    await pg.evaluate("""() => {
      const s=document.querySelector('#modal-form [name=summary]');
      s.value='E2E 验收：建单、发消息、PM 回复、状态回 idle 全部通过。';
      s.dispatchEvent(new Event('input',{bubbles:true})); s.dispatchEvent(new Event('sl-input', {bubbles:true}));
      const v=document.querySelector('#modal-form [name=verdict]');
      if(v){ v.value='accepted'; v.dispatchEvent(new Event('sl-change', {bubbles:true})); }
      document.querySelector('#modal-ok').click();
    }""")
    last = {}
    for _ in range(60):
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


async def scenario_ticket_multi(pg):
    """同一工单连续两轮追问：每轮都要重新回到 idle 并产生新回复。"""
    name = "e2e-multi-%d" % int(time.time())
    try:
        await create_project(pg, name)
        await open_project(pg, name)
        tid = await create_ticket(pg, "E2E 多轮工单",
                                  "验证同一工单连续两轮追问都能收口，不串轮、不丢消息")
        if not tid:
            raise AssertionError("建单后地址里没有 ticket 参数")
        b1, a1 = await send_and_wait(pg, tid, "第一轮：给出两条验收要点")
        b2, a2 = await send_and_wait(pg, tid, "第二轮：在上一轮基础上补一条风险")
        if not (a2["n"] > a1["n"] > b1):
            raise AssertionError("两轮消息数未单调增长: %s -> %s -> %s" % (b1, a1, a2))
        closed, ui = await close_ticket(pg, tid)
        await archive_project(pg, name)
        await delete_project_ui(pg, name)
        return {"name": name, "ticket": tid, "rounds": 2,
                "messages": [b1, a1["n"], b2, a2["n"]], "closed": closed, "ui": ui}
    finally:
        await cleanup(pg, name)


async def scenario_roles_dom(pg):
    """多岗位协作在真实 DOM 里：PM 发一轮 → 派发 developer → 群聊两路各自署名，不串名。

    前端没有「派发」按钮，角色由 PM 侧能力开出；这里通过页面自带的 run() 走真实
    RPC 派发，之后的渲染/成员卡/发言全部按 DOM 判定，盯的是「多会话能不能正确
    显示成一条带署名的群聊」，而不是接口有没有返回。
    """
    name = "e2e-roles-%d" % int(time.time())
    try:
        await create_project(pg, name)
        await open_project(pg, name)
        tid = await create_ticket(pg, "多岗位浏览器协作",
                                  "验证 PM 与开发两路消息在群聊里各自署名渲染")
        if not tid:
            raise AssertionError("建单后地址里没有 ticket 参数")
        mark_pm = "PM标记-%d" % time.time_ns()
        _, pm_last = await send_and_wait(pg, tid, mark_pm)

        spawned = await pg.evaluate("""async id => await run('ticket-role-spawn',
          {id, role: 'developer', task: '产出 docs/handoff/dev.md 并报验收点'})""", tid)
        roles = spawned.get("roles") or []
        if not roles:
            raise AssertionError("派发 developer 没有回收色行: %s" % spawned)
        dev_sid = (roles[0] or {}).get("session") or ""
        if not dev_sid or dev_sid == pm_last.get("session"):
            raise AssertionError("角色会话未独立开出: %s" % spawned)

        # 重新进页面：成员条与群聊要按新角色重渲染，不能只信旧快照
        await pg.reload(wait_until="load")
        await pg.wait_for_selector("#view-body .composer textarea", timeout=30000)
        members = await pg.evaluate("""() => (window.RENDER_MEMBERS || []).map(m => ({
          role: m.role || '', display: m.display || m.role || '',
          session: m.session || '', status: m.status || ''}))""")
        sids = {m["session"] for m in members}
        if len(sids) < 2 or dev_sid not in sids:
            raise AssertionError("成员条没有渲染出两路会话: %s" % members)

        mark_dev = "开发标记-%d" % time.time_ns()
        await pg.evaluate("""p => run('role-session-message', {id: p.sid, text: p.text})""",
                          {"sid": dev_sid, "text": mark_dev})
        # 角色那一路在后台跑：等它真跑完（status 回 idle 且有 assistant 轮次）再重进页面，
        # 否则只是「消息发出去了」，群聊自然还看不到。
        dev_state = {}
        for _ in range(80):
            await pg.wait_for_timeout(1000)
            dev_state = await pg.evaluate("""async id => {
              const s = await run('session-get', {id});
              const msgs = s.messages || [];
              return {status: s.status, n: msgs.length,
                      answered: msgs.some(m => m.role === 'assistant' &&
                        (m.content || '').trim())};
            }""", dev_sid)
            if dev_state.get("status") == "idle" and dev_state.get("answered"):
                break
        if not (dev_state.get("status") == "idle" and dev_state.get("answered")):
            raise AssertionError("开发会话 80s 内没有收口回复: %s" % dev_state)
        await pg.reload(wait_until="load")
        await pg.wait_for_selector("#view-body .composer textarea", timeout=30000)
        # 群聊里用户消息本来就不署名，能证明「两路都渲染」的是 assistant 气泡的署名：
        # 等 developer 那一侧真长出带署名的气泡，而不是拿 human 原文当判据（会被压缩吃掉）。
        try:
            await pg.wait_for_function("""() => [...document.querySelectorAll('#view-body .msg')]
              .some(m => ((m.querySelector('.msg-name') || {}).textContent || '') === 'developer')""",
                                       timeout=40000)
        except Exception:
            raise AssertionError("群聊里没有出现 developer 署名的回复")

        bubbles = await pg.evaluate("""() => [...document.querySelectorAll('#view-body .msg')]
          .map(m => ({name: (m.querySelector('.msg-name') || {}).textContent || '',
                      text: m.innerText || ''}))""")
        pm_bubbles = [b for b in bubbles if b["name"] and b["name"] not in ("developer", "")]
        dev_bubbles = [b for b in bubbles if b["name"] == "developer"]
        if not pm_bubbles:
            raise AssertionError("群聊里没有 PM 署名气泡: %s" % bubbles)
        if not dev_bubbles:
            raise AssertionError("群聊里没有 developer 署名气泡: %s" % bubbles)
        if pm_bubbles[0]["name"] == dev_bubbles[0]["name"]:
            raise AssertionError("两路署名混成同一个名字")
        if any(mark_dev in b["text"] or mark_pm in b["text"] for b in dev_bubbles):
            raise AssertionError("人的消息串进了开发气泡（串扰）: %r" % dev_bubbles[0]["text"][:120])

        # 永久留档侧再核一次：工单 transcript 里必须有 role 会话的 assistant 轮次，
        # 会话被回收/压缩后仍能回看，这是「多岗位协作不丢账」的底线。
        thread_now = await pg.evaluate("""async id => await run('ticket-thread', {id})""", tid)
        role_msgs = [m for m in ((thread_now.get("thread") or {}).get("messages") or [])
                     if (m.get("session") or "") == dev_sid]
        if not any(m.get("role") == "assistant" for m in role_msgs):
            raise AssertionError("工单留档里没有开发会话的回复: %d 条" % len(role_msgs))

        # 成员卡是真实交互：点开 developer 那张，弹层里必须写着它的会话号
        idx = next(i for i, m in enumerate(members) if m["session"] == dev_sid)
        clicked = await pg.evaluate("""i => {
          const c = document.querySelector(`#view-body .members [data-clk="member_chip"][data-member="${i}"]`);
          if (!c) return false; c.click(); return true;
        }""", idx)
        if not clicked:
            raise AssertionError("developer 成员卡不存在，点不开")
        pop = await pg.evaluate("""() => { const p = document.querySelector('#popover');
          return {open: !!p && !p.hidden, text: (p && p.innerText) || ''}; }""")
        if not (pop["open"] and "developer" in pop["text"] and dev_sid in pop["text"]):
            raise AssertionError("成员卡没写出岗位与会话: %s" % pop)

        closed, _ = await close_ticket(pg, tid)
        await delete_project_ui(pg, name)
        pm_sid = next((m["session"] for m in members if m["session"] != dev_sid), "")
        return {"name": name, "ticket": tid, "pm": pm_sid,
                "developer": dev_sid, "members": len(members), "closed": closed}
    finally:
        await cleanup(pg, name)


async def scenario_archive_guard(pg):
    """归档后的项目：新建工单入口必须不可用，不能靠前端灰按钮后仍能点开弹窗。"""
    name = "e2e-arch-%d" % int(time.time())
    try:
        await create_project(pg, name)
        await archive_project(pg, name)
        clicked = await pg.evaluate("""name => {
          const c=[...document.querySelectorAll('#view-body .pcard')].find(x=>x.innerText.includes(name));
          if(!c) return false; c.click(); return true;
        }""", name)
        if not clicked:
            raise AssertionError("归档项目卡未找到: %s" % name)
        await pg.wait_for_timeout(3000)
        state = await pg.evaluate("""() => {
          const b=[...document.querySelectorAll('#view-body .view-head sl-button')]
            .find(x=>/新建工单/.test(x.textContent || ''));
          if(!b) return {exists:false, disabled:true};
          b.click();
          const d=document.querySelector('#modal');
          return {exists:true, disabled:!!b.disabled, opened:!!(d&&d.open)};
        }""" )
        if state.get("opened"):
            raise AssertionError("归档项目仍能打开新建工单弹窗: %s" % state)
        if state.get("exists") and not state.get("disabled"):
            raise AssertionError("归档项目的新建工单按钮未禁用: %s" % state)
        await delete_project_ui(pg, name)
        return {"name": name, "guard": True, "button": state}
    finally:
        await cleanup(pg, name)


async def scenario_ticket_rounds(pg):
    """同一工单在真实 DOM 里连发两轮：每轮都要收口、composer 回可用、消息单调增长。"""
    name = "e2e-rounds-%d" % int(time.time())
    try:
        await create_project(pg, name)
        await open_project(pg, name)
        tid = await create_ticket(pg, "E2E 两轮追问", "验证同单两轮追问在前端逐轮收口")
        if not tid:
            raise AssertionError("建单后地址里没有 ticket 参数")
        marks = []
        counts = []
        for i, text in enumerate(("第一轮：给出两条验收要点", "第二轮：在上一轮基础上补一条风险")):
            mark = "%s-%d" % (text[:4], int(time.time() * 1000))
            marks.append(mark)
            full = "%s（%s）" % (text, mark)
            before, after = await send_and_wait(pg, tid, full)
            if after["n"] <= before:
                raise AssertionError("第 %d 轮消息数没增长: %s -> %s" % (i + 1, before, after["n"]))
            counts.append(after["n"])
            composer = await pg.evaluate("""() => {
              const ta=document.querySelector('#view-body .composer textarea');
              const b=[...document.querySelectorAll('.composer-actions sl-button')]
                .find(x=>x.textContent.includes('发送'));
              return {ta:!!ta, empty:!!ta && !ta.value.trim(), send:!!b && !b.disabled};
            }""")
            if not (composer["ta"] and composer["empty"] and composer["send"]):
                raise AssertionError("第 %d 轮后 composer 未回到可用: %s" % (i + 1, composer))
        # 会话有压缩（compactp）会丢旧轮，别拿「原文永留」当断言：
        # 推进证据用轮次增长（上面已断言），这里只确认 transcript 至少含两轮 user + 两轮 assistant。
        thread = await pg.evaluate("""async id => (await run('ticket-thread',{id}))""", tid)
        msgs = (thread.get("thread") or {}).get("messages") or []
        users = [m for m in msgs if m.get("role") == "user"]
        bots = [m for m in msgs if m.get("role") == "assistant"]
        if len(users) < 2 or len(bots) < 2:
            raise AssertionError("transcript 轮次不足: user %d / assistant %d"
                                 % (len(users), len(bots)))
        closed, ui = await close_ticket(pg, tid)
        await archive_project(pg, name)
        await delete_project_ui(pg, name)
        return {"name": name, "ticket": tid, "rounds": 2,
                "messages": counts, "readonly": True, "ui": ui}
    finally:
        await cleanup(pg, name)


async def scenario_timer_ui(pg):
    """定时器页面走真实按钮：改表达式弹窗 → 暂停 → 恢复 → 删除，状态与禁用门槛都要对。"""
    name = "e2e-timer-ui-%d" % int(time.time())
    title = "ST 定时器 %d" % int(time.time())
    try:
        # 先落一次页面：run() 是页面里的全局 RPC，没加载过页面直接 evaluate 会 ReferenceError
        await open_projects(pg)
        project = await pg.evaluate("""async name => await run('projects-create',{name})""", name)
        pid = project.get("id") or name
        caller = {"scope": "project", "project": pid, "role": "pm"}
        created = await pg.evaluate("""async p => await run('timer-create', p)""", {
            "project": pid, "kind": "once",
            "expr": _iso_in(900), "tz": "UTC", "title": title,
            "action": "notify", "caller": caller})
        timer_id = created.get("id") or ""
        if not timer_id:
            raise AssertionError("后端建定时器失败: %s" % created)

        await pg.goto(BASE + "/manage.html?view=timers", wait_until="load", timeout=60000)
        await pg.wait_for_selector("#view-body .view-head", timeout=30000)
        await pg.wait_for_function(
            "t => document.querySelector('#view-body').innerText.includes(t)",
            arg=title, timeout=30000)

        # 行内按钮定位：按文案找按钮，再确认它的祖先里包含本次标题，避免点错别的行
        async def click_row(label):
            got = await pg.evaluate("""([t,label]) => {
              const btns=[...document.querySelectorAll('#view-body sl-button')]
                .filter(b => (b.textContent || '').trim() === label);
              for (const b of btns) {
                let p = b;
                for (let i = 0; i < 6 && p; i++, p = p.parentElement) {
                  if ((p.textContent || '').includes(t)) { if (b.disabled) return 'disabled'; b.click(); return 'ok'; }
                }
              }
              return 'missing';
            }""", [title, label])
            if got != "ok":
                raise AssertionError("行内按钮「%s」不可点: %s" % (label, got))
            return True

        async def timer_row():
            rows = await pg.evaluate("""async c => await run('timer-list', {caller: c})""", caller)
            return next((x for x in (rows.get("items") or []) if x.get("id") == timer_id), None)

        # 1) 改表达式：走弹窗表单，保存后下次触发时刻要按新表达式重排
        before = await timer_row() or {}
        await click_row("改表达式")
        await pg.wait_for_function(
            "() => { const d=document.querySelector('#modal');"
            " return !!(d && d.open && d.label === '改表达式'); }", timeout=20000)
        await pg.evaluate("""expr => {
          const el=document.querySelector('#modal-form [name=expr]');
          el.value=expr; el.dispatchEvent(new Event('input',{bubbles:true}));
          el.dispatchEvent(new Event('sl-input', {bubbles:true}));
          document.querySelector('#modal-ok').click();
        }""", _iso_in(1800))
        moved = {}
        for _ in range(20):
            await pg.wait_for_timeout(500)
            moved = await timer_row() or {}
            if moved.get("expr") and str(moved["expr"]) != str(before.get("expr")):
                break
        if not moved.get("expr") or str(moved["expr"]) == str(before.get("expr")):
            raise AssertionError("改表达式没有生效: %s -> %s" % (before.get("expr"), moved))
        if float(moved.get("next_at") or 0) <= float(before.get("next_at") or 0):
            raise AssertionError("改表达式后下次触发没往后排: %s -> %s"
                                 % (before.get("next_at"), moved.get("next_at")))

        # 2) 暂停：状态翻转 + 暂停按钮转禁用（门槛要真拦）
        await pg.wait_for_timeout(800)
        await click_row("暂停")
        paused = {}
        for _ in range(20):
            await pg.wait_for_timeout(400)
            paused = await timer_row() or {}
            if paused.get("status") == "paused":
                break
        if paused.get("status") != "paused":
            raise AssertionError("点暂停后状态未翻转: %s" % paused)
        guard = await pg.evaluate("""t => {
          const btns=[...document.querySelectorAll('#view-body sl-button')]
            .filter(b => (b.textContent || '').trim() === '暂停');
          for (const b of btns) {
            let p=b;
            for (let i=0;i<6 && p;i++,p=p.parentElement)
              if ((p.textContent||'').includes(t)) return !!b.disabled;
          }
          return null;
        }""", title)
        if guard is not True:
            raise AssertionError("暂停态下「暂停」按钮未禁用: %r" % guard)

        # 3) 恢复：状态回 active
        await click_row("恢复")
        resumed = {}
        for _ in range(20):
            await pg.wait_for_timeout(400)
            resumed = await timer_row() or {}
            if resumed.get("status") == "active":
                break
        if resumed.get("status") != "active":
            raise AssertionError("点恢复后状态未回到 active: %s" % resumed)

        # 4) 删除：确认框走真实 dialog，行要从列表消失
        await click_row("删除")
        gone = False
        for _ in range(20):
            await pg.wait_for_timeout(400)
            listed = await timer_row()
            if listed is None:
                gone = True
                break
        if not gone:
            raise AssertionError("删除后定时器仍在列表: %s" % (await timer_row()))
        return {"project": name, "timer": timer_id, "edit": True,
                "pause": True, "resume": True, "delete": True, "guard": True}
    finally:
        await pg.evaluate("""async name => {
          try {
            const r=await run('project-tree',{});
            const items=(r.items||[]).concat(r.archived||[]);
            const n=items.find(x=>((x.project||{}).name)===name);
            if(n) await run('projects-delete',{id:n.project.id,purge:true});
          } catch(e) {}
          return true;
        }""", name)


def _iso_in(seconds):
    """相对当前 UTC 的 ISO 时刻：浏览器侧定时器表达式要显式给未来时间。"""
    import datetime
    return (datetime.datetime.now(datetime.timezone.utc)
            + datetime.timedelta(seconds=seconds)).isoformat()


async def main() -> int:
    global BASE
    ap = argparse.ArgumentParser()
    ap.add_argument("base", nargs="?", default=BASE)
    ap.add_argument("--scenario", choices=("project", "ticket", "ticket-multi",
                                           "archive-guard", "ticket-rounds",
                                           "timer-ui", "roles-dom", "all"),
                            default="all")
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
            if args.scenario in ("archive-guard", "all"):
                out = await scenario_archive_guard(pg)
                print("  OK  归档只读 E2E：归档后新建工单入口不可用 %s %s"
                      % (out["name"], out["button"]))
            if args.scenario in ("ticket-multi", "all"):
                out = await scenario_ticket_multi(pg)
                print("  OK  多轮工单 E2E：两轮追问→逐轮收口→结单→归档→删除 %s %s（消息 %s）"
                      % (out["name"], out["ticket"], out["messages"]))
            if args.scenario in ("ticket-rounds", "all"):
                out = await scenario_ticket_rounds(pg)
                print("  OK  两轮追问 E2E：同单连发两轮→逐轮收口→composer 回可用→结单只读 %s %s（消息 %s）"
                      % (out["name"], out["ticket"], out["messages"]))
            if args.scenario in ("timer-ui", "all"):
                out = await scenario_timer_ui(pg)
                print("  OK  定时器页面 E2E：改表达式→暂停→恢复→删除 %s %s（禁用门槛成立）"
                      % (out["project"], out["timer"]))
            if args.scenario in ("roles-dom", "all"):
                out = await scenario_roles_dom(pg)
                print("  OK  多岗位渲染 E2E：PM→派开发→两路各自署名→成员卡可见→结单 %s %s"
                      "（成员 %s，PM %s，开发 %s）"
                      % (out["name"], out["ticket"], out["members"], out["pm"],
                         out["developer"]))
            if errs:
                print("  FAIL 页面 JS 异常: %s" % errs)
                return 1
            return 0
        except Exception as exc:
            print("  FAIL %s" % exc)
            if args.scenario in ("ticket-rounds", "all"):
                out = await scenario_ticket_rounds(pg)
                print("  OK  两轮追问 E2E：同单连发两轮→逐轮收口→composer 回可用→结单只读 %s %s（消息 %s）"
                      % (out["name"], out["ticket"], out["messages"]))
            if args.scenario in ("timer-ui", "all"):
                out = await scenario_timer_ui(pg)
                print("  OK  定时器页面 E2E：改表达式→暂停→恢复→删除 %s %s（禁用门槛成立）"
                      % (out["project"], out["timer"]))
            if args.scenario in ("roles-dom", "all"):
                out = await scenario_roles_dom(pg)
                print("  OK  多岗位渲染 E2E：PM→派开发→两路各自署名→成员卡可见→结单 %s %s"
                      "（成员 %s，PM %s，开发 %s）"
                      % (out["name"], out["ticket"], out["members"], out["pm"],
                         out["developer"]))
            if errs:
                print("  FAIL 页面 JS 异常: %s" % errs)
            return 1
        finally:
            await b.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
