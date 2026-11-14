"""静态架构扫描 / 门禁。

三层对象：
1. 后端模块：每个 hive/modules/<name>.py 是唯一出口；对外 API = 路由 + 工具。
   扫描跨模块 import（应当为零）与 ctx.api("module.method") 调用图。
2. 流程库：data/library/flows/*.json；有 nodes/edges 就按 DAG 检查环。
3. 网页：web/state-machine.json 的状态/事件/DOM 契约 + app.js 的 DOM 引用。

门禁策略：
* 硬错误（会阻塞 git push / 工单结单）：跨模块 import、import 环、网页契约错误、流程环。
* API 调用环：只允许 docs/architecture/api-cycles-baseline.json 登记的已知环；
  新环默认阻塞。--strict-api 会把所有环（包括已知债务）升级为阻塞。
* 拆掉一条边后必须同步删除基线项，避免“基线”变成永久豁免。
"""
from __future__ import annotations

import argparse
import json
import os
import re
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULES_DIR = os.path.join(ROOT, "hive", "modules")
FLOWS_DIR = os.path.join(ROOT, "data", "library", "flows")
WEB_DIR = os.path.join(ROOT, "web")
API_BASELINE = os.path.join(ROOT, "docs", "architecture", "api-cycles-baseline.json")


def _cycle_key(cycle):
    """环的节点顺序可旋转；用字典序最小节点做起点，得到稳定 key。"""
    nodes = list(cycle or [])
    if nodes and nodes[0] == nodes[-1]:
        nodes = nodes[:-1]
    if not nodes:
        return ""
    start = min(range(len(nodes)), key=lambda i: nodes[i])
    return " -> ".join(nodes[start:] + nodes[:start])


def _known_api_cycles():
    try:
        data = json.loads(_read(API_BASELINE))
        return {_cycle_key(c) for c in (data.get("cycles") or []) if c}
    except Exception:
        return set()


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _cycles(graph):
    """返回图中的所有环（简单 DFS；图规模很小）。"""
    found = []
    state = {}
    stack = []

    def dfs(node):
        state[node] = 1
        stack.append(node)
        for nxt in sorted(graph.get(node, [])):
            if nxt not in graph:
                continue
            if state.get(nxt) == 1:
                i = stack.index(nxt)
                cyc = stack[i:] + [nxt]
                key = tuple(sorted(cyc))
                if key not in [tuple(sorted(c)) for c in found]:
                    found.append(cyc)
            elif not state.get(nxt):
                dfs(nxt)
        stack.pop()
        state[node] = 2

    for node in sorted(graph):
        if not state.get(node):
            dfs(node)
    return found


def scan_modules():
    mods = []
    for ent in sorted(os.listdir(MODULES_DIR)):
        d = os.path.join(MODULES_DIR, ent)
        if not os.path.isdir(d) or ent.startswith("__"):
            continue
        entry = os.path.join(d, "__init__.py")
        if not os.path.isfile(entry):
            continue
        files = sorted(fn for fn in os.listdir(d) if fn.endswith(".py"))
        text = "".join(_read(os.path.join(d, fn)) + "\n" for fn in files)
        routes, tools = [], []
        for m in re.finditer(r'\.route\("(?:GET|POST|PUT|DELETE)",\s*"([^"]+)"(?:,\s*name="([^"]+)")?', text):
            routes.append({"path": m.group(1), "name": m.group(2) or m.group(1)})
        for m in re.finditer(r'Tool\("([a-zA-Z_][a-zA-Z0-9_]*)"', text):
            tools.append(m.group(1))
        imports = sorted(set(re.findall(r'from\s+hive\.modules\.([a-zA-Z_][a-zA-Z0-9_]*)', text)))
        imports += sorted(set(re.findall(r'from\s+\.\.([a-zA-Z_][a-zA-Z0-9_]*)', text)))
        calls = sorted(set(re.findall(r'(?:self\.ctx|ctx)\.api\("([a-zA-Z_][a-zA-Z0-9_]*)\.([a-zA-Z_][a-zA-Z0-9_]*)"', text)))
        topics = []
        for raw in sorted(set(re.findall(r'(?:emit|publish|subscribe)\("([^"]+)"', text))):
            if "%" in raw or "{" in raw:
                continue
            from hive.kernel.bus import normalize_topic
            topics.append(normalize_topic(raw))
        bad_topics = [t for t in topics if t != "*" and not re.match(r'^[a-z][a-z0-9_-]*:[a-z0-9_.:*-]+$', t)]
        mods.append({
            "name": ent, "entry": "hive/modules/%s/__init__.py" % ent,
            "internal_files": files, "event_topics": topics, "bad_event_topics": bad_topics,
            "transport": "hub.request",
            "routes": routes, "tools": tools,
            "public_api": ["route:%s %s" % (r["path"], r["name"]) for r in routes] +
                          ["tool:%s" % t for t in tools],
            "cross_imports": imports,
            "api_calls": ["%s.%s" % (a, b) for a, b in calls],
            "private_tests": bool(re.search(r'if\s+__name__\s*==\s*"__main__"', text)),
        })
    return mods


def module_graph(mods):
    calls = defaultdict(set)
    for m in mods:
        for c in m["api_calls"]:
            target = c.split(".", 1)[0]
            if target != m["name"]:
                calls[m["name"]].add(target)
    return {k: sorted(v) for k, v in calls.items()}


def _flow_record(fid, role, nodes, edges, checks, dag=True):
    graph = defaultdict(set)
    node_ids = []
    for n in nodes:
        if isinstance(n, str):
            node_ids.append(n); graph[n]
        elif isinstance(n, dict) and n.get("id"):
            node_ids.append(n["id"]); graph[n["id"]]
            for dep in (n.get("depends_on") or n.get("after") or []):
                graph[dep].add(n["id"])
    for e in edges:
        if isinstance(e, dict):
            a, b = e.get("from"), e.get("to")
        else:
            a, b = (list(e) + [None, None])[:2]
        if a and b:
            graph[a].add(b)
            for x in (a, b):
                if x not in node_ids:
                    node_ids.append(x)
    if not node_ids:
        node_ids = [role or "role"]; graph[node_ids[0]]
    return {"id": fid, "role": role or "", "nodes": len(node_ids), "node_ids": node_ids,
            "edges": sorted([[a, b] for a, bs in graph.items() for b in bs]),
            "cycles": _cycles(graph), "dag": bool(dag), "checks": len(checks or [])}


def scan_flows():
    flows = []
    if os.path.isdir(FLOWS_DIR):
        for fn in sorted(os.listdir(FLOWS_DIR)):
            if not fn.endswith(".json"):
                continue
            path = os.path.join(FLOWS_DIR, fn)
            try:
                data = json.loads(_read(path))
            except Exception as exc:
                flows.append({"id": fn[:-5], "error": "JSON 解析失败: %r" % exc, "cycles": []})
                continue
            flows.append(_flow_record(data.get("id") or fn[:-5], data.get("role") or "",
                                      data.get("nodes") or [], data.get("edges") or [],
                                      data.get("checks") or [], bool(data.get("nodes") or data.get("edges"))))
    # 代码内置的需求级流程也要被扫描；它们不一定已落到 data/library。
    try:
        from hive.modules.library import BUILTIN_FLOWS, REQUIREMENT_FLOWS
        have = {f["id"] for f in flows}
        for fid, spec in dict(BUILTIN_FLOWS, **REQUIREMENT_FLOWS).items():
            if fid in have:
                continue
            flows.append(_flow_record(fid, spec.get("role") or "", spec.get("nodes") or [],
                                      spec.get("edges") or [], spec.get("checks") or [], True))
    except Exception as exc:
        flows.append({"id": "__builtin__", "error": "内置流程读取失败: %r" % exc, "cycles": []})
    return flows


def scan_web():
    from hive.webstate import frontend_source
    app = frontend_source(WEB_DIR)
    html = _read(os.path.join(WEB_DIR, "index.html"))
    spec = json.loads(_read(os.path.join(WEB_DIR, "state-machine.json")))
    markup = html + "\n" + app
    ids = set(re.findall(r'id="([A-Za-z0-9_-]+)"', html))
    ids |= set(re.findall(r'id="([A-Za-z0-9_-]+)"', app))
    ids |= set(re.findall(r"id='([A-Za-z0-9_-]+)'", app))
    refs = set(re.findall(r"\$\('([A-Za-z0-9_-]+)'\)", app))
    refs |= set(re.findall(r"getElementById\('([A-Za-z0-9_-]+)'\)", app))
    missing_refs = sorted(set(re.findall(r"\$\('([A-Za-z0-9_-]+)'\)", app)) - ids)

    # 组件扫描：所有带 id 的按钮/输入控件都必须被脚本显式绑定；
    # 按钮还必须有可读文本或 title/aria-label，避免“空按钮”。
    buttons, unbound_buttons, empty_buttons = 0, [], []
    for m in re.finditer(r"<button([^>]*)>(.*?)</button>", markup, re.S):
        buttons += 1
        attrs, inner = m.group(1), re.sub(r"<[^>]+>", "", m.group(2)).strip()
        im = re.search(r'id="([^"]+)"', attrs)
        if im and re.match(r'^[A-Za-z0-9_-]+$', im.group(1)) and im.group(1) not in refs:
            unbound_buttons.append(im.group(1))
        name = re.search(r'(?:title|aria-label)="([^"]*)"', attrs)
        if not inner and not (name and name.group(1).strip()):
            empty_buttons.append(im.group(1) if im else (attrs[:40] or "(无 id)"))

    controls, unbound_controls = 0, []
    for tag in ("input", "select", "textarea"):
        for m in re.finditer(r"<" + tag + r'([^>]*)>', markup):
            im = re.search(r'id="([^"]+)"', m.group(1))
            if not im or not re.match(r'^[A-Za-z0-9_-]+$', im.group(1)):
                continue
            controls += 1
            if im.group(1) not in refs:
                unbound_controls.append(im.group(1))

    states = spec.get("states") or []
    events = {}
    bad_targets = []
    for s in states:
        for ev, target in (s.get("events") or {}).items():
            events.setdefault(ev, []).append(s.get("id"))
            if target not in {x.get("id") for x in states}:
                bad_targets.append([s.get("id"), ev, target])
    components = spec.get("components") or {}
    component_missing = []
    for cid in components.get("required_ids") or []:
        if cid not in ids:
            component_missing.append(cid)
    try:
        from hive.webstate import validate
        web_ok, web_errors = validate()
    except Exception as exc:
        web_ok, web_errors = False, ["webstate 校验异常: %r" % exc]
    return {"ok": web_ok and not bad_targets and not component_missing
                  and not unbound_buttons and not empty_buttons and not unbound_controls,
            "errors": web_errors + (["事件目标不存在: %s" % x for x in bad_targets] if bad_targets else []) +
                      (["状态机缺少组件 id: %s" % x for x in component_missing] if component_missing else []) +
                      (["按钮未绑定脚本: %s" % x for x in unbound_buttons] if unbound_buttons else []) +
                      (["按钮无文本: %s" % x for x in empty_buttons] if empty_buttons else []) +
                      (["控件未绑定脚本: %s" % x for x in unbound_controls] if unbound_controls else []),
            "states": len(states), "events": len(events),
            "dom_ids": len(ids), "dom_refs": len(refs), "missing_refs": missing_refs,
            "buttons": buttons, "unbound_buttons": unbound_buttons, "empty_buttons": empty_buttons,
            "controls": controls, "unbound_controls": unbound_controls,
            "event_targets_bad": bad_targets,
            "component_ids": len(components.get("required_ids") or []),
            "component_missing": component_missing}


def scan(strict_api=False):
    mods = scan_modules()
    graph = module_graph(mods)
    api_cycles = _cycles({k: v for k, v in graph.items()})
    import_cycles = _cycles({m["name"]: m["cross_imports"] for m in mods})
    flows = scan_flows()
    web = scan_web()
    errors, warnings = [], []
    for m in mods:
        if m["cross_imports"]:
            errors.append("模块 %s 直接 import 其他模块: %s" % (m["name"], m["cross_imports"]))
        if m.get("bad_event_topics"):
            errors.append("模块 %s 事件名不符合 领域:动作: %s" % (m["name"], m["bad_event_topics"]))
    for c in import_cycles:
        errors.append("模块 import 环: %s" % " -> ".join(c))
    known_cycles = _known_api_cycles()
    for c in api_cycles:
        msg = "模块 API 调用环: %s" % " -> ".join(c)
        if strict_api:
            errors.append(msg)
        elif _cycle_key(c) in known_cycles:
            warnings.append(msg + "（已登记债务）")
        else:
            errors.append(msg + "（新增环，未登记；请拆边或显式登记到基线并说明理由）")
    for f in flows:
        if f.get("error"):
            errors.append("流程 %s: %s" % (f["id"], f["error"]))
        for c in f.get("cycles") or []:
            errors.append("流程 %s 的 DAG 环: %s" % (f["id"], " -> ".join(c)))
    for e in web["errors"]:
        errors.append("网页契约: %s" % e)
    result = {
        "root": ROOT,
        "modules": mods,
        "module_graph": graph,
        "api_cycles": api_cycles,
        "import_cycles": import_cycles,
        "flows": flows,
        "web": web,
        "errors": errors,
        "warnings": warnings,
        "ok": not errors,
        "strict_api": strict_api,
    }
    return result


def write_report(result, out_dir=None):
    out_dir = out_dir or os.path.join(ROOT, "docs", "architecture")
    os.makedirs(out_dir, exist_ok=True)
    jpath = os.path.join(out_dir, "arch-report.json")
    with open(jpath, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    lines = [
        "# 架构静态扫描报告", "",
        "生成时间：%s" % __import__("time").strftime("%Y-%m-%dT%H:%M:%SZ", __import__("time").gmtime()),
        "", "## 结论", "",
        "- 门禁：**%s**" % ("通过" if result["ok"] else "失败"),
        "- 模块数：%d；API 调用边：%d；API 环：%d；import 环：%d" % (
            len(result["modules"]), sum(len(v) for v in result["module_graph"].values()),
            len(result["api_cycles"]), len(result["import_cycles"])),
        "- 流程数：%d；流程 DAG 环：%d" % (
            len(result["flows"]), sum(len(f.get("cycles") or []) for f in result["flows"])),
        "- 网页状态：%s（状态 %d / 事件 %d / DOM id %d / 按钮 %d / 控件 %d）" % (
            "一致" if result["web"]["ok"] else "不一致", result["web"]["states"],
            result["web"]["events"], result["web"]["dom_ids"],
            result["web"].get("buttons", 0), result["web"].get("controls", 0)),
        "", "## 模块唯一出口与对外 API", "",
        "| 模块 | 唯一出口 | 路由 | 工具 | 跨模块 import |",
        "| --- | --- | --- | --- | --- |",
    ]
    for m in sorted(result["modules"], key=lambda x: x["name"]):
        lines.append("| %s | `%s` | %d | %d | %s |" % (
            m["name"], m["entry"], len(m["routes"]), len(m["tools"]),
            ", ".join(m["cross_imports"]) or "无"))
    lines += ["", "## 模块 API 依赖（同步调用）", ""]
    for k in sorted(result["module_graph"]):
        lines.append("- `%s` -> %s" % (k, ", ".join("`%s`" % x for x in result["module_graph"][k]) or "（无）"))
    lines += ["", "### API 环", ""]
    if result["api_cycles"]:
        for c in result["api_cycles"]:
            lines.append("- %s" % " -> ".join(c))
    else:
        lines.append("- 无")
    lines += ["", "## 流程 DAG", "", "| 流程 | 节点 | 边 | DAG 字段 | 环 |", "| --- | --- | --- | --- | --- |"]
    for f in sorted(result["flows"], key=lambda x: x["id"]):
        lines.append("| %s | %d | %d | %s | %s |" % (
            f["id"], f.get("nodes", 0), len(f.get("edges") or []),
            "有" if f.get("dag") else "无（仅 role/checks）",
            "有" if f.get("cycles") else "无"))
    lines += ["", "## 网页状态机", ""]
    lines.append("- 状态机校验：%s" % ("通过" if result["web"]["ok"] else "失败"))
    if result["web"]["missing_refs"]:
        lines.append("- app.js 引用但页面/模板中没有的 id：%s" % ", ".join(result["web"]["missing_refs"]))
    if result["web"]["event_targets_bad"]:
        lines.append("- 事件目标错误：%s" % result["web"]["event_targets_bad"])
    lines += ["", "## 门禁错误", ""]
    lines += ["- %s" % e for e in result["errors"]] or ["- 无"]
    lines += ["", "## 已知债务（不阻塞当前门禁）", ""]
    lines += ["- %s" % w for w in result["warnings"]] or ["- 无"]
    with open(os.path.join(out_dir, "arch-report.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return jpath, os.path.join(out_dir, "arch-report.md")


def gate(strict_api=False):
    """给调用方一个不依赖 CLI 的入口；返回 (ok, errors, warnings)。"""
    result = scan(strict_api=strict_api)
    return result["ok"], result["errors"], result["warnings"]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--strict-api", action="store_true")
    args = ap.parse_args(argv)
    result = scan(strict_api=args.strict_api)
    if args.report:
        j, m = write_report(result)
        print("report:", j)
        print("report:", m)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print("ARCH GATE %s" % ("PASS" if result["ok"] else "FAIL"))
        for e in result["errors"]:
            print("  ERROR", e)
        for w in result["warnings"]:
            print("  WARN ", w)
    raise SystemExit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
