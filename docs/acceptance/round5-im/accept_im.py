"""IM 控制台双端真实验收：真实浏览器登录、点击、截图、控制台错误收集。"""
from __future__ import annotations
import argparse, json, os, sys, time
from datetime import datetime, timezone
from pathlib import Path
from playwright.sync_api import sync_playwright, Page, expect

ROOT = Path(__file__).resolve().parent
PROJECT = "群聊样式验证"
TICKET = "TG 样式冒烟"


def now():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def login(page: Page, base: str):
    page.goto(base, wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(1200)
    if page.locator("#username").count():
        page.locator("#username input").fill("admin")
        page.locator("#password input").fill("123456")
        page.locator("#login-form button[type=submit], #login-form sl-button").first.click()
        page.wait_for_timeout(2200)


def shot(page: Page, name: str, steps: list, label: str):
    path = ROOT / name
    page.screenshot(path=str(path), full_page=False)
    steps.append({"shot": name, "label": label, "ok": True, "at": now(), "url": page.url})
    return path


def no_hscroll(page: Page):
    return page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=os.environ.get("IM_BASE", "http://127.0.0.1:8787/"))
    ap.add_argument("--out", default=str(ROOT))
    args = ap.parse_args()
    base = args.base
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    steps, errors = [], []
    views = [("desktop", 1440, 900), ("mobile", 390, 844)]
    started = time.time()

    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path="/usr/local/bin/chromium", headless=True,
            args=["--no-sandbox", "--ignore-certificate-errors"])
        for label, w, h in views:
            ctx = browser.new_context(viewport={"width": w, "height": h}, ignore_https_errors=True)
            page = ctx.new_page()
            page.on("console", lambda m, l=label: errors.append({"viewport": l, "kind": "console", "text": m.text})
                    if m.type == "error" and "favicon" not in m.text.lower() else None)
            page.on("pageerror", lambda e, l=label: errors.append({"viewport": l, "kind": "pageerror", "text": str(e)}))
            login(page, base)

            # 1) 项目列表（IM 底栏/侧栏入口后的首屏）
            if label == "mobile":
                expect(page.locator("#tabbar .tab").first).to_contain_text("项目")
                tabs = page.locator("#tabbar .tab")
                assert tabs.count() == 4, f"底栏应有 4 项，实际 {tabs.count()}"
                shot(page, f"{label}-01-projects.png", steps, "底栏项目列表")
            else:
                shot(page, f"{label}-01-projects.png", steps, "侧栏项目列表")
            assert no_hscroll(page), f"{label} 项目列表横向溢出"

            # 2) 项目卡片 -> 项目详情
            page.locator("article[role=button]").filter(has_text=PROJECT).first.click()
            page.wait_for_function("document.title.includes('群聊样式验证')", timeout=10000)
            page.wait_for_timeout(900)
            shot(page, f"{label}-02-project-detail.png", steps, "项目详情首屏")
            rows = page.locator(".pcard.list")
            assert rows.count() >= 2, f"{label} 项目详情应有秘书+工单行，实际 {rows.count()}"
            first = rows.first.inner_text()
            assert "群聊秘书" in first, f"项目详情第一项不是群聊秘书：{first}"
            assert no_hscroll(page), f"{label} 项目详情横向溢出"

            # 3) 第一项群聊秘书
            rows.first.click()
            page.wait_for_function("document.title.includes('群聊秘书')", timeout=10000)
            page.wait_for_timeout(900)
            shot(page, f"{label}-03-secretary.png", steps, "群聊秘书")
            assert no_hscroll(page), f"{label} 群聊秘书横向溢出"

            # 4) 返回项目详情，点其他工单
            page.go_back(); page.wait_for_timeout(1400)
            assert "view=project" in page.url, f"{label} 返回项目详情失败：{page.url}"
            page.locator(".pcard.list").nth(1).click()
            page.wait_for_function(f"document.title.includes('{TICKET}')", timeout=10000)
            page.wait_for_timeout(900)
            shot(page, f"{label}-04-ticket.png", steps, "项目工单")
            assert no_hscroll(page), f"{label} 工单页横向溢出"

            if label == "mobile":
                # 底栏「群聊」总览也要真实点开
                page.locator('#tabbar [data-nav="tickets"]').first.click()
                page.wait_for_function("document.title.includes('群聊')", timeout=10000)
                page.wait_for_timeout(900)
                shot(page, "mobile-05-tickets-tab.png", steps, "底栏群聊总览")
                assert no_hscroll(page), "mobile 群聊总览横向溢出"
            ctx.close()

        browser.close()

    report = {
        "base": base, "generated_at": now(), "duration_s": round(time.time() - started, 2),
        "viewports": [{"name": l, "width": w, "height": h} for l, w, h in views],
        "project": PROJECT, "ticket": TICKET,
        "steps": steps, "console_errors": errors,
        "ok": len(steps) >= 8 and not errors,
    }
    (out / "click-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"ok": report["ok"], "steps": len(steps), "errors": errors, "out": str(out)}, ensure_ascii=False))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
