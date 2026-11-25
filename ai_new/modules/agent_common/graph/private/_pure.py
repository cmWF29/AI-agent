"""图模式纯函数：并行分支合并、步数上限语义、门禁拒绝原因、嵌套子流程清单归属。

全部纯函数：不读盘、不取时钟、不挂私有状态；合并策略与归属规则由调用方经入参数据驱动。
本模块不引入任何外部图运行时，只把现有 ReAct 循环 / 状态机里已经在跑的模式收成可测纯规则。

模式对照（LangGraph 成熟做法 → 本仓库落点）：
- reducer 合并：同一状态键被并行多路写入时，按声明策略合并（默认标量覆盖、列表追加去重）；
- recursion limit：步数到限是显式的正常收口，不算失败；
- 门禁拒绝原因：把 must 未交齐 / forbid 命中归一成结构化原因，带清单 id 与原文；
- 嵌套子流程：子流程清单归子流程自身校验，父流程只汇总 must id 供回卷展示。
"""
from __future__ import annotations

APPEND = "append"
UNION = "union"
REPLACE = "replace"
CONFLICT = "conflict"
MERGE_POLICIES = (APPEND, UNION, REPLACE, CONFLICT)

# 到限收口的显式语义：与现有 react 行为一致——步数耗尽不是 failed / cancelled，
# 而是正常关闭一轮；上层据 outcome 决定补摘要还是告警。
EXHAUSTED_CLOSE = "exhausted_closed"
RUNNING = "running"


def _as_list(value):
    if isinstance(value, list):
        return list(value)
    if value is None:
        return []
    return [value]


def _dedupe(seq):
    """保序去重：可哈希键用 repr 兜底，清单条目 dict 也能区分。"""
    out, seen = [], set()
    for item in seq:
        key = repr(item)
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _default_policy(left, right):
    """未声明策略时的默认归并：标量覆盖，列表追加去重（LangGraph 默认 reducer 的本仓库口径）。"""
    if isinstance(left, list) or isinstance(right, list):
        return APPEND
    return REPLACE


def _gate_item_id(item):
    if isinstance(item, dict):
        return str(item.get("id") or "")
    return str(item or "")


def _gate_item_text(item):
    if isinstance(item, dict):
        return str(item.get("text") or "")
    return ""


def merge_branch_updates(p):
    """并行分支结果合并（reducer 纯规则）。

    入参：
      state    现状状态 dict（基线）；
      updates  各并行分支的局部更新 dict 列表；非 dict 项忽略；
      policies {键: 策略}，策略见 MERGE_POLICIES；未声明走默认策略。

    策略口径：
      append   列表追加后保序去重；
      union    集合并集，保序去重（活跃状态集合并集用）；
      replace  右值覆盖左值（标量默认）；
      conflict 左右都在且不同则记冲突、保留左值，不静默覆盖。

    回：{state 合并后状态, conflicts 冲突列表, merged_keys 被写入的键（保序）}
    """
    state = p.get("state") or {}
    updates = [u for u in (p.get("updates") or []) if isinstance(u, dict)]
    policies = p.get("policies") or {}
    merged = dict(state)
    conflicts = []
    merged_keys = []
    for upd in updates:
        for key, right in upd.items():
            left = merged.get(key)
            policy = policies.get(key) or _default_policy(left, right)
            if policy not in MERGE_POLICIES:
                raise ValueError("unknown merge policy: %s" % policy)
            if policy == REPLACE:
                merged[key] = right
            elif policy == APPEND:
                merged[key] = _dedupe(_as_list(left) + _as_list(right))
            elif policy == UNION:
                merged[key] = _dedupe(_as_list(left) + _as_list(right))
            else:  # 已校验策略集合只剩 conflict
                policy = CONFLICT
                if key in merged and left != right:
                    conflicts.append({"key": key, "left": left, "right": right})
                else:
                    merged[key] = right
            if key not in merged_keys:
                merged_keys.append(key)
    return {"state": merged, "conflicts": conflicts, "merged_keys": merged_keys}


def step_limit(p):
    """步数（递归）上限求值：显式定义到限语义，不含循环本身。

    入参：steps 已走步数；cap 上限（0 / 缺省 = 无上限）。
    回：
      exhausted  是否到限；
      remaining  剩余步数；无上限时为 None；
      running    是否仍可继续；
      outcome    running / exhausted_closed（到限按正常收口，不算失败）。
    """
    steps = int(p.get("steps") or 0)
    cap = int(p.get("cap") or 0)
    if cap > 0:
        exhausted = steps >= cap
        remaining = max(cap - steps, 0)
    else:
        exhausted = False
        remaining = None
    return {
        "steps": steps,
        "cap": cap,
        "exhausted": exhausted,
        "remaining": remaining,
        "running": not exhausted,
        "outcome": EXHAUSTED_CLOSE if exhausted else RUNNING,
    }


def _resolve_gate(contract, item):
    """在契约 by_id 里按清单 id 反查状态与原文；查不到就原样回传。"""
    gid = _gate_item_id(item)
    if isinstance(item, dict):
        return dict(item)
    for state_rec in (contract or {}).values():
        if not isinstance(state_rec, dict):
            continue
        for section in ("must", "forbid"):
            for entry in (state_rec.get("gate") or {}).get(section) or []:
                if _gate_item_id(entry) == gid:
                    return {"id": gid, "text": _gate_item_text(entry),
                            "state": state_rec.get("id") or state_rec.get("path") or ""}
    return {"id": gid, "text": _gate_item_text(item), "state": ""}


def gate_reasons(p):
    """门禁拒绝原因归一：forbid 命中 / must 未交齐 → 结构化原因列表。

    入参：
      contract 契约 by_id（state 路径 → 状态记录），用于反查清单原文；
      violations forbid 命中项（字符串 id 或 {id,text,state}）；
      missing    未交齐的 must 清单 id 列表。
    回：{reasons: [{kind, state, id, text, detail}]}
    """
    contract = p.get("contract") or {}
    reasons = []
    for v in (p.get("violations") or []):
        resolved = _resolve_gate(contract, v)
        reasons.append({"kind": "forbid", "state": resolved.get("state", ""),
                        "id": resolved.get("id", ""), "text": resolved.get("text", ""),
                        "detail": "命中禁止项"})
    for mid in (p.get("missing") or []):
        resolved = _resolve_gate(contract, mid)
        reasons.append({"kind": "must", "state": resolved.get("state", ""),
                        "id": resolved.get("id", ""), "text": resolved.get("text", ""),
                        "detail": "必备清单未交齐"})
    return {"reasons": reasons}


def subprocess_checklist(p):
    """嵌套子流程的清单归属与父级汇总。

    归属规则（数据驱动，不写死业务流程）：清单归声明它的状态；子流程 gate 在子状态
    活跃 / 离开时由同一迁移规则校验；父流程只汇总子流程 must id 供回卷展示，不替子
    流程判定交齐与否。

    入参：
      parent 父状态记录（可带 ref 引用子流程 id）；
      refs    子流程表 {ref_id: [状态记录, ...]}。
    回：
      ref              引用的子流程 id（无引用为空）；
      children         子流程各状态的 must / forbid 分组；
      owned_child_ids  归子流程自身校验的清单 id；
      rollup_must      父级汇总用的 must id 去重列表。
    """
    parent = p.get("parent") or {}
    refs = p.get("refs") or {}
    ref = parent.get("ref") or ""
    children = []
    owned_child_ids = []
    rollup_must = []
    if ref and isinstance(refs, dict) and ref in refs:
        for st in refs[ref] or []:
            if not isinstance(st, dict):
                continue
            gate = st.get("gate") or {}
            must = list(gate.get("must") or [])
            forbid = list(gate.get("forbid") or [])
            children.append({"ref": ref, "state": st.get("id") or "",
                             "must": must, "forbid": forbid})
            for item in must:
                gid = _gate_item_id(item)
                owned_child_ids.append(gid)
                rollup_must.append(gid)
    return {
        "ref": ref,
        "children": children,
        "owned_child_ids": _dedupe(owned_child_ids),
        "rollup_must": _dedupe(rollup_must),
    }
