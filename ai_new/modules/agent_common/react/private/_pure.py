"""ReAct 纯函数：把响应切成消息、把工具定义切成模型能吃的形状。循环在 react-run 需求里。"""
from __future__ import annotations


def schema(p):
    props, required = {}, []
    for item in p.get("tool") or []:
        raw = item.get("type") or "string"
        # 内部用 list 表清单，模型侧 JSON Schema 只认 array；array 需带 items。
        t = "array" if raw == "list" else raw
        prop = {"type": t, "description": item.get("desc") or ""}
        if t == "array":
            prop["items"] = {"type": "object"}
        props[item["name"]] = prop
        if item.get("required"):
            required.append(item["name"])
    return {"type": "function",
            "function": {"name": p.get("name"), "description": p.get("desc") or "",
                         "parameters": {"type": "object", "properties": props,
                                        "required": required}}}


def schemas(p):
    return [schema({"name": t["name"], "desc": t.get("desc"),
                    "tool": t.get("params")}) for t in p.get("tools") or []]


def assistant(p):
    """助手消息成形：正文 + 工具调用 + 时刻；带了上游网络报文就一并挂上，方便回查原文。

    收口轮带 questions 时原样挂到消息上：问题卡是消息的一部分，刷新后仍随历史回放。
    """
    msg = {"role": "assistant", "content": p.get("content") or ""}
    calls = p.get("tool_calls") or []
    if calls:
        msg["tool_calls"] = calls
    if p.get("at"):
        msg["at"] = p["at"]
    questions = p.get("questions")
    if isinstance(questions, (list, tuple)) and questions:
        msg["questions"] = list(questions)
    wire = p.get("wire")
    if isinstance(wire, dict) and wire:
        msg["wire"] = wire
    return msg


def toolnames(p):
    return [((c.get("function") or {}).get("name")) for c in p.get("tool_calls") or []]


def args(p):
    value = p.get("value")
    return value if isinstance(value, dict) else {}


def toolmsg(p):
    msg = {"role": "tool", "tool_call_id": p.get("id") or "call_0",
           "name": p.get("name") or "", "content": p.get("content") or "{}"}
    if p.get("at"):
        msg["at"] = p["at"]
    return msg


def step(p):
    return {"index": p.get("index"), "content": p.get("content") or "",
            "tools": p.get("tools") or []}


def result(p):
    msgs = p.get("messages") or []
    return {"steps": p.get("steps") or 0, "messages": msgs,
            "last": msgs[-1] if msgs else None, "cancelled": bool(p.get("cancelled")),
            "failed": p.get("failed"), "summary": p.get("summary"),
            "summary_by_model": bool(p.get("summary_by_model")),
            "new_messages": p.get("new_messages") or [],
            "stage": p.get("stage") or "",
            "checklist": p.get("checklist") or [],
            "violations": p.get("violations") or []}


# ---- 上下文治理：历史摘要、发往视图、大输出分级 ----

def summary_msg(p):
    """滚动摘要消息成形：role 留 assistant 供上游识别，kind 标记摘要只供展示/治理。"""
    text = p.get("summary") or ""
    if not text.strip():
        return None
    return {"role": "assistant", "kind": "summary", "content": text.strip()}


def context_view(p):
    """构造发往上游的上下文视图。

    存档 messages 全量保留供展示与回溯；发模型时除 system 外不带历史原始往返，
    历史由上一轮 LLM 生成的滚动摘要替代，只保留本轮指令（最后一条 user）。
    本轮 ReAct 内新增的 assistant/tool 由循环追加进同一视图。
    """
    msgs = p.get("messages") or []
    system = [m for m in msgs if m.get("role") == "system"]
    rest = [m for m in msgs if m.get("role") != "system"]
    last_user = None
    for m in reversed(rest):
        if m.get("role") == "user":
            last_user = m
            break
    view = list(system)
    smsg = summary_msg({"summary": p.get("summary")})
    if smsg:
        view.append(smsg)
    if last_user:
        view.append(last_user)
    return {"messages": view}


def _sig(m):
    """消息同一条判据：只比角色与正文，时间/序号变化不算另起一条。"""
    m = m or {}
    return (m.get("role"), str(m.get("content") or ""))


def _merge_tail(base, msgs):
    """把「快照尾部有、本轮消息里丢了」的条目按原位补回去。

    本轮可能是从更早的入参重建消息的：重建时快照末尾新追加的条目就被落下了。
    只补公共前缀之后的尾部，前缀之前的压缩结果不动。
    """
    base = list(base or [])
    msgs = list(msgs or [])
    prefix = 0
    while prefix < len(base) and prefix < len(msgs) \
            and _sig(base[prefix]) == _sig(msgs[prefix]):
        prefix += 1
    seen = {_sig(m) for m in msgs}
    # 只补对话条目：system 每轮都会重刷，把旧的那条搬回来就变成两份人设
    tail = [m for m in base[prefix:]
            if _sig(m) not in seen and (m or {}).get("role") != "system"]
    return msgs[:prefix] + tail + msgs[prefix:] if tail else msgs


def _keep_appended(snap, msgs, latest):
    """检查点写盘前保住「本轮快照之后才追加的人类消息」。

    本轮跑着的时候人还能往会话里发话：那条消息落在磁盘记录里，不在本轮快照里。
    检查点若整段覆盖，就把人刚说的话抹掉。这里把盘上新追加的、又不是本轮自己产出的
    消息接在后面；本轮自己写过的检查点消息按签名抵扣，避免重复落库。
    """
    base = list((snap or {}).get("messages") or [])
    msgs = list(msgs or [])
    fresh = list((latest or {}).get("messages") or [])
    extra = fresh[len(base):] if len(fresh) > len(base) else []
    for run_msg in msgs[len(base):]:
        sig = _sig(run_msg)
        for i, extra_msg in enumerate(extra):
            if _sig(extra_msg) == sig:
                del extra[i]
                break
    return msgs + extra if extra else msgs


def checkpoint(p):
    """轮内检查点成形：在会话快照上覆盖本轮累积消息/摘要/步数与时间，供中间落盘。

    纯 dict 拷贝与字段定型，不碰盘、不取时钟（now 由编排层给）。崩溃后磁盘上保留
    最后一条检查点，重启可据此重建存档；跨轮上下文接续仍以 summary 为准。
    """
    rec = dict(p.get("rec") or {})
    msgs = p.get("messages")
    if msgs is not None:
        msgs = _merge_tail((p.get("rec") or {}).get("messages"), msgs)
        msgs = _keep_appended(p.get("rec"), msgs, p.get("latest"))
        rec["messages"] = list(msgs)
    if p.get("summary") is not None:
        rec["summary"] = p.get("summary") or ""
    if p.get("steps") is not None:
        rec["steps"] = p.get("steps") or 0
    if p.get("now"):
        rec["updated"] = p.get("now")
    return rec


def classify_tool(p):
    """工具输出分级：按字符数判定是否超限需落盘只回路径。纯计算，不碰盘。"""
    text = p.get("content") or ""
    threshold = int(p.get("threshold"))
    size = len(text)
    return {"large": size > threshold, "size": size, "threshold": threshold}


def strip_fence(p):
    """剥掉模型常见的 ```json 代码围栏，留出可解析正文；纯字符串处理，不解析 JSON。"""
    t = (p.get("text") or "").strip()
    if t.startswith("```"):
        body = t[3:].strip()
        if body.endswith("```"):
            body = body[:-3].strip()
        # 首行可能是语言标签（json/yaml…）：多行按行切，单行按首个空白切。
        if "\n" in body:
            body = body.split("\n", 1)[-1]
        else:
            parts = body.split(None, 1)
            body = parts[1] if len(parts) == 2 else (parts[0] if parts else "")
        t = body.strip()
    return {"text": t.strip()}


def extract_json(p):
    """从夹带前后解释文字的正文里截取首个 { 到末个 } 的 JSON 区间；无括号则原样返回。纯字符串处理。"""
    t = (p.get("text") or "").strip()
    i, j = t.find("{"), t.rfind("}")
    if i != -1 and j > i:
        return {"text": t[i:j + 1]}
    return {"text": t}


def _textify(value):
    """收口字段定型为字符串：None 为空，其余类型转文本；不做结构化序列化（归 codec）。"""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def _questions(value):
    """澄清问题卡片定型：只收可被界面直接渲染的问题与选项。

    问题必须有正文；选项允许字符串或 {label,value}，上限 5 个。形状不对的条目丢弃，
    不让坏数据把整张问题卡带崩。多选/其他输入显式保留；缺省 other=True。
    """
    if not isinstance(value, (list, tuple)):
        return []
    out = []
    for i, item in enumerate(value):
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        opts = []
        raw_opts = item.get("options")
        if isinstance(raw_opts, (list, tuple)):
            for opt in raw_opts[:5]:
                if isinstance(opt, str):
                    label, val = opt.strip(), opt.strip()
                elif isinstance(opt, dict):
                    label = str(opt.get("label") or opt.get("value") or "").strip()
                    val = str(opt.get("value") or label).strip()
                else:
                    continue
                if label and val and not any(x["value"] == val for x in opts):
                    opts.append({"label": label, "value": val})
        out.append({"id": str(item.get("id") or "q%s" % (i + 1)).strip()[:40],
                    "text": text[:400], "multi": bool(item.get("multi")),
                    "options": opts, "other": item.get("other") is not False})
    return out[:6]


def parse_final(p):
    """拆分收口步的结构化输出：reply 进气泡，summary 存滚动摘要。

    obj 为 codec 已解码/抢救结果；解析失败/非 dict 时整段作答复正文，摘要留空由调用方回退。
    纯计算，不碰盘、不做 JSON 解码。
    """
    content = p.get("content") or ""
    obj = p.get("obj")
    def _list(v):
        """清单字段只收字符串列表：模型给错形状就当空，不让坏数据走成"已交齐"。"""
        if isinstance(v, (list, tuple)):
            return [str(x).strip() for x in v if str(x).strip()]
        if isinstance(v, str) and v.strip():
            return [x.strip() for x in v.replace("，", ",").split(",") if x.strip()]
        return []

    if isinstance(obj, dict) and ("reply" in obj or "summary" in obj or "stage" in obj
                                 or "questions" in obj):
        raw = obj
    else:
        raw = {}
    if raw:
        return {"structured": True,
                "reply": _textify(raw.get("reply")),
                "summary": _textify(raw.get("summary")).strip(),
                "stage": _textify(raw.get("stage")).strip(),
                "checklist": _list(raw.get("checklist")),
                "violations": _list(raw.get("violations")),
                "questions": _questions(raw.get("questions"))}
    return {"structured": False, "reply": content, "summary": "", "stage": "",
            "checklist": [], "violations": []}


def summarize(p):
    """滚动摘要收口：模型给了就听模型的，没给就把本轮工具往返压成一段系统兜底。

    为什么必须有：发往上游的上下文只带 system + 滚动摘要 + 最后一条用户指令，
    本轮工具结果不会自动进下一轮载荷。模型没交 summary（步数耗尽/被打断）时，
    这一轮就等于白干，所以按显式字符上限补一段，并标明是系统兜底，避免模型误当自己的结论。
    """
    base = (p.get("summary") or "").strip()
    if p.get("by_model"):
        return {"summary": base, "fallback": False}
    msgs = p.get("messages") or []
    cap = int(p.get("chars") or 0)
    title = p.get("title") or ""
    lines = []
    for m in msgs:
        role = (m or {}).get("role") or ""
        if role == "assistant" and (m or {}).get("tool_calls"):
            names = []
            for c in m.get("tool_calls") or []:
                fn = (c or {}).get("function") or {}
                arg = (fn.get("arguments") or "").strip()
                names.append("%s(%s)" % (fn.get("name") or "?", arg[:60]))
            lines.append("- 调用: " + "; ".join(names))
        elif role == "tool":
            body = ((m or {}).get("content") or "").strip().replace("\n", " ")
            lines.append("- 结果: " + body[:160])
    if not lines:
        return {"summary": base, "fallback": False}
    text = (title + "\n" if title else "") + "\n".join(lines)
    merged = (base + "\n\n" + text).strip() if base else text
    # 上限是对整段滚动摘要的硬约束，不能只截本轮兜底正文：旧摘要 + 正文拼完仍超限，
    # 下一轮上下文就会比配置的预算大。先拼再截，保留旧摘要的头部信息。
    if cap > 0 and len(merged) > cap:
        merged = merged[:cap] + "…"
    return {"summary": merged, "fallback": True}


def attach_protocol(p):
    """把收口输出协议约定追加到首条 system 消息；无 system 或无协议文本则原样返回。"""
    msgs = list(p.get("messages") or [])
    protocol = (p.get("protocol") or "").strip()
    if not protocol:
        return {"messages": msgs}
    for i, m in enumerate(msgs):
        if m.get("role") == "system":
            msg = dict(m)
            msg["content"] = (str(m.get("content") or "").rstrip() + "\n\n" + protocol).strip()
            msgs[i] = msg
            break
    return {"messages": msgs}
