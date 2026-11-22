#!/usr/bin/env python3
"""运维指标门禁：统计条只许出现 ops-metrics.yaml 里登记过的指标，且每个指标的取数源必须真实存在。

三道检查：
  1. ops-metrics.yaml 与 view-ops 的统计行一一对应（顺序、label、value 全等）；
  2. value 里的 `data.overview.<as>`，<as> 必须是 ops-overview 的 do 树里真的取回的源；
  3. 指标不许重复，key 必须有；没有数据源的指标不许硬塞。
"""
import glob
import os
import re
import sys

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEM = ROOT + "/ai_new/modules/agent_common/demand_engine/data/demands"
METRICS = ROOT + "/ai_new/modules/agent_common/demand_engine/data/ops-metrics.yaml"


def rows_of_view():
    doc = yaml.safe_load(open(DEM + "/view-ops.yaml", encoding="utf-8")) or {}
    for sec in (doc.get("view") or {}).get("sections") or []:
        if sec.get("kind") == "stats":
            return sec.get("rows") or []
    return []


def sources_of_overview():
    doc = yaml.safe_load(open(DEM + "/ops-overview.yaml", encoding="utf-8")) or {}
    srcs = set()
    for stmt in doc.get("do") or []:
        if stmt.get("as"):
            srcs.add(str(stmt["as"]))
    return srcs


def demand_ids():
    ids = set()
    for f in glob.glob(DEM + "/*.yaml"):
        d = yaml.safe_load(open(f, encoding="utf-8")) or {}
        if d.get("id"):
            ids.add(str(d["id"]))
    return ids


def problems():
    out = []
    metrics = (yaml.safe_load(open(METRICS, encoding="utf-8")) or {}).get("metrics") or []
    rows = rows_of_view()
    srcs = sources_of_overview()
    if not metrics:
        return ["ops-metrics.yaml 没有 metrics"]
    if len(metrics) != len(rows):
        out.append("指标数 %d 与统计行数 %d 不一致" % (len(metrics), len(rows)))
    for m, r in zip(metrics, rows):
        if m.get("label") != r.get("label") or m.get("value") != r.get("value"):
            out.append("指标 %s 与统计行不一致：%s/%s vs %s/%s"
                       % (m.get("key"), m.get("label"), m.get("value"), r.get("label"), r.get("value")))
        if not m.get("key"):
            out.append("指标没有 key：%s" % m.get("label"))
        root = re.match(r"^data\.overview\.([A-Za-z0-9_]+)", str(m.get("value") or ""))
        if not root:
            out.append("指标 %s 的 value 不是 data.overview.<as> 形式" % m.get("key"))
        elif root.group(1) not in srcs:
            out.append("指标 %s 引用了 ops-overview 没取的源 %s" % (m.get("key"), root.group(1)))
    keys = [m.get("key") for m in metrics]
    if len(set(keys)) != len(keys):
        out.append("指标 key 有重复：%s" % keys)
    need = {"projects", "tickets", "sessions"}
    miss = need - set(keys)
    if miss:
        out.append("核心指标缺失（运维至少要有项目/工单/会话）：%s" % sorted(miss))
    return out


def main():
    bad = problems()
    if bad:
        print("运维指标门禁失败：")
        for b in bad:
            print("  - " + b)
        return 1
    metrics = (yaml.safe_load(open(METRICS, encoding="utf-8")) or {}).get("metrics") or []
    print("运维指标门禁通过：%d 个指标全部有据可查、取数源真实存在" % len(metrics))
    return 0


if __name__ == "__main__":
    sys.exit(main())
