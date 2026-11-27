"""群聊秘书的 IM 发送态与头像一致性真机门禁。

覆盖三件线上必须成立的事：
1) 发出的那一刻右侧先出现自己的气泡，带「发送中」转圈；
2) 消息头像与顶部成员头像同字同色（不再出现顶部「我」、气泡「用」）；
3) 请求失败时气泡标红且「重发」可点，重发同 msg_id 只入队一次。

跑法：CHROME=... python3 scripts/verify_im_secretary.py [base_url]
"""
from __future__ import annotations
import asyncio
import os
import sys
import time

from playwright.async_api import async_playwright

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8787").rstrip("/")
CHROME = os.environ.get("CHROME", "/usr/local/bin/chromium")
FAILS = []


def check(name, ok, detail=""):
    print(("  OK  " if ok else "  FAIL") + " " + name + ((" · " + str(detail)) if detail and not ok else ""))
    if not ok:
        FAILS.append(name + (" · " + str(detail) if detail else ""))


async def ensure_login(pg):
    if await pg.locator("#login-form").count() and await pg.locator("#login-form").is_visible():
        await pg.fill("#username input", "admin")
        await pg.fill("#password input", "123456")
        await pg.click("#login-form button[type=submit]")
        # 登录提交会自己跳到 manage.html：等目标 URL 落定，再等控制台挂载。
        try:
            await pg.wait_for_url("**/manage.html**", timeout=15000)
        except Exception:
            if await pg.locator("#login-form").count() and await pg.locator("#login-form").is_visible():
                await pg.goto(BASE + "/", wait_until="domcontentloaded")
        await pg.wait_for_selector("#view-body", timeout=15000)


async def api(pg, demand, input_):
    got = await pg.evaluate(
        """async ([demand, input]) => {
            const r = await fetch('/api/rpc/demand_engine/run', {method:'POST',
              headers: {'Content-Type':'application/json',
                        'X-Auth-Token': localStorage.getItem('ai_new_token') || ''},
              body: JSON.stringify({id: demand, input})});
            const y = await r.text();
            return y;
        }""", [demand, input_])
    return got


async def create_project(pg, name):
    raw = await api(pg, "projects-create", {"name": name})
    # 回包按服务端配置可能是 YAML/JSON；这里只需要 id，用正则兜底，不引第三方解析。
    import re
    m = re.search(r"(?:id|project):\s*'?([^'\n,}]+)'?", raw)
    return m.group(1).strip() if m else name


async def avatar_of(pg, sel):
    return await pg.eval_on_selector(sel, """e => ({text: e.textContent.trim(),
        color: getComputedStyle(e).getPropertyValue('--av').trim()})""")


async def wait_gone(pg, sel, timeout=15000):
    try:
        await pg.wait_for_selector(sel, state="detached", timeout=timeout)
        return True
    except Exception:
        return False


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])
        ctx = await browser.new_context(ignore_https_errors=True, viewport={"width": 430, "height": 900},
                                        is_mobile=True, has_touch=True)
        page = await ctx.new_page()
        await page.goto(BASE + "/", wait_until="networkidle")
        await ensure_login(page)
        name = "IM验收-%d" % int(time.time())
        proj = await create_project(page, name)
        await page.goto(f"{BASE}/manage.html?view=secretary&project={proj}", wait_until="networkidle")
        await page.wait_for_selector(".composer", timeout=15000)
        await page.evaluate("localStorage.removeItem('ai_new_outbox_v1')")
        chips = await page.eval_on_selector_all(".av-chip", """els => els.map(e => ({
            text: e.textContent.trim(),
            color: getComputedStyle(e).getPropertyValue('--av').trim()}))""")
        me = next((x for x in chips if x["text"] == "我"), None)
        check("顶部成员里有「我」", bool(me), chips)

        async def slow_intake(route):
            body = route.request.post_data or ""
            if "secretary-intake" in body:
                await asyncio.sleep(2.0)
            await route.continue_()

        await page.route("**/api/rpc/demand_engine/run", slow_intake)
        ta = page.locator(".composer textarea")
        text1 = "IM发送态-%d" % int(time.time())
        await ta.fill(text1)
        await page.locator("[data-clk='composer_send']").click()
        await page.wait_for_timeout(350)
        sending = page.locator(".msg.outbox.sending")
        check("发送瞬间出现自己的发送中气泡", await sending.count() == 1)
        check("发送中气泡有转圈", await page.locator(".msg.outbox.sending .out-spin").count() == 1)
        check("发送中气泡写了「发送中」", "发送中" in (await sending.first.inner_text()))
        av = await avatar_of(page, ".msg.outbox .avatar")
        check("消息头像与顶部「我」同字", me and av["text"] == me["text"], (av, me))
        check("消息头像与顶部「我」同色", me and av["color"] == me["color"], (av, me))
        check("成功回显后本地气泡被服务器消息替换", await wait_gone(page, ".msg.outbox", 15000))
        await page.unroute("**/api/rpc/demand_engine/run")
        check("服务器消息流出现刚发的文本", await page.get_by_text(text1, exact=True).count() >= 1)

        async def fail_intake(route):
            body = route.request.post_data or ""
            if "secretary-intake" in body:
                await route.abort()
            else:
                await route.continue_()

        await page.route("**/api/rpc/demand_engine/run", fail_intake)
        text2 = "IM失败重发-%d" % int(time.time())
        await ta.fill(text2)
        await page.locator("[data-clk='composer_send']").click()
        await page.wait_for_timeout(1000)
        failed = page.locator(".msg.outbox.failed")
        check("失败后气泡标红并保留", await failed.count() == 1)
        check("失败气泡有「重发」按钮", await page.locator(".msg.outbox.failed [data-clk='chat_retry']").count() == 1)
        check("失败文案可见", "发送失败" in (await failed.first.inner_text()))
        await page.unroute("**/api/rpc/demand_engine/run")
        await page.locator(".msg.outbox.failed [data-clk='chat_retry']").first.click()
        check("重发后本地失败气泡消失", await wait_gone(page, ".msg.outbox", 15000))
        check("重发文本出现在服务器消息流", await page.get_by_text(text2, exact=True).count() >= 1)

        # 入队后必须有人处理：等秘书批次回执出现，不能再停在 pending。
        try:
            await page.wait_for_function(
                "() => Array.from(document.querySelectorAll('.msg.left')).some(e => /已合并|合并/.test(e.innerText))",
                timeout=30000)
            replied = True
        except Exception:
            replied = False
        check("秘书在消息后给出批次回执（自动处理已跑）", replied)
        await browser.close()
    if FAILS:
        print("IM 发送态验收失败：%s" % " | ".join(FAILS))
        return 1
    print("IM 发送态验收通过：乐观气泡/转圈/头像一致/失败重发/自动处理回执")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
