"""控件状态机门禁：页面上的每个按钮都必须在 console.yaml 的 controls 里登记。

前端的控件 id 由 render.js 的 ctlOf 用「点击种类 + 标签」算出来（显式 ctl 可覆盖）。
这里用同一套算法扫全部 view-*.yaml，双向比对：
  - 页面有、规格没有 → 加了按钮没登记状态机
  - 规格有、页面没有 → 删了按钮规格没清（或 id 漂移）
另外校验每条规格：状态非空、迁移只指向已声明状态、disabled 是终态。
"""
from __future__ import annotations
import re, sys, glob
import yaml

ROOT = __file__.rsplit("/scripts/", 1)[0]


def ctl_slug(label):
    s = re.sub(r"[\s+\uff0b]", "", str(label or ""))
    return re.sub(r"[^0-9A-Za-z_\-\u4e00-\u9fff]", "_", s) or "x"


def ctl_of(label, kind):
    return "ctl.%s.%s" % (kind, ctl_slug(label))


KIND_BY_SECTION = {"cards": "card_act", "table": "row_act", "kv": "card_act"}


def page_controls():
    """页面实际声明的控件：{(id): {"label":..., "where": [...]}}"""
    found = {}
    pat = ROOT + "/ai_new/modules/agent_common/demand_engine/data/demands/view-*.yaml"
    for path in sorted(glob.glob(pat)):
        doc = yaml.safe_load(open(path, encoding="utf-8")) or {}
        view = doc.get("view") or {}
        name = path.rsplit("/", 1)[-1][5:-5]
        def add(cid, label):
            row = found.setdefault(cid, {"label": label, "where": []})
            if name not in row["where"]:
                row["where"].append(name)
        for act in view.get("actions") or []:
            add(ctl_of(act.get("label"), "head_act"), act.get("label"))
        for sec in view.get("sections") or []:
            kind = KIND_BY_SECTION.get(sec.get("kind"), "card_act")
            for act in sec.get("actions") or []:
                add(act.get("ctl") or ctl_of(act.get("label"), kind), act.get("label"))
            if sec.get("submit"):
                sub = sec["submit"]
                add(sub.get("ctl") or ctl_of(sub.get("label"), "composer_send"), sub.get("label"))
            if sec.get("voice"):
                v = sec["voice"]
                add(v.get("ctl") or ctl_of(v.get("label"), "composer_voice"), v.get("label"))
    return found


def spec_controls():
    doc = yaml.safe_load(open(ROOT + "/ai_new/modules/agent_common/demand_engine/data/console.yaml",
                              encoding="utf-8")) or {}
    return doc.get("controls") or {}


def problems():
    out = []
    page, spec = page_controls(), spec_controls()
    for cid in sorted(set(page) - set(spec)):
        out.append("页面有、规格未登记（补 console.yaml controls）: %s (%s)" % (cid, page[cid]["label"]))
    for cid in sorted(set(spec) - set(page)):
        out.append("规格有、页面已无（删按钮要同步删规格）: %s" % cid)
    for cid, row in spec.items():
        states = [str(s) for s in (row.get("states") or [])]
        if not states:
            out.append("%s 没声明 states" % cid)
        trans = row.get("transitions") or {}
        for src, tos in trans.items():
            if str(src) not in states:
                out.append("%s 的迁移起点 %s 不在 states" % (cid, src))
            for to in tos or []:
                if str(to) not in states:
                    out.append("%s 的迁移终点 %s 不在 states" % (cid, to))
        if states and "disabled" in states and (trans.get("disabled") or []):
            out.append("%s 的 disabled 必须是无出边终态" % cid)
        if row.get("kind") and not str(row["kind"]).isascii():
            out.append("%s 的 kind 必须是点击种类（head_act/card_act/row_act/...）" % cid)
    return out


def main():
    p = problems()
    if p:
        print("控件状态机门禁未通过：")
        for x in p:
            print("  - " + x)
        return 1
    print("控件状态机门禁通过：%d 个控件全部登记" % len(spec_controls()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
