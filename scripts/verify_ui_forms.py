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
        page = await browser.new_page(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
        await page.goto(BASE + "/", wait_until="networkidle")
        await ensure_login(page)
        await page.wait_for_selector("#view-body .pcard, #view-body .empty", timeout=15000)

        name = "UI表单-%d" % int(time.time())
        head = page.get_by_text("新建项目", exact=False).first
        check("头部有「新建项目」入口", await head.count() == 1 and await head.is_visible())
        await head.tap()
        await page.wait_for_selector("#modal[open]", timeout=8000)
        check("弹窗出现且字段可输入", await page.locator("#modal sl-input[name=name]").count() == 1)
        await page.fill("#modal sl-input[name=name] input", name)
        ok_btn = page.locator("#modal-ok")
        check("弹窗「创建项目」按钮可用", await ok_btn.is_visible() and not await ok_btn.is_disabled())
        await ok_btn.tap()
        await page.wait_for_timeout(2500)
        check("提交后弹窗关闭", await page.locator("#modal[open]").count() == 0)
        check("新项目卡片出现在列表", await page.get_by_text(name, exact=True).count() >= 1)
        await browser.close()
    if FAILS:
        print("UI 表单闭环失败：%s" % " | ".join(FAILS))
        return 1
    print("UI 表单闭环通过：新建项目三次点击全链路")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
