#!/usr/bin/env python3
"""接线门禁：表单提交 → 需求 with → API 路由 in，参数必须逐项贯通。

为什么需要这道门禁：
  能力级门禁只看“路由有没有被需求 call 引用”。一个路由被别处调用，参数却没人传，
  仍然会全绿；项目路径 root 就是这样漏掉 UI 入口的。这里从用户真正能点的表单出发，
  把 submit 需求用到的每个路由入参对一遍，缺一个就报红。

豁免必须显式：内部默认参数写进 scripts/wiring-waivers.yaml，带理由；不能静默跳过。

兼容 Python 3.8；只用标准库 + PyYAML。
"""
from __future__ import annotations

import argparse
import glob
import os
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
API_GLOB = str(ROOT / "ai_new/modules/**/data/api.yaml")
DEMANDS = ROOT / "ai_new/modules/agent_common/demand_engine/data/demands"
WAIVERS = ROOT / "scripts/wiring-waivers.yaml"


def _load(path):
    return yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}


def route_inputs():
    """route -> declared input names。"""
    out = {}
    for path in glob.glob(API_GLOB, recursive=True):
        doc = _load(path)
        for name, spec in (doc.get("routes") or {}).items():
            if isinstance(spec, dict):
                out[name] = set((spec.get("in") or {}).keys())
    return out


def demand_calls():
    """demand id -> {route: set(with keys)}。"""
    out = {}
    for path in glob.glob(str(DEMANDS / "*.yaml")):
        doc = _load(path)
        did = doc.get("id") or os.path.basename(path)[:-5]
        calls = {}
        for step in doc.get("do") or []:
            if not isinstance(step, dict) or not step.get("call"):
                continue
            name = str(step["call"])
            with_map = step.get("with") or {}
            calls.setdefault(name, set())
            if isinstance(with_map, dict):
                calls[name] |= set(with_map.keys())
        out[did] = calls
    return out


def form_submits():
    """(form id, demand id, form param keys)。"""
    out = []
    for path in glob.glob(str(DEMANDS / "view-*.yaml")):
        doc = _load(path)
        for form in (doc.get("view") or {}).get("forms") or []:
            submit = form.get("submit") or {}
            if not isinstance(submit, dict) or not submit.get("demand"):
                continue
            params = submit.get("params") or {}
            out.append((str(form.get("id") or ""), str(submit["demand"]),
                        set(params.keys()) if isinstance(params, dict) else set()))
    return out


def waivers():
    """(route, param) -> reason。"""
    doc = _load(WAIVERS) if WAIVERS.exists() else {}
    out = {}
    for row in doc.get("waivers") or []:
        if not isinstance(row, dict):
            continue
        route = str(row.get("route") or "")
        param = str(row.get("param") or "")
        reason = str(row.get("reason") or "")
        if route and param:
            out[(route, param)] = reason
    return out


def scan(root=None):
    root = Path(root or ROOT)
    global API_GLOB, DEMANDS, WAIVERS  # self-test 可换目录
    api = route_inputs()
    calls = demand_calls()
    exempt = waivers()
    problems = []
    covered = set()

    for form_id, demand_id, form_keys in form_submits():
        demand = calls.get(demand_id)
        if demand is None:
            problems.append("表单 %s 提交的需求不存在: %s" % (form_id, demand_id))
            continue
        for route, supplied in demand.items():
            declared = api.get(route)
            if not declared:
                continue
            missing = sorted(declared - supplied - form_keys)
            for param in missing:
                if (route, param) in exempt:
                    covered.add((route, param))
                    continue
                problems.append(
                    "表单 %s → 需求 %s → 路由 %s 缺入参 %s"
                    % (form_id, demand_id, route, param))

    # 能力级“有调用但参数从没人传”的旁证：只对表单触达的路由报，避免把内部默认参数全算红。
    # 表单触达的路由是否缺参数已在上面的逐表单循环覆盖；这里只补一条：
    # 如果表单需求存在但需求本身没有 call 到任何路由，说明提交是空转。
    for form_id, demand_id, _ in form_submits():
        if not calls.get(demand_id):
            problems.append("表单 %s 的需求 %s 没有任何 call" % (form_id, demand_id))

    stale = sorted(set(exempt) - covered)
    for route, param in stale:
        problems.append("豁免已失效（表单路径不再触达或已补参）：%s.%s" % (route, param))
    return problems


def main(argv=None):
    ap = argparse.ArgumentParser(description="表单→需求→API 参数接线门禁")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)
    if args.self_test:
        import tempfile
        global API_GLOB, DEMANDS, WAIVERS
        tmp = Path(tempfile.mkdtemp(prefix="gate-wiring-self-"))
        (tmp / "api").mkdir()
        (tmp / "demands").mkdir()
        (tmp / "api/api.yaml").write_text(
            "routes:\n  demo.create:\n    in:\n      name:\n        req: true\n"
            "      path:\n        req: false\n", encoding="utf-8")
        (tmp / "demands/projects-create.yaml").write_text(
            "id: projects-create\ndo:\n- call: demo.create\n  with:\n    name:\n      get: input.name\n",
            encoding="utf-8")
        (tmp / "demands/view-demo.yaml").write_text(
            "view:\n  forms:\n  - id: demo.new\n    submit:\n      demand: projects-create\n"
            "      params:\n        name: $name\n", encoding="utf-8")
        (tmp / "waivers.yaml").write_text("waivers: []\n", encoding="utf-8")
        API_GLOB = str(tmp / "api/api.yaml")
        DEMANDS = tmp / "demands"
        WAIVERS = tmp / "waivers.yaml"
        bad = scan(tmp)
        if not any("缺入参 path" in x for x in bad):
            print("自检失败：构造的缺参样本没有被抓到")
            return 1
        print("自检通过：缺参样本被抓住")
        return 0
    bad = scan()
    if bad:
        print("接线门禁失败（%d 条）：" % len(bad))
        for item in bad[:30]:
            print("  - " + item)
        return 1
    print("接线门禁通过：表单/需求/API 参数逐项贯通")
    return 0


if __name__ == "__main__":
    sys.exit(main())
