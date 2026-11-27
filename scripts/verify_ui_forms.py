"""真点前端的表单闭环：新建项目从按钮 → 弹窗 → 提交 → 卡片出现。

为什么单独一条：HTTP E2E 只证明能力能跑，不证明页面上的按钮绑对了、门禁没拦错、
提交后列表会刷新。这里每一步都用真实点击/输入，失败即阻断。

跑法：python3 scripts/verify_ui_forms.py [base_url]
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
        await pg.wait_for_selector("#view-body", timeout=15000)


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])
        ctx = await browser.new_context(ignore_https_errors=True, viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
        page = await ctx.new_page()
        await page.goto(BASE + "/", wait_until="networkidle")
        await ensure_login(page)
        await page.wait_for_selector("#view-body .pcard, #view-body .empty", timeout=15000)

        name = "UI表单-%d" % int(time.time())
        head = page.get_by_text("＋ 新建项目", exact=False).first
        check("头部有「新建项目」入口", await head.count() == 1 and await head.is_visible())
        # 用户实际会反复打开又取消：状态机在 modal/idle 之间来回切，必须每次都能再开。
        for i in range(5):
            await head.tap()
            await page.wait_for_selector("#modal[open]", timeout=5000)
            await page.get_by_text("取消", exact=True).last.tap()
            await page.wait_for_selector("#modal:not([open])", timeout=5000)
        check("连续 5 次「打开→取消」后入口仍可点", await head.is_visible() and not await head.is_disabled())
        await head.tap()
        await page.wait_for_selector("#modal[open]", timeout=8000)
        check("弹窗出现且字段可输入", await page.locator("#modal sl-input[name=name]").count() == 1)
        await page.fill("#modal sl-input[name=name] input", name)
        # Web Component 的 value 同步是异步的：填完立刻点提交，慢机/快机都可能读到旧空值。
        # 等控件自己的 value 真的等于输入值再提交，避免把“输入传播竞态”误判成业务失败。
        await page.wait_for_function(
            "(name) => document.querySelector('#modal sl-input[name=name]')?.value === name",
            arg=name, timeout=5000)
        ok_btn = page.locator("#modal-ok")
        check("弹窗「创建项目」按钮可用", await ok_btn.is_visible() and not await ok_btn.is_disabled())
        await ok_btn.tap()
        # 创建是真实 HTTP + 落盘 + 列表刷新；慢机不能拿固定 2.5 秒赌，等条件成立。
        closed = False
        for _ in range(30):
            if await page.locator("#modal[open]").count() == 0:
                closed = True
                break
            await page.wait_for_timeout(500)
        check("提交后弹窗关闭", closed)
        listed = False
        for _ in range(30):
            if await page.get_by_text(name, exact=True).count() >= 1:
                listed = True
                break
            await page.wait_for_timeout(500)
        check("新项目卡片出现在列表", listed)
        if FAILS:
            try:
                await page.screenshot(path="/tmp/ui-forms-failure.png", full_page=True)
                modal = await page.locator("#modal").inner_text()
                print("DEBUG modal_open=%d cards=%d text=%r"
                      % (await page.locator("#modal[open]").count(),
                         await page.get_by_text(name, exact=True).count(), modal[-200:]))
            except Exception as exc:  # noqa: BLE001 —— 诊断失败不覆盖主断言
                print("DEBUG 截图失败: %s" % exc)
        await browser.close()
    if FAILS:
        print("UI 表单闭环失败：%s" % " | ".join(FAILS))
        return 1
    print("UI 表单闭环通过：新建项目三次点击全链路")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
