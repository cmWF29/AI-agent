#!/usr/bin/env python3
"""全量点击审计：把页面上每一类可点控件真点一遍，逐次断言门禁与状态迁移。

规格来源只有一个：后端下发的 shell.click_machine（console.yaml 的 click_machine 段）。
本脚本不维护第二份状态表，只按规格里声明的 kinds 去页面里取控件、真点击、读 window.uiSnapshot()。

用法：
  python3 scripts/audit_click_machine.py                      # 本地 http://127.0.0.1:8787
  python3 scripts/audit_click_machine.py --base https://104.168.148.112:8788 --user admin --password 123456
  python3 scripts/audit_click_machine.py --views projects,project,home

审计模式 `audit=1` 让前端只过门禁、走一遍进入/回落，不真正执行动作，所以不会写脏数据。
退出码：0 全通过；1 有违规（违规详情见输出与 --report 文件）。
"""
import argparse
import json
import sys
import urllib.parse

from playwright.sync_api import sync_playwright

# 页面里每类控件按选择器取，顺序与前端 CLICK_KINDS 无关：审计按规格 kinds 逐类验证
SELECTORS = {
    "deck": "[data-deck-open]",
    "act": "[data-act]",
    "go": "[data-go]",
    "filter": "[data-filter]",
    "nav": "[data-nav]",           # 侧栏，不在 view-body 内
    "crumb": "[data-crumb]",
    "member": "[data-member]",
    "expand": "[data-expand]",
}
# 深链发现：列表页 -> 详情页 -> 工单/文档，这些页才有堆叠、浮层、折叠、面包屑
DISCOVERY = [("projects", "go"), ("knowledge", "go"), ("project", "go"), ("ticket", "go")]
MODAL_KINDS = ["modal_ok", "modal_cancel", "modal_backdrop"]


def login(base, user, password):
    """取 token：走 demand_engine.run 的 auth-login 需求，与网页用的是同一条链路。"""
    from playwright.sync_api import sync_playwright as _sp  # noqa: F401  (保持单入口)
    import re
    import urllib.request
    import ssl

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    body = json.dumps({"id": "auth-login", "input": {"username": user, "password": password}}).encode()
    req = urllib.request.Request(base + "/api/rpc/demand_engine/run", data=body,
                                 headers={"Content-Type": "text/json"})
    raw = urllib.request.urlopen(req, context=ctx, timeout=30).read().decode("utf-8", "replace")
    m = re.search(r"token: ([A-Za-z0-9_\-]+)", raw)
    if not m:
        raise SystemExit("登录失败：%s" % raw[:200])
    return m.group(1)


def audit_modal(pg, kinds):
    """弹窗三入口：在 idle 必须被拒，在 modal 必须放行。"""
    out = []
    for kind in MODAL_KINDS:
        if kind not in kinds:
            out.append({"kind": kind, "pass": False, "why": "规格未声明该种类"})
            continue
        idle_allowed = pg.evaluate("(k) => uiAllowed(k)", kind)
        pg.evaluate("() => uiTo('modal', 'audit:force')")
        in_modal = pg.evaluate("(k) => uiAllowed(k)", kind)
        pg.evaluate("() => uiTo('idle', 'audit:leave')")
        out.append({"kind": kind, "pass": (not idle_allowed) and in_modal,
                    "why": "idle=%s modal=%s" % (idle_allowed, in_modal)})
    return out


def audit_view(pg, base, view, kinds, per_kind=3, query=""):
    url = "%s/manage.html?view=%s%s&audit=1&perf=0" % (
        base, urllib.parse.quote(view), ("&" + query if query else ""))
    pg.goto(url, wait_until="domcontentloaded")
    pg.wait_for_function("() => window.uiSnapshot && uiSnapshot().machine", timeout=90000)
    pg.wait_for_timeout(600)
    rows = []
    for kind in kinds:
        sel = SELECTORS.get(kind)
        if not sel:
            continue
        scope = "" if kind in ("nav", "crumb") else "#view-body "   # 面包屑在页头
        n = pg.evaluate("([sc, s]) => document.querySelectorAll(sc + s).length", [scope, sel])
        if not n:
            rows.append({"kind": kind, "found": 0, "clicked": 0, "pass": True, "note": "本页无此控件"})
            continue
        clicked, bad = 0, []
        for i in range(min(n, per_kind)):
            before = pg.evaluate("() => uiSnapshot().violations")
            ok = pg.evaluate("""([sc, s, i]) => {
                const el = document.querySelectorAll(sc + s)[i];
                if (!el) return 'gone';
                el.scrollIntoView({block: 'center'});
                el.click();
                return 'clicked';
            }""", [scope, sel, i])
            if ok != "clicked":
                continue
            pg.wait_for_timeout(260)
            after = pg.evaluate("() => ({v: uiSnapshot().violations, s: uiSnapshot().state, b: uiSnapshot().lastBad})")
            clicked += 1
            if after["v"] > before:
                bad.append({"index": i, "violations": after["v"] - before, "lastBad": after["b"], "state": after["s"]})
            elif after["s"] != "idle":
                bad.append({"index": i, "state": after["s"], "why": "点完没回 idle"})
        rows.append({"kind": kind, "found": n, "clicked": clicked, "pass": not bad, "bad": bad})
    return {"view": view, "query": query, "url": url, "rows": rows,
            "violations": pg.evaluate("() => uiSnapshot().violations")}


def real_behaviour(pg, base, view, query):
    """非审计模式验真:堆叠展开/收起、折叠展开、气泡开合 —— 这些不取数、无副作用。"""
    pg.goto("%s/manage.html?view=%s%s&perf=0" % (base, urllib.parse.quote(view),
                                                 "&" + query if query else ""), wait_until="domcontentloaded")
    pg.wait_for_function("() => document.querySelectorAll('#view-body .vsec').length>0", timeout=90000)
    pg.wait_for_timeout(600)
    out = []
    has = pg.evaluate("() => document.querySelectorAll('#view-body [data-deck-open]').length")
    if has:
        before = pg.evaluate("() => [...document.querySelectorAll('#view-body [data-deck]')].map((d) => d.dataset.open)")
        pg.evaluate("() => document.querySelector('#view-body [data-deck-open]').click()")
        pg.wait_for_timeout(300)
        after = pg.evaluate("() => [...document.querySelectorAll('#view-body [data-deck]')].map((d) => d.dataset.open)")
        out.append({"what": "堆叠展开", "pass": before != after, "detail": "%s -> %s" % (before, after),
                    "state": pg.evaluate("() => uiSnapshot().state")})
    n_expand = pg.evaluate("() => document.querySelectorAll('#view-body [data-expand]').length")
    if n_expand:
        f0 = pg.evaluate("() => document.querySelector('#view-body [data-expand]').classList.contains('clamp')")
        pg.evaluate("() => document.querySelector('#view-body [data-expand]').click()")
        pg.wait_for_timeout(200)
        f1 = pg.evaluate("() => document.querySelector('#view-body [data-expand]').classList.contains('clamp')")
        out.append({"what": "折叠展开", "pass": f0 != f1, "detail": "%s -> %s" % (f0, f1),
                    "state": pg.evaluate("() => uiSnapshot().state")})
    return {"view": view, "query": query, "what": out}


def audit_synthetic(pg, base, kinds):
    """没有真实实例的种类：在审计页注入一个同属性按钮，点它验门禁与迁移链路。

    只验解析->门禁->迁移，不改页面数据（审计模式本来就不执行动作）。
    """
    pg.goto(base + "/manage.html?audit=1&perf=0", wait_until="domcontentloaded")
    pg.wait_for_function("() => window.uiSnapshot && uiSnapshot().machine", timeout=90000)
    out = []
    for kind in kinds:
        sel = SELECTORS.get(kind)
        if not sel:
            continue
        attr = sel.strip("[]").split("=")[0]
        before = pg.evaluate("() => uiSnapshot().violations")
        pg.evaluate("""([sel, attr]) => {
            const host = document.querySelector('#view-body');
            const el = document.createElement('button');
            el.setAttribute(attr, attr === 'data-crumb' ? '1' : '1');
            el.className = 'synth-audit';
            el.textContent = '审计注入';
            host.appendChild(el);
        }""", [sel, attr])
        pg.evaluate("(s) => document.querySelector(s).click()", ".synth-audit")
        pg.wait_for_timeout(200)
        after = pg.evaluate("() => ({v: uiSnapshot().violations, s: uiSnapshot().state, b: uiSnapshot().lastBad})")
        pg.evaluate("() => document.querySelector('.synth-audit').remove()")
        out.append({"kind": kind, "synthetic": True, "pass": after["v"] == before and after["s"] == "idle",
                    "detail": "violations %s->%s state=%s %s" % (before, after["v"], after["s"], after["b"])})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8787")
    ap.add_argument("--user", default="")
    ap.add_argument("--password", default="")
    ap.add_argument("--views", default="", help="逗号分隔；默认读外壳菜单里声明 mobile 的全部入口")
    ap.add_argument("--per-kind", type=int, default=3, help="每类控件最多点几个（默认 3）")
    ap.add_argument("--report", default="/tmp/click-audit.json")
    ap.add_argument("--extra", default="", help="额外深链，逗号分隔，如 view=ticket-thread&ticket=t-20261121-0001")
    ap.add_argument("--headful", action="store_true")
    args = ap.parse_args()

    token = login(args.base, args.user, args.password) if args.user else ""
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path="/usr/local/bin/chromium",
                              args=["--no-sandbox"], headless=not args.headful)
        c = b.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True,
                          ignore_https_errors=True)
        if token:
            c.add_cookies([{"name": "hive_token", "value": token, "domain": urllib.parse.urlparse(args.base).hostname,
                            "path": "/", "secure": args.base.startswith("https")}])
            c.add_init_script("localStorage.setItem('ai_new_token', %r)" % token)
        pg = c.new_page()
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)[:160]))

        pg.goto(args.base + "/manage.html?audit=1&perf=0", wait_until="domcontentloaded")
        pg.wait_for_function("() => window.uiSnapshot && uiSnapshot().machine", timeout=90000)
        snap = pg.evaluate("() => uiSnapshot()")
        spec_states, spec_kinds = snap["machine"]["states"], snap["machine"]["kinds"]

        if args.views:
            views = [v.strip() for v in args.views.split(",") if v.strip()]
        else:
            # 视图清单从页面结构取：侧栏每个导航项的 data-nav 就是视图键
            views = pg.evaluate("""() => [...new Set([...document.querySelectorAll('[data-nav]')]
                .map((e) => e.dataset.nav).filter(Boolean))]""")

        # 深链：从列表页把每个 go 入口都走一遍（广度两层），把详情/工单/文档/岗位页全捞进审计范围。
        marks, frontier = [], ["view=projects", "view=knowledge", "view=logs"]
        for _depth in range(2):
            nxt = []
            for seed in frontier:
                pg.goto("%s/manage.html?%s&perf=0" % (args.base, seed), wait_until="domcontentloaded")
                try:
                    pg.wait_for_function("() => document.querySelectorAll('#view-body [data-go]').length > 0",
                                         timeout=45000)
                except Exception:
                    continue
                n = min(pg.evaluate("() => document.querySelectorAll('#view-body [data-go]').length"), 8)
                for i in range(n):
                    pg.goto("%s/manage.html?%s&perf=0" % (args.base, seed), wait_until="domcontentloaded")
                    pg.wait_for_function("(i) => document.querySelectorAll('#view-body [data-go]').length > i",
                                         arg=i, timeout=45000)
                    pg.evaluate("(i) => document.querySelectorAll('#view-body [data-go]')[i].click()", i)
                    pg.wait_for_timeout(2200)
                    q = pg.evaluate("() => location.search.replace(/^\\?/, '')")
                    if q and q != seed and q not in marks and q not in frontier:
                        marks.append(q); nxt.append(q)
                    if len(marks) >= 16:
                        break
                if len(marks) >= 16:
                    break
            frontier = nxt
            if not frontier or len(marks) >= 8:
                break

        if args.extra:
            marks += [x.strip().lstrip("?") for x in args.extra.split(",") if x.strip()]

        report = {"base": args.base, "states": spec_states, "kinds": spec_kinds,
                  "deep_links": marks, "results": [], "real": [], "pageerrors": errs}
        for v in views:
            report["results"].append(audit_view(pg, args.base, v, spec_kinds, args.per_kind))
        for q in marks:
            parts = dict(p.split("=", 1) for p in q.split("&") if "=" in p)
            view = urllib.parse.unquote_plus(parts.pop("view", ""))
            rest = "&".join("%s=%s" % (k, val) for k, val in parts.items())
            report["results"].append(audit_view(pg, args.base, view, spec_kinds, args.per_kind, rest))
            report["real"].append(real_behaviour(pg, args.base, view, rest))

        # 弹窗门禁单独验（弹窗不属于任何视图）
        pg.goto(args.base + "/manage.html?audit=1&perf=0", wait_until="domcontentloaded")
        pg.wait_for_function("() => window.uiSnapshot && uiSnapshot().machine", timeout=90000)
        naked = [k for k in spec_kinds if k not in MODAL_KINDS
                 and not any(row["clicked"] for r in report["results"] for row in r["rows"] if row["kind"] == k)]
        report["synthetic"] = audit_synthetic(pg, args.base, naked)
        modal = audit_modal(pg, spec_kinds)
        report["modal"] = modal
        report["pageerrors"] = errs
        b.close()

    cover = {}
    for r in report["results"]:
        for row in r["rows"]:
            c = cover.setdefault(row["kind"], {"found": 0, "clicked": 0})
            c["found"] += row["found"]
            c["clicked"] += row["clicked"]
    report["coverage"] = cover
    bad = [r for r in report["results"] for row in r["rows"] if not row["pass"]]
    bad += [x for r in report["real"] for x in r["what"] if not x["pass"]]
    bad += [x for x in report["synthetic"] if not x["pass"]]
    bad += [m for m in modal if not m["pass"]]
    if errs:
        bad.append({"pageerror": errs})
    with open(args.report, "w") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print("状态: %s" % " / ".join(spec_states))
    print("可点种类: %s" % " / ".join(spec_kinds))
    print("菜单入口: %d 个；深链: %s" % (len(views), " / ".join(marks) or "无"))
    for r in report["results"]:
        for row in r["rows"]:
            print("%-14s %-8s 命中 %-3s 点击 %-3s %s%s" % (
                r["view"], row["kind"], row["found"], row["clicked"],
                "通过" if row["pass"] else "失败",
                "" if row["pass"] else " <- " + json.dumps(row.get("bad"), ensure_ascii=False)[:120]))
    for r in report["real"]:
        for x in r["what"]:
            print("%-14s 真实手势 %-6s %s %s" % (r["view"], x["what"], "通过" if x["pass"] else "失败", x.get("detail", "")))
    print("覆盖矩阵: %s" % "  ".join("%s=%d/%d" % (k, v["clicked"], v["found"]) for k, v in cover.items()))
    naked = [k for k, v in cover.items() if not v["clicked"] and k not in MODAL_KINDS]
    print("无实例种类（规格已声明、当前页面未出现，属未覆盖）: %s" % (" / ".join(naked) or "无"))
    for x in report["synthetic"]:
        print("%-14s 合成实例  %s %s" % (x["kind"], "通过" if x["pass"] else "失败", x["detail"]))
    print("弹窗门禁: %s" % ", ".join("%s=%s" % (m["kind"], "通过" if m["pass"] else "失败") for m in modal))
    print("报告: %s" % args.report)
    print("结论: %s" % ("全通过" if not bad else "有 %d 处失败" % len(bad)))
    sys.exit(0 if not bad else 1)


if __name__ == "__main__":
    main()
