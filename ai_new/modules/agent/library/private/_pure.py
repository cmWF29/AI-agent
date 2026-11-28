"""岗位库纯函数：种子与用户记录的合并、查询、成形。不读盘、不取时间。"""
from __future__ import annotations

def _glob_one(text, pattern):
    """`*` `?` 通配，纯字符比较，不借标准库。"""
    if not pattern:
        return text == ""
    head, rest = pattern[0], pattern[1:]
    if head == "*":
        if not rest:
            return True
        for i in range(len(text) + 1):
            if _glob_one(text[i:], rest):
                return True
        return False
    if head == "?":
        return bool(text) and _glob_one(text[1:], rest)
    return bool(text) and text[0] == head and _glob_one(text[1:], rest)


def _glob(path, pattern):
    parts = [p for p in pattern.split("/") if p not in ("", ".")]
    segs = [s for s in path.split("/") if s not in ("", ".")]
    return _glob_path(segs, parts)


def _glob_path(segs, parts):
    if not parts:
        return not segs
    head, rest = parts[0], parts[1:]
    if head == "**":
        for i in range(len(segs) + 1):
            if _glob_path(segs[i:], rest):
                return True
        return False
    return bool(segs) and _glob_one(segs[0], head) and _glob_path(segs[1:], rest)




def _records(p):
    seed = p.get("seed") or {}
    user = p.get("user") or {}
    kind = p.get("kind") or "roles"
    seed_recs = seed.get(kind) or []
    # 种子定义的条目恒以种子为准，用户覆盖层同名副本不挤掉种子契约；
    # 覆盖层只登记运行时新增的自建条目。
    protected = {r.get("id") for r in seed_recs if r.get("id")}
    out = {rid: dict(rec) for rid, rec in user.items()}
    for rec in seed_recs:
        rid = rec.get("id")
        if not rid:
            continue
        out[rid] = dict(rec, builtin=True)
    return out


def _note_ok(notes, min_len):
    """结论备注达标：存在至少一条达到最小长度的非空备注。

    条目可为纯文本；dict 条目按 event 过滤（event 存在且非 note 的系统事件不计）。
    """
    for n in notes or []:
        if isinstance(n, dict):
            if n.get("event") and n.get("event") != "note":
                continue
            txt = str(n.get("text") or "")
        else:
            txt = str(n or "")
        if len(txt.strip()) >= int(min_len or 1):
            return True
    return False


def _check_desc(c, tpl):
    """单条流程检查规则翻成可读中文；形状来自 flows 记录，缺字段不报错。"""
    tpl = tpl or {}
    kind = c.get("kind")
    paths = c.get("paths") or []
    joined = "、".join(paths)
    minb = c.get("min_bytes")
    if kind == "contains":
        head = (tpl.get("check_contains") or "").format(text=c.get("text") or "")
    elif kind == "note":
        head = tpl.get("check_note") or ""
    else:
        match = c.get("match") or "all"
        if match == "any":
            head = (tpl.get("check_any") or "").format(paths=joined)
        else:
            head = (tpl.get("check_all") or "").format(paths=joined)
    if minb:
        head += (tpl.get("check_min_bytes") or "").format(minb=minb)
    return head


def _position(rec, flow, prompt_text="", tpl=None):
    """岗位 = 系统提示词引用 + 红线/必做 + 工具清单 + 自己的状态机与验收检查。

    状态集/转移/检查项直接写在岗位记录里（checks/states/kind），不再另存流程实体；
    只有被多个岗位复用的子流程才留在流程库，靠状态节点 ref 指过去。
    正文取提示词文件内容；提示词归属模块由记录 prompt_module 标注。
    """
    tpl = tpl or {}
    flow = flow or rec
    checks = [dict(c, desc=_check_desc(c, tpl)) for c in (flow.get("checks") or [])]
    stages = flow.get("states") or flow.get("stages") or []
    must_outputs = []
    for c in checks:
        must_outputs.extend(c.get("paths") or [])
    flow_id = rec.get("flow") or flow.get("id") or ""
    return {"id": rec.get("id"), "cn": rec.get("cn"),
            "prompt_file": rec.get("prompt_file"),
            "prompt_module": rec.get("prompt_module") or "agent/library",
            "prompt": prompt_text or "",
            "must_outputs": must_outputs,
            "forbidden": rec.get("forbidden") or [],
            "must_dos": rec.get("must_dos") or [],
            "tools": rec.get("tools") or [],
            "flow_id": flow_id,
            "stages": stages,
            "skill": rec.get("skill") or "",
            "builtin": bool(rec.get("builtin")),
            "readonly": bool(rec.get("readonly")),
            "system": bool(rec.get("system")),
            "flow": {"id": flow.get("id") or flow_id,
                     "cn": flow.get("cn") or "",
                     "checks": checks,
                     "states": stages}}


def reviewp(p):
    """一轮收尾评审：缺口清单 + 已回催次数 → 三态判定（纯计算，不带时钟）。

    pass      没有缺口，本轮交付达标；
    repush    有缺口且未超上限：计数 +1，交回催缺口清单；
    exhausted 有缺口但重试已到上限：不再催，留卡点交上层裁决。
    重试上限由需求层从配置传入，纯函数不持有策略默认值。
    """
    missing = p.get("missing") or []
    retries = int(p.get("retries") or 0)
    limit = int(p.get("max_retries"))
    text = "; ".join(_gap_text(g) for g in missing)
    if not missing:
        return {"verdict": "pass", "missing": [], "missing_text": "",
                "retries": retries, "repush": []}
    if retries < limit:
        return {"verdict": "repush", "missing": missing, "missing_text": text,
                "retries": retries + 1, "repush": missing}
    return {"verdict": "exhausted", "missing": missing, "missing_text": text,
            "retries": retries, "repush": []}


def _collect_ids(nodes, prefix, refs, alias):
    for node in nodes or []:
        if not isinstance(node, dict):
            continue
        nid = node.get("id")
        if not nid:
            continue
        path = node.get("path") or (nid if not prefix else prefix + "." + nid)
        alias[nid] = path
        sub = node.get("children")
        if node.get("ref") and refs:
            sub = refs[node["ref"]]
        _collect_ids(sub, path, refs, alias)


def _flatten_states(nodes, prefix, depth, refs, out, parents, children, depths):
    alias = {}
    _collect_ids(nodes, prefix, refs, alias)
    for node in nodes or []:
        if not isinstance(node, dict):
            continue
        nid = node.get("id")
        if not nid:
            continue
        path = node.get("path") or (nid if not prefix else prefix + "." + nid)
        rec = dict(node)
        rec["path"] = path
        ref_id = node.get("ref")
        nexts = []
        for x in node.get("next") or []:
            if ref_id and x == ref_id and refs and refs[ref_id]:
                first = refs[ref_id][0]
                nexts.append(path + "." + (first.get("id") or ""))
            else:
                nexts.append(alias.get(x, x))
        rec["next"] = nexts
        if prefix:
            parents[path] = prefix
        children.setdefault(path, [])
        depths[path] = depth
        out.append(rec)
        if prefix:
            children[prefix].append(path)
        sub = node.get("children")
        if node.get("ref") and refs:
            sub = refs[node["ref"]]
        _flatten_states(sub, path, depth + 1, refs, out, parents, children, depths)


def _active_list(p):
    """归一活跃状态集合：active 列表优先；否则回退单值 stage。"""
    act = p.get("active")
    if isinstance(act, list):
        return [str(x).strip() for x in act if str(x).strip()]
    stage = str(p.get("stage") or "").strip()
    return [stage] if stage else []


def _check_missing(checks, files, contents, tpl, notes=None):
    """单状态交付件条件判定：复用 glob/contains/note 规则，返回未达标项。

    只校验交付件是否落盘达标，不做任何语义判断；规则形状来自流程记录。
    notes 为本轮结论备注条目（dict 含 text 或字符串），供 note 类检查依据。
    """
    missing = []
    for c in checks:
        kind = c.get("kind")
        if kind == "glob":
            paths = c.get("paths") or []
            match = c.get("match") or "all"
            if match == "any":
                if not any(any(_glob(f, pat) for pat in paths) for f in files):
                    missing.append({"kind": kind, "paths": paths, "match": match,
                                    "reason": tpl.get("missing_any") or ""})
            else:
                for pat in paths:
                    if not any(_glob(f, pat) for f in files):
                        missing.append({"kind": kind, "path": pat, "match": match})
        elif kind == "contains":
            text = c.get("text")
            if not any(text and text in (contents.get(f) or "") for f in files):
                missing.append({"kind": kind, "text": text,
                                "reason": tpl.get("missing_contains") or ""})
        elif kind == "note":
            if not _note_ok(notes, c.get("min_len")):
                missing.append({"kind": kind,
                                "reason": tpl.get("missing_note") or ""})
    return missing


def stage_contractp(p):
    """状态机契约定形：states/stages 列表（可嵌套 children、可 ref 引用子流程）→ 路径索引、初始与终态集合。

    refs 是子流程契约表：节点 ref=R 时把 refs[R] 以 父.R 前缀并入索引；next 引用写全路径。
    """
    machine = p.get("machine") or {}
    raw = p.get("states") or p.get("stages") or machine.get("states") or []
    refs = p.get("refs") or machine.get("refs") or {}
    out, parents, children, depths = [], {}, {}, {}
    _flatten_states(raw, "", 0, refs, out, parents, children, depths)
    by = {s["path"]: s for s in out}
    initial = out[0]["path"] if out else ""
    terminals = [s["path"] for s in out if s.get("terminal")]
    return {"states": out, "stages": out, "by_id": by, "initial": initial,
            "terminals": terminals, "parents": parents, "children": children,
            "depth": depths, "checks": p.get("checks") or machine.get("checks") or []}


def stage_refsp(p):
    """子流程引用表：流程记录中 kind=process 的条目归成 {id: states}，供契约 ref 展开。

    纯表提取，不内嵌任何流程节点；记录形状来自种子与用户流程库。
    """
    flows = _records({"seed": p.get("seed"), "user": p.get("flows"), "kind": "flows"})
    refs = {}
    for rid, rec in flows.items():
        if rec.get("kind") == "process":
            refs[rid] = rec.get("states") or []
    return {"refs": refs}


def flow_to_statesp(p):
    """旧流程 nodes/edges 归一为状态机 states：边转 next 邻接，无出边者标终态。"""
    nodes = p.get("nodes") or []
    nexts = {n: [] for n in nodes}
    for edge in p.get("edges") or []:
        if isinstance(edge, (list, tuple)) and len(edge) == 2:
            a, b = edge
            if a in nexts and b not in nexts[a]:
                nexts[a].append(b)
    states = [{"id": n, "next": nexts[n], "terminal": not nexts[n]} for n in nodes]
    return {"states": states}


def stage_apply_overridesp(p):
    """动态并入状态机覆盖：add 增节点，remove 删节点及其出边，edges 追加邻接。

    纯数据成形，不读盘；返回并入后的 states 列表。内置保护由需求层在调用前判定。
    """
    base = p.get("states") or p.get("stages") or []
    by = {s.get("id"): dict(s) for s in base if isinstance(s, dict) and s.get("id")}
    for node in p.get("add") or []:
        if isinstance(node, dict) and node.get("id"):
            by[node["id"]] = dict(node)
    for rid in p.get("remove") or []:
        by.pop(rid, None)
        for rec in by.values():
            rec["next"] = [x for x in (rec.get("next") or []) if x != rid]
    for edge in p.get("edges") or []:
        if isinstance(edge, (list, tuple)) and len(edge) == 2:
            a, b = edge
            if a in by and b in by and b not in by[a].get("next", []):
                by[a].setdefault("next", []).append(b)
    return {"states": list(by.values())}


def stage_conditionsp(p):
    """汇总活跃状态交付件条件缺口：各活跃状态 checks 跑落盘校验，不做语义判断。"""
    contract = p.get("contract") or {}
    by = contract.get("by_id") or {}
    active = _active_list(p)
    tpl = p.get("tpl") or {}
    files = p.get("files") or []
    contents = p.get("contents") or {}
    notes = p.get("notes") or []
    missing = []
    missing.extend(_check_missing(contract.get("checks") or [], files, contents, tpl, notes))
    for path in active:
        rec = by.get(path) or {}
        missing.extend(_check_missing(rec.get("checks") or [], files, contents, tpl, notes))
    return {"missing": missing}


def stage_transitionp(p):
    """校验自报状态与转移边；源状态交付件条件达标才放行。

    ok               合法（原地停留、开局进初始、边可达且条件达标）；
    unset            本轮未上报状态，直通保留活跃态；
    unknown_stage    自报状态不在契约内；
    illegal_start   开局未进初始状态；
    illegal_edge     相对活跃态的跳转不在 next 表内；
    condition_unmet  源状态交付件条件未达标，保留活跃态。

    nxt 可为单状态或多目标列表：一次分叉并行进入多条分支，活跃集合并入全部目标；
    终态源在转移后从活跃集合摘除，非终态源保留。
    """
    contract = p.get("contract") or {}
    by = contract.get("by_id") or {}
    tpl = p.get("tpl") or {}
    nxt_raw = p.get("nxt")
    if isinstance(nxt_raw, list):
        targets = [str(x).strip() for x in nxt_raw if str(x).strip()]
    else:
        targets = [str(nxt_raw or "").strip()] if str(nxt_raw or "").strip() else []
    active_raw = p.get("active")
    prev = []
    if isinstance(active_raw, list):
        prev = [str(x).strip() for x in active_raw if str(x).strip()]
    prev_raw = p.get("prev")
    if isinstance(prev_raw, list):
        prev = [str(x).strip() for x in prev_raw if str(x).strip()]
    elif str(prev_raw or "").strip():
        prev = [str(prev_raw).strip()]
    # 当前态以单值 prev 为准；活跃集是并发分支并集，其首项不能顶替当前态。
    cur = prev_raw if isinstance(prev_raw, str) and prev_raw.strip() else (prev[0] if prev else "")
    if not targets:
        return {"ok": True, "code": "unset", "stage": cur, "active": prev}
    for t in targets:
        if t not in by:
            return {"ok": False, "code": "unknown_stage",
                    "stage": cur, "active": prev}
    if not prev:
        if targets == [contract.get("initial")]:
            return {"ok": True, "code": "ok", "stage": targets[0], "active": list(targets)}
        return {"ok": False, "code": "illegal_start", "stage": "", "active": []}
    # 边可达：每个目标须由某活跃源 next 指向
    for t in targets:
        if t not in prev and not any(t in ((by.get(x) or {}).get("next") or []) for x in prev):
            return {"ok": False, "code": "illegal_edge",
                    "stage": cur, "active": prev}
    # 自检清单：要离开的源状态，must 项必须全部交齐；只允许原地停留时免检。
    checked = set(str(x) for x in (p.get("checked") or []) if str(x))
    violations = [str(x) for x in (p.get("violations") or []) if str(x)]
    if violations:
        return {"ok": False, "code": "forbidden_hit", "stage": cur, "active": prev,
                "violations": violations}
    missing = []
    for x in prev:
        if all(t == x for t in targets):
            continue
        rec = by.get(x) or {}
        for it in ((rec.get("gate") or {}).get("must") or []):
            gid = str((it or {}).get("id") or "")
            if gid and gid not in checked:
                missing.append(gid)
    if missing:
        return {"ok": False, "code": "checklist_unmet", "stage": cur, "active": prev,
                "missing": missing}

    # 源状态交付件条件：有源将离开其 checks 须落盘达标；原地停留不强制。
    files = p.get("files") or []
    contents = p.get("contents") or {}
    notes = p.get("notes") or []
    for x in prev:
        if any(t != x for t in targets):
            rec = by.get(x) or {}
            if _check_missing(rec.get("checks") or [], files, contents, tpl, notes):
                return {"ok": False, "code": "condition_unmet",
                        "stage": cur, "active": prev}
    # 活跃集合：离开的当前态要摘掉，并行分支上的兄弟态保留；目标态并入。
    kept = [x for x in prev if x != cur and not (by.get(x) or {}).get("terminal")]
    for t in targets:
        if t not in kept:
            kept.append(t)
    return {"ok": True, "code": "ok", "stage": targets[0], "active": kept}


def stage_toolsp(p):
    """按活跃状态裁剪工具清单：各活跃状态 tools 取并集；状态未列 tools 回退全集。"""
    contract = p.get("contract") or {}
    by = contract.get("by_id") or {}
    active = _active_list(p)
    items = p.get("items") or []
    allow, has_allow = set(), False
    for path in active:
        tools = (by.get(path) or {}).get("tools")
        if tools:
            has_allow = True
            allow.update(tools)
    if not has_allow:
        return {"items": list(items)}
    kept = []
    for t in items:
        name = t.get("name") if isinstance(t, dict) else t
        if name in allow:
            kept.append(t)
    return {"items": kept}


def stage_blockp(p):
    """把活跃状态契约拼成注入 system 的文本段；标题与措辞来自模板，状态内容来自数据。"""
    tpl = p.get("tpl") or {}
    contract = p.get("contract") or {}
    by = contract.get("by_id") or {}
    if not by:
        return {"system": ""}
    active = _active_list(p) or [str(contract.get("initial") or "")]
    checked = p.get("checked") or []
    if isinstance(checked, dict):
        checked = checked.get("checked") or []
    checked = {str(x.get("id") if isinstance(x, dict) else x)
               for x in checked if (x.get("id") if isinstance(x, dict) else x)}
    lines = []
    head = tpl.get("heading_stage") or ""
    if head:
        lines.append(head)
    alert = p.get("alert") or p.get("stage_alert") or {}
    gate_alert = p.get("gate_alert") or {}
    if alert.get("code"):
        lines.append((tpl.get("stage_alert") or "").format(code=alert.get("code") or ""))
        for m in gate_alert.get("missing") or alert.get("missing") or []:
            text = m.get("text") if isinstance(m, dict) else str(m)
            lines.append((tpl.get("gate_alert_item") or "- {text}").format(text=text))
        for v in gate_alert.get("violations") or alert.get("violations") or []:
            text = v.get("text") if isinstance(v, dict) else str(v)
            lines.append((tpl.get("gate_violation_item") or "- {text}").format(text=text))
    for path in active:
        rec = by.get(path) or {}
        if not rec:
            continue
        cur = (tpl.get("stage_current") or "").format(cn=rec.get("cn") or path, id=path)
        if cur:
            lines.append(cur)
        desc = rec.get("desc") or ""
        if desc:
            lines.append((tpl.get("stage_desc") or "").format(desc=desc))
        nxt = rec.get("next") or []
        if nxt:
            nxt_cn = [by.get(x, {}).get("cn") or x for x in nxt]
            lines.append((tpl.get("stage_next") or "").format(next="、".join(nxt_cn)))
        elif rec.get("terminal"):
            lines.append(tpl.get("stage_terminal") or "")
    # 本步清单跟着 system 走：上下文压缩只留 system，清单不能只挂在流程约束消息里
    gate_lines = []
    for path in active:
        rec = by.get(path) or {}
        gate = rec.get("gate") or {}
        for it in gate.get("must") or []:
            mid = (it or {}).get("id") or ""
            done = mid and mid in checked
            gt = (tpl.get("gate_must_done") if done else tpl.get("gate_must")) or ""
            if gt:
                gate_lines.append(gt.format(id=mid,
                                            text=(it or {}).get("text") or ""))
        for f in gate.get("forbid") or []:
            gt = tpl.get("gate_forbid") or ""
            if gt:
                gate_lines.append(gt.format(text=f))
    if gate_lines and tpl.get("heading_gate"):
        lines.append(tpl["heading_gate"])
        lines.extend(gate_lines)
        if tpl.get("gate_rule"):
            lines.append(tpl["gate_rule"])
    if tpl.get("stage_rule"):
        lines.append(tpl["stage_rule"])
    return {"system": "\n".join(lines)}


def flow_contextp(p):
    """把流程契约定形成独立结构化约束块：流程标识/状态全集/当前活跃态/可转移/验收标准。

    data 部分（flow/active/states/checks）存档供后端与前端；content 是渲染后的可读文本，
    进 LLM 上下文。纯数据成形，文案来自模板，不读盘不取时钟。
    """
    tpl = p.get("tpl") or {}
    contract = p.get("contract") or {}
    by = contract.get("by_id") or {}
    active = _active_list(p) or [str(contract.get("initial") or "")]
    flow = p.get("flow") or {}
    states = []
    for path, rec in by.items():
        states.append({"id": path, "cn": rec.get("cn") or path,
                       "desc": rec.get("desc") or "",
                       "next": rec.get("next") or [],
                       "when": rec.get("when") or {},
                       "gate": rec.get("gate") or {},
                       "terminal": bool(rec.get("terminal"))})
    checks = [dict(c, desc=_check_desc(c, tpl)) for c in (p.get("checks") or [])]
    lines = []
    head = tpl.get("heading_flow_context") or tpl.get("heading_stage") or ""
    if head:
        lines.append(head)
    flow_cn = flow.get("cn") or ""
    flow_name_tpl = tpl.get("flow_name") or ""
    if flow.get("id") and flow_name_tpl:
        lines.append(flow_name_tpl.format(cn=flow_cn, id=flow.get("id")))
    for path in active:
        rec = by.get(path) or {}
        cur = (tpl.get("stage_current") or "").format(cn=rec.get("cn") or path, id=path)
        if cur:
            lines.append(cur)
        desc = rec.get("desc") or ""
        if desc:
            lines.append((tpl.get("stage_desc") or "").format(desc=desc))
        nxt = rec.get("next") or []
        if nxt:
            nxt_cn = [by.get(x, {}).get("cn") or x for x in nxt]
            lines.append((tpl.get("stage_next") or "").format(next="、".join(nxt_cn)))
        elif rec.get("terminal"):
            lines.append(tpl.get("stage_terminal") or "")
    # ---- 状态机全貌：分支、回退与迁移条件都要进提示词，模型不能只看到"当前阶段" ----
    sm_head = tpl.get("heading_state_machine") or ""
    if sm_head and by:
        lines.append(sm_head)
    for path, rec in by.items():
        t = (tpl.get("machine_state_cur") if path in active else tpl.get("machine_state")) or ""
        if t:
            lines.append(t.format(cn=rec.get("cn") or path, id=path, desc=rec.get("desc") or ""))
        for to in (rec.get("next") or []):
            trec = by.get(to) or {}
            cond = (rec.get("when") or {}).get(to) or ""
            e = (tpl.get("machine_edge") if cond else tpl.get("machine_edge_plain")) or ""
            if e:
                lines.append(e.format(cn=trec.get("cn") or to, id=to, when=cond))
    # ---- 本步清单：must 打勾项 + forbid 红线，直接随状态机下发 ----
    gate_head = tpl.get("heading_gate") or ""
    gate_lines = []
    for path in active:
        rec = by.get(path) or {}
        gate = rec.get("gate") or {}
        for it in gate.get("must") or []:
            gt = tpl.get("gate_must") or ""
            if gt:
                gate_lines.append(gt.format(id=(it or {}).get("id") or "", text=(it or {}).get("text") or ""))
        for f in gate.get("forbid") or []:
            gt = tpl.get("gate_forbid") or ""
            if gt:
                gate_lines.append(gt.format(text=f))
    if gate_lines and gate_head:
        lines.append(gate_head)
        lines.extend(gate_lines)
        if tpl.get("gate_rule"):
            lines.append(tpl.get("gate_rule"))
    checks_head = tpl.get("heading_checks") or ""
    if checks:
        if checks_head:
            lines.append(checks_head)
        for c in checks:
            lines.append("- " + (c.get("desc") or ""))
    return {"kind": "flow-context",
            "flow": {"id": flow.get("id") or "", "cn": flow_cn},
            "active": active, "states": states, "checks": checks,
            "content": "\n".join(lines)}


def stage_gapsp(p):
    """把状态约束并入产物缺口：任一活跃状态非终态、非法跳转各成一条；无契约直通。"""
    tpl = p.get("tpl") or {}
    contract = p.get("contract") or {}
    by = contract.get("by_id") or {}
    active = _active_list(p) or [str(contract.get("initial") or "")]
    alerts = p.get("stage_alert") or {}
    missing = list(p.get("base") or [])
    open_active = [x for x in active if by.get(x) and not by[x].get("terminal")]
    if by and open_active:
        rec = by.get(open_active[0])
        txt = (tpl.get("stage_not_terminal") or "").format(
            cn=rec.get("cn") or open_active[0], id=open_active[0])
        missing.append({"kind": "stage", "text": txt})
    if alerts and alerts.get("code"):
        txt = (tpl.get("stage_alert") or "").format(code=alerts.get("code") or "")
        missing.append({"kind": "stage", "text": txt})
    return {"missing": missing}


def _gap_text(gap):
    """单条缺口成形为可读文本；形状来自 checkp，缺字段不报错。"""
    if not isinstance(gap, dict):
        return str(gap)
    if gap.get("path"):
        return str(gap["path"])
    if gap.get("text"):
        return str(gap["text"])
    if gap.get("reason"):
        return str(gap["reason"])
    return str(gap.get("paths") or gap)


def prompt_blocks(p):
    """把岗位自然语言正文与结构化红线/必做拼成系统提示词附加段。

    正文来自数据文件；这里只做结构拼装，不写任何职责正文。
    """
    tpl = p.get("tpl") or {}
    text = p.get("text") or ""
    must = p.get("must_dos") or []
    forbidden = p.get("forbidden") or []
    stage_text = p.get("stage") or ""
    parts = [text] if text else []
    if must:
        head = tpl.get("heading_must") or ""
        parts.append(head + "\n" + "\n".join("- %s" % m for m in must) if head
                     else "\n".join("- %s" % m for m in must))
    if forbidden:
        head = tpl.get("heading_forbidden") or ""
        parts.append(head + "\n" + "\n".join("- %s" % m for m in forbidden) if head
                     else "\n".join("- %s" % m for m in forbidden))
    if stage_text:
        parts.append(stage_text)
    return {"system": "\n\n".join(parts)}


def bind_tools(p):
    """岗位×流程×工具三级绑定成形：给每个岗位打上"哪些工具在本项目可用"。

    项目覆盖层只存禁用名，公共库只存岗位工具名单；绑定关系在这里显性摊开，
    视图才能一行看清"这个岗位走哪条流程、手里有哪几件工具、哪件被本项目关了"。
    """
    disabled = set(p.get("disabled") or [])
    kind = p.get("kind") or ""
    items = []
    for row in p.get("items") or []:
        rec = dict(row)
        names = [str(n) for n in (rec.get("tools") or [])]
        bound = [{"name": n, "enabled": (n not in disabled),
                  "source": "builtin"} for n in names]
        live = [b["name"] for b in bound if b["enabled"]]
        rec["bound_tools"] = bound
        rec["tools_enabled"] = live
        rec["tools_disabled"] = [b["name"] for b in bound if not b["enabled"]]
        rec["tools_sum"] = "%d/%d" % (len(live), len(names))
        rec["tools_text"] = "、".join(live) if live else ""
        states = rec.get("stages") or []
        rec["stage_text"] = " → ".join(str((s or {}).get("cn") or (s or {}).get("id") or "")
                                       for s in states if isinstance(s, dict))
        rec["kind"] = kind
        items.append(rec)
    return {"items": items}


def positionp(p):
    """单条岗位：岗位记录 + 关联流程规范合并成形。"""
    rec = p.get("rec") or {}
    prompt_text = p.get("prompt_text") or ""
    tpl = p.get("tpl") or {}
    if not rec:
        pid = p.get("id") or ""
        t = tpl.get("position_missing") or ""
        return {"ok": False, "code": "not_found", "status": 404,
                "error": t.format(id=pid) if t else ""}
    return _position(rec, p.get("flow") or {}, prompt_text, tpl)


def _disabled_skill_ids(skills):
    """状态为 disabled 的 Skill 标识集合；归属这些 Skill 的岗位/工具/流程不进运行名单。"""
    return {sid for sid, rec in (skills or {}).items()
            if isinstance(rec, dict) and rec.get("status") == "disabled"}


def positionsp(p):
    """岗位列表：岗位记录按 id 关联各自流程规范；禁用 Skill 的岗位摘除。

    disabled_roles 为项目级禁用岗位 id 集合：公共库记录仍展示并打 disabled 标记，供项目重新启用；
    system/readonly 内置条目恒定受保护，不被项目禁用标记摘除。
    """
    roles = _records({"seed": p.get("seed"), "user": p.get("user"), "kind": "roles"})
    disabled = _disabled_skill_ids(p.get("skills"))
    disabled_roles = set(p.get("disabled_roles") or [])
    tpl = p.get("tpl") or {}
    items = []
    for rid, rec in roles.items():
        sk = rec.get("skill")
        if sk and sk in disabled:
            continue
        row = _position(rec, rec, "", tpl)
        locked = bool(rec.get("system") or rec.get("readonly"))
        row["disabled"] = (rid in disabled_roles) and not locked
        if row["disabled"]:
            row["disabled_text"] = tpl.get("label_disabled_project") or ""
        else:
            row["disabled_text"] = tpl.get("label_enabled") or ""
        row["locked"] = locked
        items.append(row)
    return {"items": items}


def listp(p):
    kind = p.get("kind") or "roles"
    return {"kind": kind, "items": [dict(r) for r in _records(p).values()]}


def getp(p):
    kind = p.get("kind") or "roles"
    rid = p.get("id") or ""
    rec = _records(p).get(rid)
    if not rec:
        tpl = (p.get("tpl") or {}).get("kind_missing") or ""
        return {"ok": False, "code": "not_found", "status": 404,
                "error": tpl.format(kind=kind, id=rid) if tpl else ""}
    return {"kind": kind, "item": rec}


def designp(p):
    """用户记录合并字段；内置角色不许改提示词。"""
    kind = p.get("kind") or "roles"
    rid = p.get("id") or ""
    fields = p.get("fields") or {}
    tpl = p.get("tpl") or {}
    if not rid:
        return {"ok": False, "code": "missing_id", "error": tpl.get("id_required") or ""}
    rec = dict(p.get("record") or {})
    if rec.get("builtin") and kind == "roles" and fields.get("prompt"):
        return {"ok": False, "code": "builtin_protected", "status": 403,
                "error": tpl.get("builtin_role_protected") or ""}
    rec.update(fields)
    rec.setdefault("id", rid)
    rec.setdefault("builtin", False)
    rec["updated"] = p.get("now") or ""
    return rec


def summaryp(p):
    seed = p.get("seed") or {}
    user = p.get("user") or {}
    roles = _records({"seed": seed, "user": user.get("roles") or {}, "kind": "roles"})
    # 流程数统计带状态机的岗位：状态机随岗位走，不再有独立流程实体（子流程库另计）
    flows = sum(1 for r in roles.values() if isinstance(r, dict) and r.get("states"))
    skills = [k for k, v in (p.get("user_skills") or {}).items() if isinstance(v, dict)]
    return {"counts": {"roles": len(roles), "flows": flows, "skills": len(skills)},
            "roles": sorted(roles), "flows": [], "skills": sorted(skills)}


def promptp(p):
    role = p.get("role") or ""
    rec = p.get("rec") or {}
    ref = rec.get("prompt_file")
    if not ref:
        tpl = p.get("tpl") or {}
        t = tpl.get("no_prompt_file") or ""
        return {"ok": False, "code": "no_prompt_file",
                "error": t.format(role=role) if t else ""}
    return {"role": role, "prompt": p.get("text") or "", "ref": ref}


def prompt_fold(p):
    """提示词变更成文：append 追加规则，replace 整段替换；只算文本，不写盘。

    PM 在线上发现角色提示词导致空转时，用 prompt_patch 追加一条带日期的约束，
    下一个会话/下一轮即可生效；不要求 PM 有源码写权限，也不改 roles.yaml。
    """
    old = str(p.get("old") or "")
    add = str(p.get("append") or "").strip()
    mode = str(p.get("mode") or "append")
    if mode == "replace":
        body = str(p.get("text") or "").strip()
    else:
        body = old.rstrip() + ("\n\n" + add if add else "")
    body = body.rstrip() + "\n"
    return {"old_chars": len(old), "new_chars": len(body),
            "changed": body != old, "text": body}

def checkp(p):
    """files: [路径]；contents: {路径: 文本}；notes: 本轮结论备注；checks 来自流程记录。"""
    tpl = p.get("tpl") or {}
    rec = p.get("rec") or {}
    checks = rec.get("checks") or []
    files = p.get("files") or []
    contents = p.get("contents") or {}
    notes = p.get("notes") or []
    missing = []
    for c in checks:
        kind = c.get("kind")
        if kind == "glob":
            paths = c.get("paths") or []
            match = c.get("match") or "all"
            if match == "any":
                if not any(any(_glob(f, pat) for pat in paths) for f in files):
                    missing.append({"kind": kind, "paths": paths, "match": match,
                                    "reason": tpl.get("missing_any") or ""})
            else:
                for pat in paths:
                    if not any(_glob(f, pat) for f in files):
                        missing.append({"kind": kind, "path": pat, "match": match})
        elif kind == "contains":
            text = c.get("text")
            if not any(text and text in (contents.get(f) or "") for f in files):
                missing.append({"kind": kind, "text": text, "reason": tpl.get("missing_contains") or ""})
        elif kind == "note":
            if not _note_ok(notes, c.get("min_len")):
                missing.append({"kind": kind, "reason": tpl.get("missing_note") or ""})
    return {"flow": p.get("flow") or "", "missing": missing, "checked": len(checks)}


def kind_file(p):
    """岗位库分库用户记录文件：模板由需求层配置表给出，纯函数只填参。"""
    paths = p.get("paths") or {}
    t = paths.get("record") or ""
    kind = p.get("kind") or ""
    return {"path": t.format(kind=kind) if t else kind}


def prompt_path(p):
    """提示词文件定位：返回所属模块与相对路径；模板由需求层配置表给出，纯函数只填参。

    提示词归属模块由记录 prompt_module 标注（缺省 agent/library）；sessions 侧记录的
    prompt_file 已是相对会话数据根的完整路径，不再套 library 的 prompts 模板。
    """
    paths = p.get("paths") or {}
    rec = p.get("rec") or {}
    module = rec.get("prompt_module") or "agent/library"
    file = p.get("file") or rec.get("prompt_file") or ""
    if module == "agent/sessions":
        return {"module": module, "path": file}
    t = paths.get("prompt") or ""
    return {"module": module, "path": t.format(file=file) if t else file}


def save_record(p):
    """把合并后的记录并回用户记录字典（按 id 映射）；写盘值归岗位库模块。"""
    user = dict(p.get("user") or {})
    rec = p.get("rec") or {}
    rid = rec.get("id")
    if rid:
        user[rid] = dict(rec)
    return {"value": user}


# ---- Skill 单元：聚合岗位/流程/工具，支持禁用与级联卸载 ----

def disabled_p(p):
    """Skill 登记字典 → 已禁用标识清单；供工具/岗位清单按归属摘除。判断归岗位库模块。"""
    return {"ids": sorted(_disabled_skill_ids(p.get("skills")))}


def skills_listp(p):
    """Skill 登记字典 → 清单行：关联岗位中文名、流程在库与否、工具名清单与状态。

    disabled 为项目级禁用 Skill 标识集合：记录仍展示并打 disabled_project 标记，供项目重新启用。
    合并与摘要成形归岗位库模块；各库记录由需求读盘后交入。
    """
    skills = p.get("skills") or {}
    roles = p.get("roles") or {}
    flows = p.get("flows") or {}
    disabled_project = set(p.get("disabled") or [])
    tpl = p.get("tpl") or {}
    items = []
    for sid, rec in skills.items():
        if not isinstance(rec, dict):
            continue
        role_id = rec.get("role") or ""
        flow_id = rec.get("flow") or ""
        tool_names = rec.get("tools") or []
        role_rec = roles.get(role_id) or {}
        disabled = rec.get("status") == "disabled"
        items.append({
            "id": sid,
            "cn": rec.get("cn") or sid,
            "doc": rec.get("doc") or "",
            "source": rec.get("source") or "",
            "version": rec.get("version") or "",
            "status": rec.get("status") or "enabled",
            "status_text": (tpl.get("label_disabled") or "") if disabled else (tpl.get("label_enabled") or ""),
            "disabled_project": sid in disabled_project,
            "disabled_text": (tpl.get("label_disabled_project") or "") if sid in disabled_project else "",
            "role": role_id,
            "role_cn": role_rec.get("cn") or "",
            "flow": flow_id,
            "has_flow": bool(role_rec.get("states")),
            "flow_text": (tpl.get("label_has_flow") or "") if role_rec.get("states") else (tpl.get("label_no_flow") or ""),
            "tools": "、".join(tool_names),
            "tool_names": tool_names,
            "builtin": bool(rec.get("builtin")),
            "created": rec.get("created") or "",
            "updated": rec.get("updated") or "",
        })
    items.sort(key=lambda x: x.get("created") or "", reverse=True)
    return {"items": items}


def skill_statusp(p):
    """翻转 Skill 启用状态；内置 Skill 受保护不改。记录合并归岗位库模块。"""
    sid = (p.get("id") or "").strip()
    rec = dict(p.get("record") or {})
    tpl = p.get("tpl") or {}
    if not sid:
        return {"ok": False, "code": "missing_id", "error": tpl.get("id_required") or ""}
    if rec.get("builtin"):
        return {"ok": False, "code": "builtin_protected", "status": 403,
                "error": tpl.get("builtin_skill_protected") or ""}
    rec["id"] = sid
    rec["status"] = p.get("status") or rec.get("status") or "enabled"
    rec["updated"] = p.get("now") or ""
    return rec


def skill_uninstallp(p):
    """级联卸载：从 Skill 登记及其岗位/流程/工具字典中一并摘除；内置受保护。

    只裁剪字典不写盘；写盘编排归需求。工具按登记名单与 skill 归属双保险清理。
    """
    sid = (p.get("id") or "").strip()
    skills = dict(p.get("skills") or {})
    tpl = p.get("tpl") or {}
    if not sid:
        return {"ok": False, "code": "missing_id", "error": tpl.get("id_required") or ""}
    rec = skills.get(sid)
    if not isinstance(rec, dict):
        tpl_missing = tpl.get("skill_missing") or ""
        return {"ok": False, "code": "not_found", "status": 404,
                "error": tpl_missing.format(id=sid) if tpl_missing else ""}
    if rec.get("builtin"):
        return {"ok": False, "code": "builtin_protected", "status": 403,
                "error": tpl.get("builtin_skill_uninstall_protected") or ""}
    roles = dict(p.get("roles") or {})
    flows = dict(p.get("flows") or {})
    tools = dict(p.get("tools") or {})
    role_id = rec.get("role") or ""
    flow_id = rec.get("flow") or ""
    tool_names = list(rec.get("tools") or [])
    if role_id and role_id in roles:
        del roles[role_id]
    if flow_id and flow_id in flows:
        del flows[flow_id]
    for tn in tool_names:
        if tn in tools:
            del tools[tn]
    for tn, t in list(tools.items()):
        if isinstance(t, dict) and t.get("skill") == sid:
            del tools[tn]
    del skills[sid]
    return {"skills": skills, "roles": roles, "flows": flows, "tools": tools,
            "removed": {"role": role_id, "flow": flow_id, "tools": tool_names}}
