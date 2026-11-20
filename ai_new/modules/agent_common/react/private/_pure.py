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
    msg = {"role": "assistant", "content": p.get("content") or ""}
    calls = p.get("tool_calls") or []
    if calls:
        msg["tool_calls"] = calls
    if p.get("at"):
        msg["at"] = p["at"]
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
            "stage": p.get("stage") or ""}


def toolerr(p):
    return {"error": p.get("message") or "", "code": p.get("code") or "tool_error"}


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


def checkpoint(p):
    """轮内检查点成形：在会话快照上覆盖本轮累积消息/摘要/步数与时间，供中间落盘。

    纯 dict 拷贝与字段定型，不碰盘、不取时钟（now 由编排层给）。崩溃后磁盘上保留
    最后一条检查点，重启可据此重建存档；跨轮上下文接续仍以 summary 为准。
    """
    rec = dict(p.get("rec") or {})
    msgs = p.get("messages")
    if msgs is not None:
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


def parse_final(p):
    """拆分收口步的结构化输出：reply 进气泡，summary 存滚动摘要。

    obj 为 codec 已解码结果；解析失败/非 dict 时整段作答复正文，摘要留空由调用方回退。
    纯计算，不碰盘、不做 JSON 解码。
    """
    content = p.get("content") or ""
    obj = p.get("obj")
    if isinstance(obj, dict) and ("reply" in obj or "summary" in obj or "stage" in obj):
        return {"structured": True,
                "reply": _textify(obj.get("reply")),
                "summary": _textify(obj.get("summary")),
                "stage": _textify(obj.get("stage"))}
    return {"structured": False, "reply": content, "summary": "", "stage": ""}


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
