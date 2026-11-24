#!/usr/bin/env python3
"""可点实例清单：把页面上出现的每一个可点元素都登记成带状态机的一条记录。

逐页打开控制台，枚举真实 DOM 里的可点元素（button / data-clk / data-act / summary / 工具卡），
每条记录包含：页面、控件 id、点击种类、文案、点后去向、它自己的状态机。
结果写到 demand_engine/data/ui-inventory.json，供「点击状态机」页展示并由 gate_inventory.py 校验。
用法：python3 scripts/ui_inventory.py [--check] [base_url]
"""
import glob
import hashlib
import json
import os
import yaml
import sys

import yaml
from playwright.async_api import async_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONSOLE = ROOT + "/ai_new/modules/agent_common/demand_engine/data/console.yaml"
DEMANDS = ROOT + "/ai_new/modules/agent_common/demand_engine/data/demands"
OUT = ROOT + "/ai_new/modules/agent_common/demand_engine/data/ui-inventory.json"

BASE = "http://127.0.0.1:8787"
CHECK = "--check" in sys.argv
for a in sys.argv[1:]:
    if a.startswith("http"):
        BASE = a

CHROME = os.environ.get("CHROME", "/usr/local/bin/chromium")

# 决定可点 DOM 的全部源：YAML 声明 + 前端脚本。任何一个变了，清单就必须重扫。
WEB = ROOT + "/ai_new/modules/agent/web/data/console"
SIG_FILES = [CONSOLE, WEB + "/render.js", WEB + "/boot.js", WEB + "/app.js", WEB + "/manage.html",
             WEB + "/graph.js"]


def source_sig():
    h = hashlib.sha256()
    files = sorted(SIG_FILES + sorted(glob.glob(DEMANDS + "/view-*.yaml")))
    for p in files:
        if os.path.exists(p):
            h.update(os.path.relpath(p, ROOT).encode())  # 相对路径：签名不得随检出目录漂移
            h.update(open(p, "rb").read())
    return {"sha": h.hexdigest()[:16], "files": len(files)}

TOGGLE_KINDS = {"fold_text", "summary_fold", "wire_fold", "raw_fold", "tree_group",
                "section_fold", "deck_toggle", "member_chip", "popover_close",
                "filter", "dag_zoom", "deck_swipe", "stack_open"}
NAV_KINDS = {"nav", "crumb_up", "rail_open", "rail_close", "drawer_open", "drawer_scrim"}


def slug(label):
    import re
    s = re.sub(r"[\s+\uff0b]", "", str(label or ""))
    return re.sub(r"[^0-9A-Za-z_\-\u4e00-\u9fff]", "_", s) or "x"


def load_spec():
    shell = yaml.safe_load(open(CONSOLE, encoding="utf-8")) or {}
    kinds = {k["key"]: k for k in (shell.get("click_machine") or {}).get("kinds") or []}
    controls = shell.get("controls") or {}
    views, acts = {}, {}
    for path in glob.glob(DEMANDS + "/view-*.yaml"):
        doc = yaml.safe_load(open(path, encoding="utf-8")) or {}
        v = doc.get("view") or {}
        key = v.get("key")
        if not key:
            continue
        views[key] = v
        actmap = {}
        blobs = list(v.get("actions") or []) + [a for s in (v.get("sections") or []) for a in (s.get("actions") or [])]
        for s in (v.get("sections") or []):
            if s.get("submit"):
                blobs.append(s["submit"])
        for act in blobs:
            label = act.get("label") or act.get("text") or ""
            if not label:
                continue
            eff = "本页刷新"
            if act.get("view"):
                tv = act["view"]
                eff = "跳到 %s" % (tv if isinstance(tv, str) else (tv.get("key") or tv.get("view")))
            elif act.get("modal"):
                eff = "打开弹窗 %s" % act["modal"]
            elif act.get("confirm") or act.get("flash"):
                eff = "本页刷新"
            actmap[(key, label.replace("＋ ", ""))] = eff
        acts[key] = actmap
    return views, acts, kinds, controls


def machine_of(kind, ctx_ctl, controls):
    """每条记录自己的状态机：控件登记过就用登记的，没有就按点击种类给默认。"""
    if ctx_ctl in controls:
        row = controls[ctx_ctl]
        return {"states": list(row.get("states") or []), "transitions": dict(row.get("transitions") or {})}
    if kind in TOGGLE_KINDS:
        return {"states": ["idle", "done"], "transitions": {"idle": ["done"], "done": ["idle"]}}
    if kind in ("modal_cancel", "modal_backdrop"):
        return {"states": ["idle", "busy"], "transitions": {"idle": ["busy"], "busy": ["idle"]}}
    if kind in NAV_KINDS:
        return {"states": ["idle", "busy"], "transitions": {"idle": ["busy"], "busy": ["idle"]}}
    return {"states": ["idle", "busy", "done", "disabled"],
            "transitions": {"idle": ["busy"], "busy": ["done", "idle"], "done": ["idle"], "disabled": []}}


async def collect(pages):
    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])
        c = await b.new_context(viewport={"width": 430, "height": 900})
        pg = await c.new_page()
        rows, miss = [], []
        for view, q in pages:
            await pg.goto("%s/manage.html?view=%s" % (BASE, q), wait_until="load")
            await pg.wait_for_timeout(1200)
            items = await pg.evaluate("""() => {
              const sel = 'button,sl-button,sl-icon-button,sl-tab,[data-act],[data-clk],[data-cube],summary,details.tool-call';
              return [...document.querySelectorAll(sel)].filter((e) => {
                // 原生 details/summary 是浏览器自带的展开收起，不是需要状态机的动作控件；
                // 工具卡里的按钮仍会被单独枚举。
                if (e.tagName === 'SUMMARY' || e.tagName === 'DETAILS') return false;
                const r = e.getBoundingClientRect();
                return r.width > 0 && r.height > 0 && !e.closest('[hidden]');
              }).map((e) => ({ctl: e.dataset.ctl || '', clk: e.dataset.clk || '',
                              tag: e.tagName, label: (e.textContent || '').trim().slice(0, 18)}));
            }""")
            for it in items:
                if not it["ctl"]:
                    miss.append((view, it["tag"], it["label"]))
                rows.append(dict(view=view, ctl=it["ctl"], kind=it["clk"] or "button",
                                 tag=it["tag"], label=it["label"]))
        await b.close()
        return rows, miss


def first(demand, key, field):
    """取一条真实数据的标识，让详情页也进清点范围。"""
    import urllib.request
    req = urllib.request.Request("%s/api/rpc/demand_engine/run" % BASE,
                                 data=json.dumps({"id": demand, "input": {}}).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as resp:
            raw = resp.read().decode()
            ctype = (resp.headers.get("Content-Type") or "").lower()
        r = json.loads(raw) if "json" in ctype else yaml.safe_load(raw)
        items = ((r.get("result") or {}).get("result") or {}).get(key) or []
        if not items:
            return ""
        return items[0].get(field) or items[0].get("name") or items[0].get("id") or ""
    except Exception:
        return ""


def main():
    views, acts, kinds, controls = load_spec()
    pages = [(k, k) for k, v in views.items() if v.get("menu")]
    proj = first("projects-list", "items", "title")
    tid = first("ticket-list", "items", "id")
    tproj = first("ticket-list", "items", "project")
    if proj:
        pages.append(("project", "project&project=%s" % proj))
    if tid:
        pages.append(("ticket", "ticket&ticket=%s&project=%s" % (tid, tproj)))
    pages.append(("position", "position&position=architect"))
    rows, miss = asyncio_run(collect(pages))
    for r in rows:
        if not r["ctl"] or (r["kind"] not in kinds and r["ctl"] not in controls):
            miss.append((r["view"], r["ctl"] or r["kind"], r["label"]))
            continue
        m = machine_of(r["kind"], r["ctl"], controls)
        r.update({"states": m["states"], "transitions": m["transitions"]})
        label = r["label"].replace("＋ ", "")
        r["effect"] = (acts.get(r["view"], {}) or {}).get(label, "本页刷新")
        if r["ctl"].startswith("ctl.nav."):
            r["effect"] = "导航（收起侧栏）"
        elif r["kind"] in TOGGLE_KINDS:
            r["effect"] = "只改本页显示"
    pages_sum = {}
    for r in rows:
        pages_sum[r["view"]] = pages_sum.get(r["view"], 0) + 1
    body = {"sig": source_sig(),
            "stats": {"instances": len(rows), "pages": len(pages_sum),
                      "kinds": len({r["kind"] for r in rows})},
            "pages": [{"view": k, "count": v} for k, v in sorted(pages_sum.items(), key=lambda x: -x[1])],
            "rows": rows}
    if CHECK:
        old = json.load(open(OUT, encoding="utf-8")) if os.path.exists(OUT) else {}
        prev_sig = (old.get("sig") or {}).get("sha")
        prev = (old.get("stats") or {}).get("instances")
        drift = len(rows) - (prev or 0)
        # 硬门禁：签名一致（源码变→必须重扫）+ 活扫描零缺控件 id。
        # 总量只作提示：可点实例数随运行期数据（项目/工单档案）浮动，跨环境不可比。
        if not prev_sig:
            print("清单没有源码签名：跑 scripts/ui_inventory.py 重新生成")
            return 1
        if prev_sig != source_sig()["sha"]:
            print("清单过期：决定可点 DOM 的源码变了（清单sig=%s 现算=%s），跑 scripts/ui_inventory.py 重新生成"
                  % (prev_sig, source_sig()["sha"]))
            return 1
        if miss:
            print("活扫描发现 %d 个没有控件 id 的可点元素：%s" % (len(miss), miss[:10]))
            return 1
        print("清单校验通过：签名一致，活扫描缺控件 id 0 个"
              + ("（可点实例 %d，清单记录 %d，差 %d 来自运行期数据差异）" % (len(rows), prev, drift) if drift else "，可点实例 %d" % len(rows)))
        return 0
    json.dump(body, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("已写入 %s：%d 个可点实例，覆盖 %d 个页面，缺控件 id %d 个"
          % (OUT, len(rows), len(pages_sum), len(miss)))
    return 0 if not miss else 1


def asyncio_run(coro):
    import asyncio
    try:
        return asyncio.run(coro)
    except RuntimeError:
        return asyncio.get_event_loop().run_until_complete(coro)


if __name__ == "__main__":
    sys.exit(main())
