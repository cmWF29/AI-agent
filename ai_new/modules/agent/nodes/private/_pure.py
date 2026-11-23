"""节点协调纯计算：注册、心跳、租约、fencing、项目→节点分配、备份台账。

本文件无 IO、不读时钟：时间戳一律由入参 ``now`` 传入；所有返回都是可 JSON
序列化的普通 dict。模块之间不 import，跨模块数据经 api 路由交换。

状态形状（nodes 模块自持 data，不落 projects 记录结构）::

    {
      "nodes": {<node_id>: {id, endpoint, transport, region, capacity, load,
                            registered_at, last_seen, lease_ttl, status}},
      "leases": {<project>: {project, node, token, epoch, state, tier,
                             acquired_at, expires_at, renewed_at, ttl, checkpoint}},
      "backups": {<project>: {project, snapshot_id, created_at, entries, state, note}},
      "migrations": [{project, from_node, to_node, reason, epoch,
                      migrated_at, state, checkpoint, note}]
    }
"""
from __future__ import annotations

DEFAULT_TTL = 30.0
LEASE_HELD = "held"
LEASE_RELEASED = "released"

# 选节点默认权重：容量余量优先，历史持有节点给亲和加成，同区域再加成。
# 权重可由 policy.weights 覆盖；只做纯数值比较，不含业务档案。
DEFAULT_WEIGHTS = {"capacity": 1.0, "history": 2.0, "region": 1.0}

# 迁移台账状态
MIG_DONE = "done"
MIG_FAILED = "failed"


def empty_state():
    """空状态：纯函数不携带默认业务档案。"""
    return {"nodes": {}, "leases": {}, "backups": {}, "migrations": []}


def _ts(now):
    try:
        return float(now or 0.0)
    except (TypeError, ValueError):
        return 0.0


def validate_node(node):
    """节点登记字段校验；返回错误码列表，空列表表示通过。"""
    errors = []
    if not isinstance(node, dict):
        return ["node_not_object"]
    if not str(node.get("id") or "").strip():
        errors.append("missing_id")
    if not str(node.get("endpoint") or "").strip():
        errors.append("missing_endpoint")
    capacity = node.get("capacity")
    if capacity is not None and not isinstance(capacity, dict):
        errors.append("capacity_not_object")
    return errors


def register(state, node, now):
    """登记（或刷新）一个执行节点；state 原地变更，返回结果 dict。

    重复登记同一 node_id：保留首次注册时间，刷新 endpoint/capacity/last_seen。
    """
    now = _ts(now)
    errors = validate_node(node)
    if errors:
        return {"ok": False, "errors": errors}
    nodes = state.setdefault("nodes", {})
    nid = str(node["id"]).strip()
    prev = nodes.get(nid)
    record = {
        "id": nid,
        "endpoint": str(node["endpoint"]).strip(),
        "transport": str(node.get("transport") or "direct"),
        "region": str(node.get("region") or (prev or {}).get("region") or ""),
        "capacity": dict(node.get("capacity") or {}),
        "load": dict((prev or {}).get("load") or node.get("load") or {}),
        "registered_at": (prev or {}).get("registered_at") or now,
        "last_seen": now,
        "lease_ttl": float(node.get("lease_ttl") or (prev or {}).get("lease_ttl")
                           or DEFAULT_TTL),
        "status": "alive",
    }
    nodes[nid] = record
    return {"ok": True, "node": record}


def heartbeat(state, node_id, load, now):
    """心跳：刷新负载与最后见活时间。未知节点报 ``unknown_node``。"""
    now = _ts(now)
    nodes = state.setdefault("nodes", {})
    rec = nodes.get(str(node_id or "").strip())
    if rec is None:
        return {"ok": False, "code": "unknown_node"}
    rec["load"] = dict(load or {})
    rec["last_seen"] = now
    rec["status"] = "alive"
    return {"ok": True, "node": rec}


def sweep_expired(state, now, ttl=None):
    """失联回收：最后见活超过 ttl 的节点置 ``lost``，其持有的租约全部释放。

    返回 ``{state, expired: [node_id], released: [project]}``。租约过期是
    重调度的前提；同一项目在旧租约释放前不会被第二台节点持有（见 acquire）。
    """
    now = _ts(now)
    expired, released = [], []
    for nid, rec in state.get("nodes", {}).items():
        eff = float(ttl or rec.get("lease_ttl") or DEFAULT_TTL)
        if rec["last_seen"] + eff < now:
            rec["status"] = "lost"
            expired.append(nid)
    for project, lease in state.get("leases", {}).items():
        if lease.get("state") == LEASE_HELD:
            holder = state.get("nodes", {}).get(lease["node"])
            if holder is None or holder["status"] == "lost":
                lease["state"] = LEASE_RELEASED
                lease["released_at"] = now
                released.append(project)
    return {"state": state, "expired": expired, "released": released}


def acquire(state, project, node_id, now, ttl=None, tier="weak", checkpoint=None):
    """申领项目租约（项目固定落在一个节点，项目内工单在该节点执行）。

    - 节点未知 / 已失联：拒；
    - 租约仍被别的节点持有：拒（``lease_held``），防双跑；
    - 同节点重复申领：续租，epoch 不变；
    - 接手过期/已释放租约：epoch 单调 +1，签发新 token。

    fencing token 正确性由单调 epoch 保证：token 不要求不可猜测，epoch
    回退即被拒写。
    """
    now = _ts(now)
    project = str(project or "").strip()
    node_id = str(node_id or "").strip()
    if not project or not node_id:
        return {"ok": False, "code": "missing_project_or_node"}
    nodes = state.setdefault("nodes", {})
    rec = nodes.get(node_id)
    if rec is None:
        return {"ok": False, "code": "unknown_node"}
    if rec["status"] == "lost":
        return {"ok": False, "code": "node_lost"}
    lease_ttl = float(ttl or rec.get("lease_ttl") or DEFAULT_TTL)
    leases = state.setdefault("leases", {})
    prev = leases.get(project)
    if prev and prev.get("state") == LEASE_HELD:
        if prev["node"] == node_id:
            prev["expires_at"] = now + lease_ttl
            prev["renewed_at"] = now
            prev["ttl"] = lease_ttl
            return {"ok": True, "lease": prev, "reused": True}
        return {"ok": False, "code": "lease_held", "holder": prev["node"],
                "epoch": prev["epoch"]}
    epoch = (prev or {}).get("epoch") or 0
    epoch += 1
    token = "%s:e%d:%d" % (node_id, epoch, int(now * 1_000_000))
    lease = {
        "project": project,
        "node": node_id,
        "token": token,
        "epoch": epoch,
        "state": LEASE_HELD,
        "tier": tier or "weak",
        "acquired_at": now,
        "expires_at": now + lease_ttl,
        "renewed_at": now,
        "ttl": lease_ttl,
        "checkpoint": checkpoint or None,
    }
    leases[project] = lease
    return {"ok": True, "lease": lease, "reused": False}


def renew(state, project, token, now, checkpoint=None):
    """续租：token 匹配且租约未过期才延后 expires_at；可顺带更新检查点。"""
    now = _ts(now)
    lease = state.setdefault("leases", {}).get(str(project or "").strip())
    if lease is None:
        return {"ok": False, "code": "unknown_project"}
    if lease["token"] != token:
        return {"ok": False, "code": "token_mismatch"}
    if lease["state"] != LEASE_HELD:
        return {"ok": False, "code": "not_held", "state": lease["state"]}
    if now > lease["expires_at"]:
        return {"ok": False, "code": "lease_expired"}
    ttl = float(lease.get("ttl") or DEFAULT_TTL)
    lease["expires_at"] = now + ttl
    lease["renewed_at"] = now
    if checkpoint is not None:
        lease["checkpoint"] = checkpoint
    return {"ok": True, "lease": lease}


def release(state, project, token, now):
    """主动释放租约；token 不匹配拒放（防旧持有者误放新持有者的租约）。"""
    now = _ts(now)
    lease = state.setdefault("leases", {}).get(str(project or "").strip())
    if lease is None:
        return {"ok": False, "code": "unknown_project"}
    if lease["token"] != token:
        return {"ok": False, "code": "token_mismatch"}
    lease["state"] = LEASE_RELEASED
    lease["released_at"] = now
    return {"ok": True, "lease": lease}


def fence_check(state, project, token, epoch):
    """写前 fencing 校验：token 与当前 epoch 都必须吻合，否则拒写。

    脑裂残余窗口内，旧节点凭旧 token 回写时，epoch 已被新租约 +1，此处拒。
    """
    lease = state.get("leases", {}).get(str(project or "").strip())
    if lease is None:
        return {"ok": False, "code": "unknown_project"}
    if lease["token"] != token:
        return {"ok": False, "code": "token_mismatch",
                "current_epoch": lease["epoch"]}
    try:
        epoch_int = int(epoch)
    except (TypeError, ValueError):
        return {"ok": False, "code": "epoch_invalid",
                "current_epoch": lease["epoch"]}
    if epoch_int != lease["epoch"]:
        return {"ok": False, "code": "stale_epoch",
                "current_epoch": lease["epoch"]}
    if lease["state"] != LEASE_HELD:
        return {"ok": False, "code": "not_held"}
    return {"ok": True, "epoch": lease["epoch"]}


def nodes_view(state, now, ttl=None):
    """节点列表视图：健康度按 last_seen + ttl 推导，附带本节点持有的项目。"""
    now = _ts(now)
    held = {}
    for project, lease in state.get("leases", {}).items():
        if lease.get("state") == LEASE_HELD:
            held.setdefault(lease["node"], []).append(project)
    out = []
    for nid, rec in state.get("nodes", {}).items():
        eff = float(ttl or rec.get("lease_ttl") or DEFAULT_TTL)
        health = "alive" if rec["last_seen"] + eff >= now else "lost"
        row = dict(rec)
        row["health"] = health
        row["projects"] = sorted(held.get(nid, []))
        out.append(row)
    return sorted(out, key=lambda r: r["id"])


def assignments_view(state):
    """项目→节点分配表视图（含已释放记录，供审计）。"""
    leases = state.get("leases", {}).values()
    return [dict(l) for l in sorted(leases, key=lambda x: x["project"])]


def project_node(state, project):
    """单项目归属查询；无租约返回 None。"""
    lease = state.get("leases", {}).get(str(project or "").strip())
    if not lease:
        return None
    return {
        "project": lease["project"],
        "node": lease["node"],
        "epoch": lease["epoch"],
        "state": lease["state"],
        "tier": lease.get("tier"),
        "expires_at": lease["expires_at"],
    }


def record_backup(state, project, snapshot):
    """登记一份备份台账（快照文件由 store 能力落地，此处只记元数据）。"""
    backups = state.setdefault("backups", {})
    record = dict(snapshot or {})
    record["project"] = str(project or "").strip()
    backups[record["project"]] = record
    return record


def backups_view(state):
    """备份状态视图。"""
    return [dict(b) for b in sorted(
        state.get("backups", {}).values(), key=lambda x: x.get("project") or "")]


def _rel_ok(rel):
    """快照条目相对路径校验：拒绝绝对路径、盘符、``..`` 穿越片段。"""
    seg = str(rel or "").strip().replace("\\", "/")
    if not seg or seg.startswith("/"):
        return False
    head = seg.split("/")[0]
    if ":" in head:
        return False
    parts = [p for p in seg.split("/") if p not in ("", ".")]
    return bool(parts) and ".." not in parts


def plan_snapshot(project, entries, now):
    """生成快照清单计划：条目逐条做越界校验，拒绝项单列，不混进清单。"""
    now = _ts(now)
    clean, rejected = [], []
    for entry in entries or []:
        if isinstance(entry, dict):
            rel = entry.get("rel")
            digest = entry.get("digest") or ""
        else:
            rel, digest = str(entry), ""
        if _rel_ok(rel):
            clean.append({"rel": rel, "digest": digest})
        else:
            rejected.append(rel)
    manifest = {
        "project": str(project or "").strip(),
        "created_at": now,
        "entries": clean,
        "state": "planned",
    }
    return {"ok": not rejected, "manifest": manifest, "rejected": rejected}


def verify_manifest(manifest, digests):
    """按摘要校验快照清单：缺摘要记 missing，摘要不符记 mismatch。"""
    digests = digests or {}
    missing, mismatch = [], []
    for entry in (manifest or {}).get("entries", []):
        rel = entry["rel"]
        if rel not in digests:
            missing.append(rel)
        elif entry.get("digest") and digests[rel] != entry["digest"]:
            mismatch.append(rel)
    return {"ok": not missing and not mismatch,
            "missing": missing, "mismatch": mismatch}


# ---------------------------------------------------------------- 回迁调度

def _policy(policy):
    """归一调度策略；preempt_back 默认 False（恢复后不自动抢回）。"""
    policy = policy or {}
    weights = dict(DEFAULT_WEIGHTS)
    weights.update(policy.get("weights") or {})
    return {
        "preempt_back": bool(policy.get("preempt_back", False)),
        "region": str(policy.get("region") or ""),
        "weights": weights,
    }


def _slots(node):
    cap = node.get("capacity") or {}
    return float(cap.get("slots") or cap.get("cpu") or 10)


def _running(node):
    load = node.get("load") or {}
    try:
        return float(load.get("running") or 0)
    except (TypeError, ValueError):
        return 0.0


def _headroom(node):
    return max(0.0, _slots(node) - _running(node))


def pick_node(state, project, now, policy=None):
    """按容量余量 + 亲和性给存活节点打分，返回最优候选。

    亲和性规则：
    - history：同项目上次持有节点优先（迁移后倾向稳定，权重默认 2.0）；
    - region：同区域节点优先（权重默认 1.0）；
    - capacity：容量余量（槽位 / CPU 减在跑工单数，权重默认 1.0）。
    权重可由 ``policy.weights`` 覆盖；并列时按节点 id 字典序决胜。
    """
    pol = _policy(policy)
    project = str(project or "").strip()
    prev = state.get("leases", {}).get(project)
    last_holder = prev.get("node") if prev else None
    scored = []
    for nid, rec in state.get("nodes", {}).items():
        if rec.get("status") != "alive":
            continue
        w = pol["weights"]
        reasons = ["headroom=%.1f" % _headroom(rec)]
        score = _headroom(rec) * w["capacity"]
        if last_holder and nid == last_holder:
            score += w["history"]
            reasons.append("history")
        if pol["region"] and rec.get("region") == pol["region"]:
            score += w["region"]
            reasons.append("region")
        scored.append({"node": nid, "score": score, "reasons": reasons,
                       "headroom": _headroom(rec)})
    if not scored:
        return {"ok": False, "code": "no_candidate", "candidates": []}
    scored.sort(key=lambda r: (-r["score"], r["node"]))
    best = dict(scored[0])
    best["all"] = scored
    return {"ok": True, **best}


def idem_key(project, ticket, op, seq):
    """工单动作 / 交付件幂等键：项目 + 工单 + 操作 + 安全点序号。

    同一键的重复产出由既有幂等层识别去重；``seq`` 取检查点序号（提交到
    哪个工单条目 / 交付件版本），跨回迁保持不变。交付件去重另比对内容
    摘要，摘要相同即判重复产出，不二次落库、不重复通知。
    """
    return "%s:%s:%s:%s" % (str(project or "").strip(), str(ticket or "").strip(),
                            str(op or "").strip(), str(seq or "").strip())


def record_migration(state, migration):
    """追加一条迁移台账记录（审计可见：从哪到哪、原因、epoch、时间）。"""
    row = dict(migration or {})
    row["project"] = str(row.get("project") or "").strip()
    state.setdefault("migrations", []).append(row)
    return row


def migrations_view(state):
    """迁移台账视图：按迁移时间倒序。"""
    rows = list(state.get("migrations", []))
    rows.sort(key=lambda x: x.get("migrated_at") or 0, reverse=True)
    return [dict(r) for r in rows]


def reassign(state, project, now, policy=None, candidate=None, reason=None,
             checkpoint=None):
    """下线回迁纯编排：detect → fence → reassign → resume → verify。

    前置：旧租约已被 ``sweep_expired`` 判失联并释放（或本就已释放）。
    默认 ``preempt_back=False``：旧节点恢复后不自动抢回正在被持有的租约；
    仅策略显式放开才允许抢占活租约。

    失败处理：
    - 旧租约仍被存活节点持有且未放开抢回 → ``lease_held``，不产生第二持有者；
    - 无可选节点 → 台账记 ``failed``，项目待下一轮重新调度；
    - 新节点申领失败 → 台账记 ``failed``，原因记入 note；
    - resume / verify 由执行侧在新节点上跑检查点恢复与 fencing 复核，
      失败则释放租约并告警（见报告第八节兜底）。
    """
    now = _ts(now)
    project = str(project or "").strip()
    pol = _policy(policy)
    leases = state.setdefault("leases", {})
    lease = leases.get(project)
    if lease is None:
        return {"ok": False, "code": "unknown_project", "steps": ["detect"]}
    old_node = lease.get("node")
    old_epoch = lease.get("epoch")
    holder = state.get("nodes", {}).get(old_node)
    steps = ["detect"]

    # fence 前置：旧持有者仍存活且持有中，默认不抢活租约
    if (lease.get("state") == LEASE_HELD and holder is not None
            and holder["status"] == "alive"):
        if not pol["preempt_back"]:
            return {"ok": False, "code": "lease_held", "holder": old_node,
                    "epoch": old_epoch, "steps": steps + ["fence-rejected"]}
        steps.append("preempt-back-allowed")

    target = str(candidate or "").strip() or None
    if target is None:
        picked = pick_node(state, project, now, policy)
        if not picked["ok"]:
            row = record_migration(state, {
                "project": project, "from_node": old_node, "to_node": None,
                "reason": reason or "node_lost", "epoch": old_epoch,
                "migrated_at": now, "state": MIG_FAILED,
                "checkpoint": checkpoint or lease.get("checkpoint"),
                "note": "no_candidate: no alive candidate; project pending reschedule",
            })
            return {"ok": False, "code": "no_candidate", "migration": row,
                    "steps": steps + ["reassign-failed"]}
        target = picked["node"]
    steps.append("fence")

    res = acquire(state, project, target, now, tier=lease.get("tier"),
                  checkpoint=checkpoint or lease.get("checkpoint"))
    if not res["ok"]:
        row = record_migration(state, {
            "project": project, "from_node": old_node, "to_node": target,
            "reason": reason or "node_lost", "epoch": old_epoch,
            "migrated_at": now, "state": MIG_FAILED,
            "checkpoint": checkpoint or lease.get("checkpoint"),
            "note": "acquire_failed: %s" % res.get("code"),
        })
        return {"ok": False, "code": res.get("code"), "migration": row,
                "steps": steps + ["reassign-failed"]}
    steps.append("reassign")

    row = record_migration(state, {
        "project": project, "from_node": old_node, "to_node": target,
        "reason": reason or "node_lost", "epoch": res["lease"]["epoch"],
        "migrated_at": now, "state": MIG_DONE,
        "checkpoint": res["lease"].get("checkpoint"),
        "note": "",
    })
    steps.append("resume")
    return {"ok": True, "lease": res["lease"], "migration": row,
            "steps": steps, "previous_epoch": old_epoch}
