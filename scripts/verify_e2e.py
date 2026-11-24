"""输入级 E2E：真实浏览器 → 弹窗 → 提交 → 列表出现 → 清理。

这不是“页面能打开”的冒烟，而是把用户最短路径完整走一遍：
点「新建项目」、填名称、提交、看到项目卡、再把测试项目删掉。
"""
from __future__ import annotations
import asyncio, os, sys, time
from playwright.async_api import async_playwright

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8787").rstrip("/")
CHROME = os.environ.get("CHROME", "/usr/local/bin/chromium")


async def main() -> int:
    name = "e2e-%d" % int(time.time())
    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])
        c = await b.new_context(viewport={"width": 390, "height": 844}, ignore_https_errors=True)
        token = os.environ.get("HIVE_TOKEN", "")
        if token:
            await c.add_cookies([{"name": "hive_token", "value": token,
                                  "domain": "127.0.0.1", "path": "/"}])
        pg = await c.new_page()
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        await pg.goto(BASE + "/manage.html?view=projects", wait_until="load", timeout=60000)
        await pg.wait_for_selector("#view-body .view-head", timeout=30000)
        btn = pg.locator("#view-body .view-head sl-button", has_text="新建项目").first
        await btn.wait_for(state="visible", timeout=10000)
        await btn.click()
        await pg.wait_for_timeout(500)
        modal = await pg.evaluate("""() => {
          const d=document.querySelector('#modal');
          return {open:!!(d&&d.open), fields:document.querySelectorAll('#modal-form sl-input').length};
        }""")
        if not (modal["open"] and modal["fields"] >= 1):
            print("FAIL 新建项目弹窗未打开", modal, errs); await b.close(); return 1
        await pg.evaluate("""name => {
          const el=document.querySelector('#modal-form sl-input');
          el.value=name; el.dispatchEvent(new Event('sl-input', {bubbles:true}));
          document.querySelector('#modal-ok').click();
        }""", name)
        try:
            await pg.wait_for_function("""name => document.querySelector('#view-body')?.innerText.includes(name)""",
                                       arg=name, timeout=20000)
        except Exception:
            print("FAIL 提交后列表未出现项目", name, errs); await b.close(); return 1
        found = await pg.evaluate("""async name => {
          const r = await run('project-tree', {});
          const items = (r.result && r.result.items) || r.items || [];
          const n = items.find(x => ((x.project||{}).name) === name);
          if (!n) return {found:false, cleaned:false};
          await run('projects-delete', {id:n.project.id, purge:true});
          return {found:true, id:n.project.id, cleaned:true};
        }""", name)
        if not found.get("cleaned"):
            print("FAIL 项目已创建但清理失败", name, found); await b.close(); return 1
        print("  OK  新建项目 E2E：弹窗→提交→列表出现→已清理", name)
        if errs:
            print("  FAIL 页面 JS 异常", errs); await b.close(); return 1
        await b.close()
        return 0

if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
