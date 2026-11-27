#!/usr/bin/env python3
"""需求生命周期门禁：入口写需求必须声明"做完没有"，异步交接必须有消费者。

为什么需要这道门禁：
  死代码扫描只能回答"这个符号有没有被引用"，回答不了"用户点完之后，后台的活有没有人接"。
  secretary-intake 既被视图引用、又 callable，因此引用扫描与孤儿路由都判它活着；
  secretary-flush 是 callable 运维入口，也不是孤儿。结果就是"入队有、消费无"全绿上线。

口径：
  1. 所有视图表单 / composer 的 submit 写需求，必须显式声明 completion；
  2. completion: inline 表示请求返回即用户可见的活已经做完；
  3. 异步交接必须写成 {event, consumer}，且：
     - consumer 存在、启用、on 里有该 event、do 非空；
     - event 在 Python 生产代码里既有 hooks.point 注册、又有 hooks.emit 发射；
  4. 未声明、消费者不存在、事件没人发/没人注册都报红，不维护人工豁免清单。

兼容 Python 3.8；只用标准库 + PyYAML。
"""
from __future__ import annotations

import argparse
import glob
import os
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
DEMANDS = ROOT / "ai_new/modules/agent_common/demand_engine/data/demands"


def _load(path):
    return yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}


def _demands():
    out = {}
    for path in sorted(DEMANDS.glob("*.yaml")):
        rec = _load(path)
        out[str(rec.get("id") or path.stem)] = rec
    return out


def entry_demands():
    """视图真正能触发的写需求：表单 submit + composer submit。"""
    out = []
    for path in sorted(DEMANDS.glob("view-*.yaml")):
        view = (_load(path).get("view") or {})
        for form in view.get("forms") or []:
            submit = form.get("submit") or {}
            if submit.get("demand"):
                out.append((str(view.get("key") or path.stem), str(form.get("id") or "form"),
                            str(submit["demand"])))
        for section in view.get("sections") or []:
            submit = section.get("submit") or {}
            if submit.get("demand"):
                out.append((str(view.get("key") or path.stem), str(section.get("kind") or "section"),
                            str(submit["demand"])))
    return out


def _hook_evidence(root):
    """event -> {'point': [file], 'emit': [file]}，只看生产代码。"""
    seen = {}
    pat = re.compile(r"hooks\.(point|emit)\(\s*[\"']([^\"']+)[\"']")
    for path in glob.glob(str(root / "ai_new/modules/**/*.py"), recursive=True):
        if "/private/test_" in path or path.endswith("test_start.py"):
            continue
        rel = os.path.relpath(path, root)
        if "/agent_test/" in rel:
            continue
        for kind, event in pat.findall(Path(path).read_text(encoding="utf-8")):
            seen.setdefault(event, {"point": [], "emit": []})[kind].append(rel)
    return seen


def scan(root=None):
    root = Path(root or ROOT)
    global DEMANDS
    DEMANDS = root / "ai_new/modules/agent_common/demand_engine/data/demands"
    demands = _demands()
    hooks = _hook_evidence(root)
    problems = []
    seen_entries = set()
    for view, form, did in entry_demands():
        if did in seen_entries:
            continue
        seen_entries.add(did)
        rec = demands.get(did)
        if rec is None:
            problems.append("视图 %s 的 %s 提交了不存在的需求: %s" % (view, form, did))
            continue
        if "write" not in (rec.get("tags") or []):
            continue
        where = "视图 %s 的 %s → 需求 %s" % (view, form, did)
        done = rec.get("completion")
        if not done:
            problems.append("%s 缺少 completion：必须声明 inline 或 {event, consumer}" % where)
            continue
        if done == "inline":
            text = " ".join(str(rec.get(k) or "") for k in ("title", "description", "promise")).lower()
            if any(word in text for word in ("入队", "队列", "排队", "queue", "pending")):
                problems.append("%s 声明 inline，但描述里仍是队列/异步语义：要么写清消费者，要么改文案" % where)
            continue
        if not isinstance(done, dict):
            problems.append("%s 的 completion 只能是 inline 或 {event, consumer}" % where)
            continue
        event = str(done.get("event") or "")
        consumer = str(done.get("consumer") or "")
        if not event or not consumer:
            problems.append("%s 的 completion 缺 event 或 consumer" % where)
            continue
        target = demands.get(consumer)
        if target is None:
            problems.append("%s 声明的消费者不存在: %s" % (where, consumer))
            continue
        if not target.get("enabled", True):
            problems.append("%s 声明的消费者未启用: %s" % (where, consumer))
            continue
        if event not in (target.get("on") or []):
            problems.append("%s 声明的消费者 %s 没有挂在 %s 上" % (where, consumer, event))
            continue
        if not target.get("do"):
            problems.append("%s 声明的消费者 %s 没有任何动作" % (where, consumer))
        info = hooks.get(event) or {"point": [], "emit": []}
        if not info["point"]:
            problems.append("%s 的事件 %s 在生产代码里没有 hooks.point 注册" % (where, event))
        if not info["emit"]:
            problems.append("%s 的事件 %s 在生产代码里没有 hooks.emit 发射点" % (where, event))
    return problems


def self_test():
    import tempfile
    tmp = Path(tempfile.mkdtemp(prefix="gate-lifecycle-self-"))
    (tmp / "ai_new/modules/demo").mkdir(parents=True)
    (tmp / "ai_new/modules/demo/__init__.py").write_text(
        "ctx.hooks.point('demo.queued', defer=True)\n"
        "ctx.hooks.emit('demo.queued', {})\n", encoding="utf-8")
    global DEMANDS
    old = DEMANDS
    DEMANDS = tmp / "demands"
    DEMANDS.mkdir()
    (DEMANDS / "view-demo.yaml").write_text(
        "id: view-demo\nview:\n  key: demo\n  sections:\n  - kind: composer\n"
        "    submit: {demand: demo.intake}\n", encoding="utf-8")
    (DEMANDS / "demo.intake.yaml").write_text(
        "id: demo.intake\ntags: [write]\nenabled: true\ncallable: true\n'on': []\ndo: []\n",
        encoding="utf-8")
    (DEMANDS / "demo.consume.yaml").write_text(
        "id: demo.consume\ntags: [write]\nenabled: true\ncallable: false\n"
        "'on': [demo.queued]\ndo:\n- call: demo.flush\n", encoding="utf-8")
    bad = scan(tmp)
    ok_missing = any("缺少 completion" in x for x in bad)
    (DEMANDS / "demo.intake.yaml").write_text(
        "id: demo.intake\ntags: [write]\nenabled: true\ncallable: true\n'on': []\n"
        "completion: {event: demo.queued, consumer: demo.consume}\ndo: []\n",
        encoding="utf-8")
    bad2 = scan(tmp)
    ok_full = not bad2
    (DEMANDS / "demo.consume.yaml").unlink()
    bad3 = scan(tmp)
    ok_no_consumer = any("消费者不存在" in x for x in bad3)
    DEMANDS = old
    if not (ok_missing and ok_full and ok_no_consumer):
        print("自检失败：缺声明/完整链路/消费者缺失 三态未全部命中")
        return 1
    print("自检通过：缺 completion 与缺消费者都会被抓住")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="视图入口需求生命周期门禁")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)
    if args.self_test:
        return self_test()
    bad = scan()
    if bad:
        print("需求生命周期门禁失败（%d 条）：" % len(bad))
        for item in bad[:30]:
            print("  - " + item)
        return 1
    print("需求生命周期门禁通过：每个入口写需求都显式收口，异步交接有消费者与事件发射点")
    return 0


if __name__ == "__main__":
    sys.exit(main())
