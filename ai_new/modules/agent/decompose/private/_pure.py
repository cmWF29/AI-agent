"""拆解纯函数：包内容解析、提示词成形、模型返回成形、入库记录映射。

不读盘、不取时间、不调模型；模型返回的对象已由闭环解码后交进来。
Skill.md 的 frontmatter 与 requirements.txt 都是纯文本，这里手写极简解析，
不借 yaml/json 标准库（编解码归 codec，文件读取归 store）。
拆解结果直接成形为一个 Skill 单元（岗位 + 流程 + 工具），不再经过草稿待确认。
"""
from __future__ import annotations


# ---- 包文本解析 ----

def _split_frontmatter(md):
    """拆出 frontmatter 行与正文；没有头部分隔符时整段算正文。"""
    lines = (md or "").splitlines()
    if not lines or lines[0].strip() != "---":
        return [], md or ""
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        return [], md or ""
    return lines[1:end], "\n".join(lines[end + 1:])


def _parse_meta_lines(meta_lines):
    """极简 frontmatter 键值解析：顶层键平铺，缩进键归 metadata。不做类型转换。"""
    meta = {}
    nested = {}
    for line in meta_lines:
        if not line.strip():
            continue
        indented = line[:1] in (" ", "\t")
        key, _, val = line.strip().partition(":")
        val = val.strip().strip('"').strip("'")
        key = key.strip()
        if not key:
            continue
        if indented:
            nested[key] = val
        else:
            meta[key] = val
    if nested:
        meta["metadata"] = nested
    return meta


def _req_package(line):
    """requirements 一行 → 包名；剥版本约束、注释与环境标记。"""
    s = line.strip()
    if not s or s.startswith("#"):
        return ""
    for sep in ("==", ">=", "<=", "~=", "!=", ";", "<", ">", " "):
        idx = s.find(sep)
        if idx != -1:
            s = s[:idx]
    return s.strip()


def _as_list(value):
    """文本按换行/逗号拆清单；本就是列表就逐项转字符串。"""
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x or "").strip()]
    text = str(value or "")
    if not text.strip():
        return []
    for sep in ("\n", ",", "，"):
        text = text.replace(sep, "\n")
    return [x.strip() for x in text.split("\n") if x.strip()]


# ---- 拆解期拉装工具的确定性校验 ----

# pip 包名允许字符（PEP 508 名称）：字母数字开头，后接字母数字 / . / _ / -。
_PKG_ALLOWED = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-")
# 包名/版本约束里都不该出现的注入字符：空格、管道、后台、替换、路径、括号、通配等。
_PKG_DANGEROUS = set(" |&$`/\\(){}*?#\"'")


def safe_pkg(p, tpl=None):
    """校验待装 pip 包名：剥版本约束，拒掉含注入字符或环境标记的写法。

    只认纯包名（可带简单版本约束）；分号后的环境标记、空格与任何 shell/路径
    元字符一律拒。返回 {ok, pkg, error}，不在这里起进程装包。
    """
    tpl = tpl or {}
    raw = str(p or "").strip()
    if not raw:
        return {"ok": False, "pkg": "", "error": tpl.get("pkg_empty") or ""}
    if any(ch in _PKG_DANGEROUS for ch in raw):
        t = tpl.get("pkg_bad") or ""
        return {"ok": False, "pkg": raw, "error": t.format(pkg=raw) if t else ""}
    for sep in ("==", ">=", "<=", "~=", "!=", "<", ">", "["):
        idx = raw.find(sep)
        if idx != -1:
            raw = raw[:idx]
    raw = raw.strip().strip("'\"")
    if not raw:
        return {"ok": False, "pkg": "", "error": tpl.get("pkg_empty") or ""}
    if not raw[0].isalnum() or any(ch not in _PKG_ALLOWED for ch in raw):
        t = tpl.get("pkg_bad") or ""
        return {"ok": False, "pkg": raw,
                "error": t.format(pkg=raw) if t else ""}
    return {"ok": True, "pkg": raw, "error": ""}


def tool_defs():
    """拆解循环可调用的受限工具定义（供 ReAct 生成 function schema）。

    只开放"拉取文档文本"与"白名单装单个 pip 包"两个动作；不开放任意 shell。
    工具实现挂在拆解模块注册表，执行与边界在闭环内。
    """
    return [
        {"name": "fetch_url", "desc": "拉取一个 http(s) 文档链接的正文文本（只读 GET）；"
                                      "用于补读包内引用的说明/requirements 文件。",
         "params": [{"name": "url", "type": "string", "desc": "要拉取的 http(s) URL",
                     "required": True}]},
        {"name": "pip_install", "desc": "把缺失的 Python 包装进当前运行环境；包名经白名单"
                                        "校验，固定走 pip install，不执行任意命令。",
         "params": [{"name": "pkg", "type": "string",
                     "desc": "Python 包名，可带版本约束（如 python-pptx==1.0）",
                     "required": True}]},
        {"name": "shell", "desc": "在运行环境执行一条命令：argv 数组直传、不经 shell；"
                                  "用于拆解期补装依赖、拉取资源、跑随包脚本。",
         "params": [{"name": "argv", "type": "list",
                     "desc": "命令与参数数组，如 [\"python\",\"-m\",\"pip\",\"install\",\"x\"]",
                     "required": True},
                    {"name": "cwd", "type": "string", "desc": "工作目录（可选）",
                     "required": False},
                    {"name": "timeout", "type": "number", "desc": "超时秒（可选，默认 300）",
                     "required": False}]},
    ]


def parse_skill_doc(p):
    """包文本 → 结构化元数据：标识/说明、Python 依赖、脚本资源清单。

    输入是需求经 store/表单取来的纯文本；这里只拆结构，不判断依赖是否装好。
    """
    md = p.get("skill_md") or ""
    meta_lines, body = _split_frontmatter(md)
    meta = _parse_meta_lines(meta_lines)
    pip = [pkg for pkg in (_req_package(x) for x in (p.get("requirements") or "").splitlines()) if pkg]
    scripts = _as_list(p.get("scripts"))
    version = (meta.get("metadata") or {}).get("version") if isinstance(meta.get("metadata"), dict) else ""
    return {
        "meta": {
            "id": (meta.get("name") or "").strip(),
            "doc": (meta.get("description") or "").strip(),
            "version": (version or "").strip(),
        },
        "body": body.strip(),
        "pip": pip,
        "scripts": scripts,
    }


# ---- 提示词成形 ----

def _names(tools):
    return [t.get("name") for t in (tools or []) if t.get("name")]


def promptize(p):
    """把系统提示词、包内容与现有工具名单拼成对话消息；成形规则归拆解模块。"""
    system = (p.get("system") or "").strip()
    meta = p.get("meta") or {}
    tpl = p.get("tpl") or {}

    def _label(key, value):
        lab = tpl.get(key) or ""
        return ("%s：%s" % (lab, value)) if lab else str(value)

    parts = []
    if meta.get("id"):
        parts.append(_label("meta_id_label", meta["id"]))
    if meta.get("doc"):
        parts.append(_label("meta_doc_label", meta["doc"]))
    if meta.get("version"):
        parts.append(_label("meta_version_label", meta["version"]))
    if p.get("pip"):
        parts.append(_label("pip_label", "、".join(p["pip"])))
    if p.get("scripts"):
        parts.append(_label("scripts_label", "、".join(p["scripts"])))
    if p.get("body"):
        body_lab = tpl.get("body_label") or ""
        parts.append(("%s：\n%s" % (body_lab, p["body"])) if body_lab else p["body"])
    avail = "、".join(_names(p.get("tools"))) or (tpl.get("no_tools") or "")
    tools_lab = tpl.get("tools_label") or ""
    parts.append(("%s：%s" % (tools_lab, avail)) if tools_lab else avail)
    user = "\n\n".join(parts)
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": user})
    return {"messages": messages}


# ---- 模型返回成形 ----

def _norm_deps(deps, fallback_pip=None):
    """依赖声明归一为四类清单；resources 另记脚本资源。"""
    deps = deps or {}
    out = {
        "cli": _as_list(deps.get("cli")),
        "pip": _as_list(deps.get("pip")) or list(fallback_pip or []),
        "env": _as_list(deps.get("env")),
        "config": _as_list(deps.get("config")),
        "resources": _as_list(deps.get("resources")),
    }
    return out


def _norm_tool(rec, whitelist, fallback_pip, fallback_scripts):
    """模型给的新工具定义 → 成形记录；与现有工具重名的不算新工具。"""
    if not isinstance(rec, dict):
        return None, ["工具定义不是对象: %s" % rec]
    name = str(rec.get("name") or "").strip()
    if not name:
        return None, ["新工具缺少 name"]
    if name in whitelist:
        return None, [name]
    params = []
    for x in rec.get("params") or []:
        if not isinstance(x, dict):
            continue
        pname = str(x.get("name") or "").strip()
        if pname:
            params.append({"name": pname, "type": x.get("type") or "string",
                           "required": bool(x.get("required")),
                           "desc": x.get("desc") or ""})
    deps = _norm_deps(rec.get("deps"), fallback_pip)
    if fallback_scripts and not deps["resources"]:
        deps["resources"] = list(fallback_scripts)
    tool = {"name": name, "desc": str(rec.get("desc") or "").strip(),
            "params": params, "module": "decompose", "kinds": [],
            "deps": deps, "demand": "", "builtin": False}
    return tool, []


def parse(p):
    """模型返回对象 → 结构化草稿；引用现有工具核对白名单，新工具定义成形。

    缺字段给空兜底，不报错；核对规则归拆解模块。
    """
    obj = p.get("draft") or {}
    whitelist = set(_names(p.get("tools")))
    meta = p.get("meta") or {}
    fallback_pip = p.get("pip") or []
    fallback_scripts = p.get("scripts") or []
    role = obj.get("role") or {}
    flow = obj.get("flow") or {}

    kept, dropped = [], []
    for name in role.get("tools") or []:
        name = str(name or "").strip()
        if not name:
            continue
        (kept if name in whitelist else dropped).append(name)

    new_tools, tool_dropped = [], []
    for rec in obj.get("new_tools") or []:
        tool, bad = _norm_tool(rec, whitelist, fallback_pip, fallback_scripts)
        if tool:
            new_tools.append(tool)
        else:
            tool_dropped.extend(bad)

    draft_id = (meta.get("id") or "").strip()
    draft = {
        "id": draft_id,
        "role": {"cn": role.get("cn") or "",
                 "must_dos": list(role.get("must_dos") or []),
                 "forbidden": list(role.get("forbidden") or []),
                 "tools": kept},
        "flow": {"checks": list(flow.get("checks") or []),
                 "nodes": list(flow.get("nodes") or []),
                 "edges": list(flow.get("edges") or [])},
        "tools": new_tools,
    }
    return {"draft": draft, "meta": meta, "dropped": dropped + tool_dropped,
            "tools": sorted(whitelist)}


# ---- 入库记录映射 ----

def install_parts(p):
    """模型成形的拆解草稿 → 一个 Skill 单元的入库记录：岗位 + 流程 + 工具 + Skill 条目。

    字段映射归拆解模块，不写盘；流程拆不出就留空（无 checks/nodes/edges），不硬造。
    """
    draft = p.get("draft") or {}
    rid = (draft.get("id") or "").strip()
    if not rid:
        tpl = p.get("tpl") or {}
        return {"ok": False, "code": "missing_id", "status": 400,
                "error": tpl.get("missing_id") or ""}
    role = draft.get("role") or {}
    flow = draft.get("flow") or {}
    meta = p.get("meta") or {}

    role_tools = list(role.get("tools") or [])
    tool_records = []
    for tool in draft.get("tools") or []:
        if not isinstance(tool, dict) or not tool.get("name"):
            continue
        rec = dict(tool, skill=rid, builtin=False)
        tool_records.append(rec)
        if tool["name"] not in role_tools:
            role_tools.append(tool["name"])

    role_record = {"id": rid, "cn": role.get("cn") or "",
                   "must_dos": role.get("must_dos") or [],
                   "forbidden": role.get("forbidden") or [],
                   "tools": role_tools,
                   "prompt_file": "", "backend": "",
                   "skill": rid, "builtin": False}

    flow_record = {"id": rid, "role": rid, "skill": rid}
    flow_id = ""
    if flow.get("checks"):
        flow_record["checks"] = flow.get("checks")
        flow_id = rid
    if flow.get("nodes"):
        flow_record["kind"] = "process"
        flow_record["nodes"] = flow.get("nodes")
        flow_record["edges"] = flow.get("edges")
        flow_id = rid
    if not flow_id:
        flow_record = None

    skill_record = {"id": rid, "cn": role.get("cn") or rid,
                     "doc": meta.get("doc") or "",
                     "source": p.get("source") or "",
                     "version": meta.get("version") or "",
                     "status": "enabled", "role": rid, "flow": flow_id,
                     "tools": [t["name"] for t in tool_records],
                     "builtin": False,
                     "created": p.get("now") or "", "updated": p.get("now") or ""}
    return {"skill": skill_record, "role": role_record,
            "flow": flow_record, "tools": tool_records}


def install_effects(p):
    """成形的 Skill 单元 + 现有四库字典 → 落盘 effects；产物无效则不产出任何写盘动作。

    判断归拆解模块：缺 skill 记录说明拆解没成功，直接回空 effects，由需求侧
    runtime.apply 跳过，正式库不被重写。合并按 id/name 映射，不读盘、不起进程。
    """
    parts = p.get("parts") or {}
    skill = parts.get("skill") or {}
    if not skill.get("id"):
        tpl = p.get("tpl") or {}
        return {"ok": False, "effects": [],
                "error": parts.get("error") or tpl.get("invalid_parts") or ""}
    roles = dict(p.get("roles") or {})
    flows = dict(p.get("flows") or {})
    tools = dict(p.get("tools") or {})
    skills = dict(p.get("skills") or {})

    role = parts.get("role") or {}
    if role.get("id"):
        roles[role["id"]] = dict(role)
    flow = parts.get("flow")
    if flow and flow.get("id"):
        flows[flow["id"]] = dict(flow)
    for tool in parts.get("tools") or []:
        if isinstance(tool, dict) and tool.get("name"):
            tools[tool["name"]] = dict(tool)
    skills[skill["id"]] = dict(skill)

    effects = [
        {"kind": "write", "module": "agent/library",
         "path": "roles.yaml", "value": roles},
        {"kind": "write", "module": "agent_common/tools",
         "path": "tools.yaml", "value": tools},
        {"kind": "write", "module": "agent/library",
         "path": "skills.yaml", "value": skills},
    ]
    if flow and flow.get("id"):
        effects.insert(1, {"kind": "write", "module": "agent/library",
                           "path": "flows.yaml", "value": flows})
    return {"ok": True, "effects": effects}

