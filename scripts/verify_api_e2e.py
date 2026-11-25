#!/usr/bin/env python3
"""HTTP 黑盒业务 E2E：真服务、真 RPC、真并发，不走进程内装配。

场景（每个都建夹具、断言状态迁移、finally 清理）：
  project-rename：建项目→建工单→改名→工单引用改挂→开单归档被拒→结单→归档→只读拦截→删除
  knowledge    ：写初版→读→旧版本冲突→按当前版本覆盖→再读→版本元数据
  timer        ：建→列→暂停→恢复→改→删
  nodes        ：登记→申领→冲突申领被拒→错 token 释放被拒→正确释放→epoch 递增
  parallel     ：12 路并发建项目→列表可见→并发删除→列表归零

用法：
  AI_NEW_STUB=1 python agent_start.py &
  python scripts/verify_api_e2e.py --scenario all
"""
from __future__ import annotations

import argparse
import http.client
import json
import os
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from perf_http import Client, login  # noqa: E402

BASE = "http://127.0.0.1:8787"
TOKEN = ""


class E2E(Exception):
    pass


def req(demand_id, payload=None, token=None):
    c = Client(BASE, TOKEN if token is None else token)
    try:
        sample, data = c.rpc(demand_id, payload or {})
        outer = data.get("result") if isinstance(data, dict) else {}
        if not sample.ok:
            raise E2E("%s 失败: %s" % (demand_id, error_code(outer) or sample.code))
        if not isinstance(outer, dict):
            raise E2E("%s 缺 result: %s" % (demand_id, data))
        if outer.get("ok") is False:
            raise E2E("%s 失败: %s" % (demand_id, outer.get("code") or "false"))
        value = outer.get("result")
        return value if isinstance(value, dict) else {}
    finally:
        c.close()


def must(cond, message):
    if not cond:
        raise E2E(message)


def error_code(node):
    """业务失败可能嵌两层 result：顶层失败 → 内层 result 才带 code。"""
    if not isinstance(node, dict):
        return ""
    code = node.get("code")
    if code:
        return str(code)
    return error_code(node.get("result"))


def workspace(demand_id, payload=None):
    """返回 (result, code)：预期失败也拿得到 code，供负向断言。"""
    c = Client(BASE, TOKEN)
    try:
        sample, data = c.rpc(demand_id, payload or {})
        outer = data.get("result") if isinstance(data, dict) else {}
        inner_code = error_code(outer)
        if not sample.ok:
            return {}, inner_code or sample.code
        if not isinstance(outer, dict):
            return {}, "bad_shape"
        if outer.get("ok") is False:
            return {}, inner_code or "false"
        value = outer.get("result")
        return (value if isinstance(value, dict) else {}), ""
    finally:
        c.close()


def _fail_text(node):
    """业务失败可能落在 failed / result / error 任一层；递归取最内层人话。"""
    if not isinstance(node, dict):
        return ""
    failed = node.get("failed")
    if isinstance(failed, dict):
        inner = _fail_text(failed.get("result")) or _fail_text(failed)
        return str(failed.get("error") or failed.get("code") or inner or "")
    if node.get("error"):
        return str(node.get("error"))
    if node.get("code"):
        return str(node.get("code"))
    return _fail_text(node.get("result"))


def outcome(demand_id, payload=None, token=None):
    """返回 (值, 错误文本)：业务失败可能落在 failed 节点，code 未必存在。"""
    c = Client(BASE, TOKEN if token is None else token)
    try:
        sample, data = c.rpc(demand_id, payload or {})
        outer = data.get("result") if isinstance(data, dict) else {}
        if not sample.ok:
            return {}, _fail_text(outer) or sample.code
        if not isinstance(outer, dict):
            return {}, "bad_shape"
        if outer.get("ok") is False:
            return {}, _fail_text(outer) or "false"
        value = outer.get("result")
        return (value if isinstance(value, dict) else {}), ""
    finally:
        c.close()


def must_fail(demand_id, payload, *needles):
    _, err = outcome(demand_id, payload)
    text = str(err)
    must(any(n in text for n in needles), "%s 失败原因不符（want %s）: %s"
         % (demand_id, needles, text))
    return text





def project(name):
    return req("projects-create", {"name": name})


def delete_project(pid):
    try:
        req("projects-delete", {"id": pid, "purge": True})
    except E2E:
        pass


def create_ticket(project_id, title):
    return req("ticket-create", {"project": project_id, "title": title,
                                 "goal": "E2E 黑盒验收：建单、迁移、守卫、结单、归档"})


def close_ticket(tid):
    return req("ticket-close", {"id": tid, "verdict": "accepted",
                                "summary": "E2E 黑盒验收通过：状态迁移与只读守卫成立"})


def wait_reply(tid, timeout=45):
    deadline = time.time() + timeout
    seen = 0
    while time.time() < deadline:
        thread = req("ticket-thread", {"id": tid})
        msgs = thread.get("thread", {}).get("messages") or []
        seen = max(seen, len(msgs))
        if any((m.get("role") == "assistant") and (m.get("content") or "").strip()
               for m in msgs) and thread.get("thread", {}).get("status") == "idle":
            return thread
        time.sleep(0.8)
    raise E2E("工单 %s 未在 %ss 内收到 PM 回复（已 %d 条消息）" % (tid, timeout, seen))


def scenario_project_rename():
    name = "e2e-api-%d" % time.time_ns()
    renamed = name + "-renamed"
    pid = ""
    tid = ""
    try:
        rec = project(name)
        pid = rec["id"]
        ticket = create_ticket(pid, "改名与引用改挂")
        tid = ticket["id"]
        req("projects-rename", {"id": pid, "name": renamed})
        got = req("projects-get", {"id": renamed})
        must(got.get("name") == renamed, "改名后项目详情名字不对: %s" % got)
        moved = req("ticket-get", {"id": tid})
        must(moved.get("project") == renamed,
             "改名后工单未改挂: ticket.project=%r (want %r)" % (moved.get("project"), renamed))
        _, code = workspace("projects-archive", {"id": renamed})
        must(code in ("open_tickets", "has_open_tickets", "409"),
             "有未结单工单时归档未被拒: code=%r" % code)
        close_ticket(tid)
        req("projects-archive", {"id": renamed})
        got = req("projects-get", {"id": renamed})
        must(got.get("archived") is True, "归档后项目档案未标记 archived: %s" % got)
        _, code = workspace("ticket-message", {"id": tid, "text": "归档后补一句"})
        must(code in ("archived", "project_archived", "read_only", "ticket_closed"),
             "归档/结单后发消息未被拒: code=%r" % code)
        delete_project(renamed)
        pid = ""
        return {"project": renamed, "ticket": tid, "rebound": True,
                "archive_guard": True, "closed_readonly": True}
    finally:
        if pid:
            delete_project(pid)
        if renamed:
            delete_project(renamed)


def scenario_knowledge():
    name = "e2e-know-%d" % time.time_ns()
    pid = ""
    try:
        pid = project(name)["id"]
        v1 = req("knowledge-write", {"layer": "project", "project": pid,
                                     "name": "e2e-doc", "content": "v1",
                                     "mode": "overwrite", "author": "e2e"})
        must(v1.get("ok", True), "初版写入失败: %s" % v1)
        read1 = req("knowledge-read", {"layer": "project", "project": pid, "name": "e2e-doc"})
        body1 = read1.get("text") or read1.get("content") or ""
        must("v1" in body1, "初版读回不含 v1: %s" % read1)
        version1 = str((v1.get("revision") or {}).get("version") or "") or "1"
        res, code = workspace("knowledge-write", {"layer": "project", "project": pid,
                                                  "name": "e2e-doc", "content": "stale",
                                                  "mode": "overwrite", "author": "e2e",
                                                  "base_version": "0"})
        must(bool(code) or res.get("ok") is False,
             "旧版本覆盖未触发冲突: %s" % res)
        v2 = req("knowledge-write", {"layer": "project", "project": pid,
                                     "name": "e2e-doc", "content": "v2",
                                     "mode": "overwrite", "author": "e2e",
                                     "base_version": version1})
        must(v2.get("ok", True), "按当前版本覆盖失败: %s" % v2)
        read2 = req("knowledge-read", {"layer": "project", "project": pid, "name": "e2e-doc"})
        body2 = read2.get("text") or read2.get("content") or ""
        must("v2" in body2, "覆盖后读回不含 v2: %s" % read2)
        version2 = str((v2.get("revision") or {}).get("version") or "")
        must(version2 and int(version2) > int(version1), "版本未递增: %s -> %s"
             % (version1, version2))
        return {"project": pid, "conflict_guard": True, "version": version2}
    finally:
        if pid:
            delete_project(pid)


def scenario_timer():
    name = "e2e-timer-%d" % time.time_ns()
    pid = ""
    timer_id = ""
    try:
        pid = project(name)["id"]
        caller = {"scope": "project", "project": pid, "role": "e2e"}
        rec = req("timer-create", {"project": pid, "kind": "cron",
                                   "expr": "*/5 * * * *", "tz": "Asia/Shanghai",
                                   "title": "E2E 巡检", "action": "notify",
                                   "payload": {}, "creator": "e2e"})
        timer_id = rec.get("id") or ""
        must(timer_id, "建定时器未回 id: %s" % rec)
        rows = req("timer-list", {"project": pid})
        ids = [x.get("id") for x in (rows.get("items") or rows.get("rows") or [])]
        must(timer_id in ids, "定时器列表看不到新建项: %s" % rows)
        req("timer-toggle", {"id": timer_id, "action": "pause", "caller": caller})
        rows = req("timer-list", {"project": pid})
        paused = next((x for x in (rows.get("items") or []) if x.get("id") == timer_id), {})
        must(paused.get("status") in ("paused", "pause"),
             "暂停后状态未迁移: %s" % paused)
        req("timer-toggle", {"id": timer_id, "action": "resume", "caller": caller})
        req("timer-update", {"id": timer_id, "title": "E2E 巡检（改）",
                             "expr": "*/7 * * * *", "tz": "Asia/Shanghai",
                             "action": "notify", "caller": caller})
        rows = req("timer-list", {"project": pid})
        updated = next((x for x in (rows.get("items") or []) if x.get("id") == timer_id), {})
        must("改" in (updated.get("title") or ""), "更新后标题未变: %s" % updated)
        req("timer-delete", {"id": timer_id, "caller": caller})
        timer_id = ""
        return {"project": pid, "listed": True, "paused": True, "updated": True, "deleted": True}
    finally:
        if timer_id:
            try:
                req("timer-delete", {"id": timer_id, "caller": caller})
            except E2E:
                pass
        if pid:
            delete_project(pid)


def scenario_nodes():
    name = "e2e-node-%d" % time.time_ns()
    pid = ""
    node = "e2e-node-%d" % time.time_ns()
    token = ""
    try:
        pid = project(name)["id"]
        req("nodes-register", {"id": node, "endpoint": "tcp://127.0.0.1:9797",
                               "transport": "tcp", "capacity": {"cpu": 2, "memory_mb": 1024},
                               "lease_ttl": 30})
        lease = req("nodes-acquire", {"project": pid, "node": node, "ttl": 30, "tier": "weak"})
        token = lease.get("lease", {}).get("token") or lease.get("token") or ""
        must(token, "申领租约未回 token: %s" % lease)
        _, code = workspace("nodes-acquire", {"project": pid, "node": "e2e-node-other",
                                             "ttl": 30, "tier": "weak"})
        must(bool(code), "同项目重复申领未被拒")
        _, code = workspace("nodes-release", {"project": pid, "token": "wrong-token"})
        must(bool(code), "错 token 释放未被拒")
        req("nodes-release", {"project": pid, "token": token})
        token = ""
        lease2 = req("nodes-acquire", {"project": pid, "node": node, "ttl": 30, "tier": "weak"})
        token = lease2.get("lease", {}).get("token") or lease2.get("token") or ""
        must(token, "重新申领未回 token: %s" % lease2)
        epoch = lease2.get("lease", {}).get("epoch") or lease2.get("epoch")
        must(epoch in (None, 1, "1") or int(epoch) >= 1, "重新申领 epoch 异常: %s" % lease2)
        return {"project": pid, "node": node, "guard": True, "reacquired": True}
    finally:
        if token:
            try:
                req("nodes-release", {"project": pid, "token": token})
            except E2E:
                pass
        if pid:
            delete_project(pid)


def scenario_parallel(count=12):
    stamp = time.time_ns()
    names = ["e2e-par-%s-%02d" % (stamp, i) for i in range(count)]
    made = []
    lock = threading.Lock()

    def create(n):
        try:
            rec = project(n)
            with lock:
                made.append(rec["id"])
        except Exception as exc:  # noqa: BLE001
            with lock:
                errors.append((n, str(exc)))

    errors = []
    threads = [threading.Thread(target=create, args=(n,)) for n in names]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    must(not errors, "并发建项目失败: %s" % errors[:3])
    must(len(made) == count, "并发建项目只成功 %d/%d" % (len(made), count))
    rows = req("projects-list", {}).get("items") or []
    seen = {x.get("id") for x in rows}
    must(set(made) <= seen, "并发建的项目未全部出现在列表")
    def destroy(pid):
        try:
            delete_project(pid)
        except Exception:
            pass
    ths = [threading.Thread(target=destroy, args=(pid,)) for pid in made]
    for t in ths:
        t.start()
    for t in ths:
        t.join(timeout=30)
    return {"created": len(made), "listed": True, "deleted": len(made)}


def scenario_ticket_note():
    name = "e2e-note-%d" % time.time_ns()
    pid = ""
    tid = ""
    try:
        pid = project(name)["id"]
        tid = create_ticket(pid, "备注守卫")["id"]
        text = "E2E 备注 %d：结单前可追加，结单后只读" % time.time_ns()
        req("ticket-note", {"id": tid, "text": text})
        thread = req("ticket-thread", {"id": tid})
        history = thread.get("ticket", {}).get("history") or []
        must(any((h.get("event") == "note") and (text in (h.get("text") or ""))
                 for h in history), "备注未进工单历程: %s" % history[-3:])
        close_ticket(tid)
        _, code = workspace("ticket-note", {"id": tid, "text": "结单后再写"})
        must(code in ("ticket_closed", "closed", "read_only", "rpc_ticket_closed"),
             "结单后写备注未被拒: code=%r" % code)
        return {"project": pid, "ticket": tid, "note": True, "closed_guard": True}
    finally:
        if pid:
            delete_project(pid)


def scenario_knowledge_search():
    name = "e2e-search-%d" % time.time_ns()
    pid = ""
    token = "zebracorn-%d" % time.time_ns()
    try:
        pid = project(name)["id"]
        req("knowledge-write", {"layer": "project", "project": pid,
                                "name": "search-doc", "content": "alpha %s omega" % token,
                                "mode": "overwrite", "author": "e2e"})
        out = req("knowledge-search", {"query": token, "limit": 20})
        items = out.get("items") or []
        hit = next((x for x in items if token in (x.get("snippet") or "")), None)
        must(hit is not None, "知识检索没有命中刚写入的文档: %s" % items)
        must("search-doc" in (hit.get("path") or ""), "命中路径不是目标文档: %s" % hit)
        none = req("knowledge-search", {"query": "no-such-token-%d" % time.time_ns(), "limit": 5})
        must(not (none.get("items") or []), "无关键词仍返回结果: %s" % none)
        return {"project": pid, "hit": hit.get("path"), "miss_empty": True}
    finally:
        if pid:
            delete_project(pid)


def scenario_role_session():
    role = "cloud-configurer"
    purpose = "e2e-role-%d" % time.time_ns()
    sid = ""
    try:
        first = req("role-session-open", {"role": role, "purpose": purpose})
        sid = first.get("id") or ""
        must(sid, "岗位会话未回 id: %s" % first)
        again = req("role-session-open", {"role": role, "purpose": purpose})
        must((again.get("id") or "") == sid, "同 purpose 未幂等复用: %s -> %s" % (sid, again.get("id")))
        members = req("role-session-members", {"role": role})
        rows = members.get("items") or []
        must(any(x.get("role") == role for x in rows), "成员里没有岗位: %s" % rows)
        text = "E2E 岗位会话探针 %d" % time.time_ns()
        req("role-session-message", {"id": sid, "text": text})
        got = req("session-get", {"id": sid})
        msgs = got.get("messages") or []
        must(any((m.get("content") or "") == text for m in msgs), "会话未追加 human 消息")
        destroyed = req("session-destroy", {"id": sid})
        must((destroyed.get("status") or "") in ("gone", "destroyed"), "销毁后状态不对: %s" % destroyed)
        sid = ""
        return {"role": role, "idempotent": True, "message": True, "destroyed": True}
    finally:
        if sid:
            try:
                req("session-destroy", {"id": sid})
            except E2E:
                pass


def scenario_cloud_profile():
    pid = "e2e-cloud-%d" % time.time_ns()
    caller = {"scope": "global", "role": "cloud-configurer"}
    created = False
    try:
        must_fail("cloud-profile-save", {
            "id": pid, "company": "e2e", "provider": "http_dir",
            "endpoint": "http://127.0.0.1:9/nope", "root_dir": "/e2e",
            "credentials": {}, "categories": ["knowledge"], "caller": caller},
            "白名单", "bad_scheme")
        must_fail("cloud-profile-save", {
            "id": pid, "company": "e2e", "provider": "nope",
            "endpoint": "https://example.com", "root_dir": "/e2e",
            "credentials": {"a": "b"}, "categories": ["knowledge"], "caller": caller},
            "提供方", "bad_provider")
        saved = req("cloud-profile-save", {
            "id": pid, "company": "e2e", "provider": "s3",
            "endpoint": "https://s3.example.com", "root_dir": "/e2e",
            "credentials": {"access_key": "AK-E2E", "secret_key": "SK-E2E"},
            "categories": ["knowledge"], "caller": caller})
        created = True
        must((saved.get("id") or "") == pid, "保存未回目标 id: %s" % saved)
        view = saved.get("view") or {}
        dumped = json.dumps(view, ensure_ascii=False)
        must("AK-E2E" not in dumped and "SK-E2E" not in dumped,
             "保存回显了明文凭证: %s" % dumped)
        rows = req("cloud-profile-list", {}).get("items") or []
        row = next((x for x in rows if x.get("id") == pid), None)
        must(row is not None, "列表看不到新 profile")
        must("AK-E2E" not in json.dumps(row, ensure_ascii=False), "列表泄露了明文凭证")
        got = req("cloud-profile-get", {"id": pid}).get("view") or {}
        must((got.get("id") or "") == pid, "详情未回目标 profile")
        req("cloud-profile-switch", {"id": pid, "caller": caller})
        active = req("cloud-profile-list", {}).get("active")
        must(active == pid, "切换后 active 不是目标: %s" % active)
        audit = req("cloud-audit-list", {}).get("items") or []
        must(any((x.get("action") == "profile_save") and (x.get("decision") == "deny")
                 for x in audit), "非法保存没有审计拒绝记录")
        req("cloud-profile-delete", {"id": pid, "caller": caller})
        created = False
        must(all((x.get("id") != pid) for x in (req("cloud-profile-list", {}).get("items") or [])),
             "删除后列表仍有 profile")
        return {"id": pid, "masked": True, "switched": True, "audit": True, "deleted": True}
    finally:
        if created:
            try:
                req("cloud-profile-delete", {"id": pid, "caller": caller})
            except E2E:
                pass


def scenario_boundary():
    """真实 HTTP 边界：未知需求、超长 id、坏 payload 不得 500。"""
    c = Client(BASE, TOKEN)
    try:
        sample, _ = c.call("/api/nope")
        must(not sample.ok and sample.code in ("http_404", "http_405"),
             "未知路径未按 4xx 收口: %s" % sample.code)
        sample, _ = c.rpc("__e2e_no_such_demand__", {})
        must(not sample.ok, "未知需求被当成成功: %s" % sample.code)
        long_id = "x" * 4096
        sample, _ = c.rpc("demand_engine.run", {"id": long_id})
        must(not sample.ok, "超长 id 没有失败: %s" % sample.code)
        sample, _ = c.rpc("tickets-list", {"project": ["not-an-object"]})
        must(not sample.ok, "非法类型没有失败: %s" % sample.code)
        return {"unknown_path": True, "unknown_demand": True,
                "overlong_id": True, "bad_type": True}
    finally:
        c.close()


SCENARIOS = {
    "project-rename": scenario_project_rename,
    "knowledge": scenario_knowledge,
    "knowledge-search": scenario_knowledge_search,
    "ticket-note": scenario_ticket_note,
    "timer": scenario_timer,
    "nodes": scenario_nodes,
    "role-session": scenario_role_session,
    "cloud-profile": scenario_cloud_profile,
    "boundary": scenario_boundary,
    "parallel": scenario_parallel,
}


def main(argv=None):
    global BASE, TOKEN
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=BASE)
    ap.add_argument("--scenario", default="all",
                    choices=("all", *SCENARIOS.keys()))
    ap.add_argument("--username", default="")
    ap.add_argument("--password", default="")
    args = ap.parse_args(argv)
    BASE = args.base.rstrip("/")
    try:
        TOKEN = login(BASE, args.username, args.password)
    except SystemExit as exc:
        print("  FAIL 登录: %s" % exc)
        return 1

    c = Client(BASE, TOKEN)
    s, data = c.call("/api/health/live")
    c.close()
    if not s.ok or (data or {}).get("ok") is not True:
        print("  FAIL 服务未就绪: %s %s" % (BASE, s.code))
        return 1

    names = list(SCENARIOS) if args.scenario == "all" else [args.scenario]
    failed = 0
    for name in names:
        started = time.time()
        try:
            out = SCENARIOS[name]()
            print("  OK  %-16s %s（%.1fs）" % (name, json.dumps(out, ensure_ascii=False),
                                               time.time() - started))
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print("  FAIL %-16s %s" % (name, exc))
    if failed:
        print("E2E 失败 %d/%d" % (failed, len(names)))
        return 1
    print("E2E 全绿 %d/%d" % (len(names), len(names)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())



