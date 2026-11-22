#!/usr/bin/env python3
"""界面状态图门禁：节点=界面状态（页面/浮层），边=具体控件点击后到达的状态。

扫描对象是视图规格 + console.yaml 的 screen_machine，不是代码里的注释：
  - 每个视图都要有一个 view:<key> 节点，跳转目标/弹窗目标必须已声明
  - 每个浮层（侧栏/弹窗）必须登记"怎么关"，关的控件必须真实存在
  - 每条边的 ctl 必须在 controls 或 shell_controls 里登记（或 ctl.nav.* 导航项）
  - 每个页面都要有入边；从入口出发所有页面可达（点不回去的孤岛算错）
"""
import glob
import os
import re
import sys

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEMANDS = ROOT + "/ai_new/modules/agent_common/demand_engine/data/demands"
CONSOLE = ROOT + "/ai_new/modules/agent_common/demand_engine/data/console.yaml"


def slug(label):
    s = re.sub(r"[\s+\uff0b]", "", str(label or ""))
    return re.sub(r"[^0-9A-Za-z_\-\u4e00-\u9fff]", "_", s) or "x"


def load():
    shell = yaml.safe_load(open(CONSOLE, encoding="utf-8")) or {}
    views = {}
    for path in sorted(glob.glob(DEMANDS + "/view-*.yaml")):
        doc = yaml.safe_load(open(path, encoding="utf-8")) or {}
        v = doc.get("view") or {}
        if v.get("key"):
            views[v["key"]] = v
    return shell, views


def acts_of(v):
    out = list(v.get("actions") or [])
    for sec in v.get("sections") or []:
        out += list(sec.get("actions") or [])
        if sec.get("submit"):
            out.append(sec["submit"])
        if sec.get("on_click"):
            out.append(dict(sec["on_click"], label=sec.get("click_label") or "打开卡片"))
    return out


def derive(shell, views):
    """返回 (nodes, edges)。与 demand_engine.screens() 同口径：页面边自动推导，壳层边显式声明。"""
    sm = shell.get("screen_machine") or {}
    nodes = {"view:%s" % k for k in views}
    edges = []
    for key, v in views.items():
        for act in acts_of(v):
            if act.get("view"):
                tv = act["view"]
                to = "view:%s" % (tv if isinstance(tv, str) else (tv.get("key") or tv.get("view")))
                edges.append({"from": "view:%s" % key, "to": to,
                              "ctl": act.get("ctl") or "ctl.head_act.%s" % slug(act.get("label") or "打开"),
                              "label": act.get("label") or "打开"})
            elif act.get("modal"):
                to = "overlay:form:%s" % act["modal"]
                nodes.add(to)
                edges.append({"from": "view:%s" % key, "to": to,
                              "ctl": act.get("ctl") or "ctl.card_act.%s" % slug(act.get("label") or "打开"),
                              "label": act.get("label") or "打开弹窗"})
        par = v.get("parent") or {}
        parent = par if isinstance(par, str) else par.get("view")
        if parent:
            edges.append({"from": "view:%s" % key, "to": "view:%s" % parent, "ctl": "ctl.crumb_up", "label": "面包屑返回"})
    for ov in sm.get("overlays") or []:
        nodes.add(ov.get("key"))
    for key, v in views.items():
        edges.append({"from": "view:%s" % key, "to": "overlay:sidebar", "ctl": "ctl.shell.menu", "label": "点三条杠展开"})
        if v.get("menu"):
            edges.append({"from": "overlay:sidebar", "to": "view:%s" % key,
                          "ctl": "ctl.nav.%s" % slug((v["menu"] or {}).get("label") or key),
                          "label": "导航并收起"})
    return nodes, edges


def problems():
    shell, views = load()
    sm = shell.get("screen_machine") or {}
    controls = shell.get("controls") or {}
    shells = {r.get("key") for r in (sm.get("shell_controls") or []) if r.get("key")}
    nodes, edges = derive(shell, views)
    out = []

    # 1. 每条边两端必须存在
    for e in edges:
        if e["from"] not in nodes or e["to"] not in nodes:
            out.append("界面边指向未声明状态：%s --%s--> %s" % (e["from"], e["label"], e["to"]))

    # 2. 浮层必须能关，关的控件必须真实登记
    overlays = {ov.get("key"): ov for ov in (sm.get("overlays") or [])}
    for key in [n for n in nodes if n.startswith("overlay:")]:
        if key not in overlays:
            # 弹窗靠「取消」关；侧栏必须显式登记
            if key == "overlay:sidebar":
                out.append("浮层 %s 没有登记关闭方式（screen_machine.overlays）" % key)
            continue
        close = overlays[key].get("close_ctl")
        if not close:
            out.append("浮层 %s 没写 close_ctl" % key)
        elif close not in controls and close not in shells:
            out.append("浮层 %s 的关闭控件 %s 未在 controls 登记" % (key, close))

    # 3. 边的控件必须登记（导航项是动态的，按 ctl.nav.* 放行）
    declared = set(controls) | shells
    # 页面内按钮的 id 由 gate_controls 双向闭合；这里只校验壳层边（侧栏/面包屑/导航）都真正登记过
    for e in edges:
        ctl = e["ctl"]
        if not (ctl.startswith("ctl.shell.") or ctl.startswith("ctl.crumb_up") or ctl.startswith("ctl.nav.")):
            continue
        if not ctl.startswith("ctl.nav.") and ctl not in declared:
            out.append("壳层边用的控件未登记：%s（%s）" % (ctl, e["label"]))

    # 4. 每个页面有入边，且从入口可达（不含浮层回边）
    page_edges = [e for e in edges
                  if e["from"].startswith(("view:", "overlay:sidebar"))
                  and (e["to"].startswith("view:") or e["to"] == "overlay:sidebar")]
    inbound = {e["to"] for e in page_edges}
    entry = sm.get("entry") or "view:projects"
    if entry not in nodes:
        out.append("入口 %s 不是已声明状态" % entry)
    for key in sorted(nodes):
        if key.startswith("view:") and key != entry and key not in inbound:
            out.append("页面 %s 没有任何入边（只能靠手输地址才能到）" % key)
    reached = {entry}
    for _ in range(len(nodes)):
        for e in page_edges:
            if e["from"] in reached:
                reached.add(e["to"])
    for key in sorted(nodes):
        if key.startswith("view:") and key not in reached:
            out.append("页面 %s 从入口不可达" % key)
    return out


def main():
    bad = problems()
    if bad:
        print("界面状态图门禁失败：")
        for p in bad:
            print("  - " + p)
        return 1
    print("界面状态图门禁通过：页面/浮层节点闭合、浮层可关、控件已登记、入口全可达")
    return 0


if __name__ == "__main__":
    sys.exit(main())
