"""网页状态机契约校验：先维护 web/state-machine.json，再按它改网页。

这不是浏览器里的第二套状态；它是把 app.js 的路由/视图/控件与 JSON 契约做一致性检查，
避免“页面加了按钮但状态转移图没更新”或“图上有状态但网页根本到不了”。
"""
from __future__ import annotations

import json
import os
import re


def load_spec(web_dir=None):
    web_dir = web_dir or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")
    with open(os.path.join(web_dir, "state-machine.json"), encoding="utf-8") as f:
        return json.load(f)


def validate(web_dir=None):
    """返回 (ok, errors)。只做静态契约检查，运行 pytest/run_all 时调用。"""
    web_dir = web_dir or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")
    spec = load_spec(web_dir)
    app = open(os.path.join(web_dir, "app.js"), encoding="utf-8").read()
    html = open(os.path.join(web_dir, "index.html"), encoding="utf-8").read()
    errors = []

    ids = [s.get("id") for s in spec.get("states", [])]
    if not ids:
        errors.append("state-machine.json 没有 states")
    for s in spec.get("states", []):
        if not s.get("render"):
            errors.append("状态 %s 缺 render" % s.get("id"))
        elif s["render"] not in app:
            errors.append("状态 %s 的 render=%s 在 app.js 不存在" % (s["id"], s["render"]))
        for v in s.get("visible", []):
            if ('id="%s"' % v) not in html:
                errors.append("状态 %s 需要 DOM #%s，但 index.html 没有" % (s["id"], v))
    # 路由契约：hash 解析必须认识 project/chat/library/health/versions，且不再有 source 顶层
    for token in ('type === \'project\'', 'type === \'chat\'', 'type === \'library\'', 'type === \'health\''):
        if token not in app:
            errors.append("routeOfHash 缺少路由分支 %s" % token)
    if "type === 'source'" in app:
        errors.append("app.js 仍保留顶部 source 路由")
    # 顶部导航契约
    for tab in (spec.get("forbidden", {}).get("top_tabs") or []):
        if re.search(r'data-tab="%s"' % re.escape(tab), html):
            errors.append("index.html 仍有已废弃顶部 tab: %s" % tab)
    if 'id="groups"' in html:
        errors.append("index.html 仍有全局会话侧栏 #groups")
    if 'id="idle-chip"' in html:
        errors.append("index.html 仍有顶部全局空闲队列 #idle-chip")
    # 项目内必须能到达的模式/源码/队列
    for need in ("pv-backend", "pv-source", "pv-bindsource", "pv-idle", "pv-trace"):
        if ('id="%s"' % need) not in html:
            errors.append("项目页缺少控件 #%s" % need)
    # 群聊 trace 不再有“查看更早报文”入口
    if "查看更早的模块报文" in app:
        errors.append("app.js 仍有“查看更早的模块报文”入口")
    # 交付件下载/预览必须存在
    if "artifact-img" not in app or "art-download" not in app:
        errors.append("app.js 缺少交付件图片预览/下载")
    # 状态机 JSON 中所有 events 的 target 必须存在
    for s in spec.get("states", []):
        for ev, target in (s.get("events") or {}).items():
            if target not in ids:
                errors.append("状态 %s 的事件 %s 指向不存在状态 %s" % (s.get("id"), ev, target))
    return (not errors), errors


if __name__ == "__main__":
    ok, errs = validate()
    print("OK" if ok else "\n".join(errs))
    raise SystemExit(0 if ok else 1)
