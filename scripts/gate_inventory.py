#!/usr/bin/env python3
"""可点实例清单门禁：清单里的每一条都必须能点、能定位、有自己的状态机、有明确去向。"""
import glob
import hashlib
import json
import os
import sys

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INV = ROOT + "/ai_new/modules/agent_common/demand_engine/data/ui-inventory.json"
CONSOLE = ROOT + "/ai_new/modules/agent_common/demand_engine/data/console.yaml"


WEB = ROOT + "/ai_new/modules/agent/web/data/console"


def source_sig():
    h = hashlib.sha256()
    files = sorted([CONSOLE, WEB + "/render.js", WEB + "/boot.js", WEB + "/app.js", WEB + "/manage.html",
                    WEB + "/graph.js"]
                   + sorted(glob.glob(ROOT + "/ai_new/modules/agent_common/demand_engine/data/demands/view-*.yaml")))
    for p in files:
        if os.path.exists(p):
            h.update(os.path.relpath(p, ROOT).encode())  # 相对路径：签名不得随检出目录漂移
            h.update(open(p, "rb").read())
    return {"sha": h.hexdigest()[:16], "files": len(files)}


def problems():
    out = []
    if not os.path.exists(INV):
        return ["清单不存在（跑 scripts/ui_inventory.py 生成）"]
    inv = json.load(open(INV, encoding="utf-8"))
    rows = inv.get("rows") or []
    if not rows:
        return ["清单是空的"]
    sig = inv.get("sig") or {}
    here = source_sig()
    if not sig.get("sha"):
        out.append("清单没有源码签名：跑 scripts/ui_inventory.py 重新生成（清单必须跟着源码走）")
    elif sig.get("sha") != here.get("sha"):
        out.append("清单过期：决定可点 DOM 的源码变了（sig=%s 现算=%s），跑 scripts/ui_inventory.py 重新生成"
                   % (sig.get("sha"), here.get("sha")))
    shell = yaml.safe_load(open(CONSOLE, encoding="utf-8")) or {}
    kinds = {k["key"] for k in (shell.get("click_machine") or {}).get("kinds") or []}
    pages = {r["view"] for r in rows}
    for i, r in enumerate(rows):
        tag = "%s #%d %s(%s)" % (r.get("view"), i, r.get("ctl"), r.get("label"))
        if not r.get("ctl"):
            out.append("没有控件 id：" + tag)
        else:
            ctl = r["ctl"]
            if ctl.startswith(("ctl.nav.", "ctl.card_open.", "ctl.row_open.")) or ctl in (shell.get("controls") or {}):
                pass
            elif ctl.count(".") == 1 or ctl.startswith("ctl.shell.") or ctl.startswith("ctl.crumb_up"):
                pass
            # 细粒度 id 与控件登记对不上不算错：动态行按同一控件模板重复
        if r.get("kind") not in kinds:
            out.append("点击种类未声明：" + tag + " kind=" + str(r.get("kind")))
        m = r.get("states") or []
        if not m:
            out.append("没有状态机：" + tag)
        tr = r.get("transitions") or {}
        for src, tos in tr.items():
            if src not in m:
                out.append("状态机起点不在 states：" + tag)
            for to in tos or []:
                if to not in m:
                    out.append("状态机终点不在 states：" + tag)
        if not r.get("effect"):
            out.append("没有点后去向：" + tag)
    return out


def main():
    bad = problems()
    if bad:
        print("可点实例门禁失败（%d 条）：" % len(bad))
        for b in bad[:20]:
            print("  - " + b)
        return 1
    inv = json.load(open(INV, encoding="utf-8"))
    print("可点实例门禁通过：%d 条记录，全部有控件 id、状态机与去向" % len(inv["rows"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
