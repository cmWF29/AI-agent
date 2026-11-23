"""拆解纯函数：包内容解析、提示词成形、模型返回成形、入库记录映射。

不读盘、不取时间、不调模型；模型返回的对象已由闭环解码后交进来。
Skill.md 的 frontmatter 与 requirements.txt 都是纯文本，这里手写极简解析，
不借 yaml/json 标准库（编解码归 codec，文件读取归 store）。
拆解结果直接成形为一个 Skill 单元（岗位 + 流程 + 工具），不再经过草稿待确认。

安全边界相关纯函数（包扫描 / 环境探测 / 依赖计划 / 审计条目 / 登记守卫 / 幂等键）
同样不读盘、不起进程、不带业务默认数据；主机事实由路由层探测后整份传入。
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
# 包名/版本约束里都不该出现的注入字符：空格、管道、后台、替换、路径、括号、通配、
# 命令分隔符与换行（; && | ` $() 换行注入一律拒，固定 argv 直传不经 shell）。
_PKG_DANGEROUS = set(" |&$`/\\(){}*?#\"';\n\r")


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


def _norm_check(rec):
    """模型给的交付件检查项 → 岗位记录里的契约检查对象；裸文本收成 note 备注。

    契约字段：kind / paths / match / min_bytes / min_len / text。非对象、空文本丢弃。
    """
    if isinstance(rec, dict):
        kind = str(rec.get("kind") or "").strip() or "note"
        out = {"kind": kind}
        paths = [str(x).strip() for x in (rec.get("paths") or []) if str(x).strip()]
        if paths:
            out["paths"] = paths
        if rec.get("match"):
            out["match"] = rec["match"]
        if rec.get("text") is not None:
            out["text"] = str(rec["text"])
        if rec.get("min_bytes") is not None:
            out["min_bytes"] = rec["min_bytes"]
        if rec.get("min_len") is not None:
            out["min_len"] = rec["min_len"]
        return out
    text = str(rec or "").strip()
    if not text:
        return None
    return {"kind": "note", "text": text}


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

    checks = [c for c in (_norm_check(x) for x in flow.get("checks") or []) if c]

    draft_id = (meta.get("id") or "").strip()
    draft = {
        "id": draft_id,
        "role": {"cn": role.get("cn") or "",
                 "must_dos": list(role.get("must_dos") or []),
                 "forbidden": list(role.get("forbidden") or []),
                 "tools": kept},
        "flow": {"checks": checks,
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
    meta = p.get("meta") or {}
    # 标识优先取预检任务登记的技能 id（bundle.id），其次模型草稿 id，再回退包
    # frontmatter 的 name：包名本来就是业界通用的技能名。
    # 只去首尾空白，不改写大小写与分隔符——标识是外部生态里的原名，改了就对不上。
    rid = str(p.get("id") or draft.get("id") or meta.get("id") or meta.get("name") or "").strip()
    if not rid:
        tpl = p.get("tpl") or {}
        return {"ok": False, "code": "missing_id", "status": 400,
                "error": tpl.get("missing_id") or ""}
    role = draft.get("role") or {}
    flow = draft.get("flow") or {}

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
                   "prompt_file": "",
                   "skill": rid, "builtin": False}
    # 状态机与验收检查直接写在岗位记录里：不再另存一份同名流程，避免一处定义两处存。
    if flow.get("checks"):
        role_record["checks"] = flow.get("checks")
    if flow.get("nodes"):
        role_record["kind"] = "process"
        role_record["nodes"] = flow.get("nodes")
        role_record["edges"] = flow.get("edges")

    skill_record = {"id": rid, "cn": role.get("cn") or rid,
                     "doc": meta.get("doc") or "",
                     "source": p.get("source") or "",
                     "version": meta.get("version") or "",
                     "status": "enabled", "role": rid,
                     "tools": [t["name"] for t in tool_records],
                     "builtin": False,
                     "created": p.get("now") or "", "updated": p.get("now") or ""}
    return {"skill": skill_record, "role": role_record, "tools": tool_records}


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
    tools = dict(p.get("tools") or {})
    skills = dict(p.get("skills") or {})

    role = parts.get("role") or {}
    if role.get("id"):
        roles[role["id"]] = dict(role)
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
    return {"ok": True, "effects": effects}


# ---------------------------------------------------------------- 包安全扫描

# 扫描上限策略默认值（可由 payload.limits 覆盖）；是策略常量，不是业务数据。
_SCAN_DEFAULTS = {
    "max_files": 32,
    "max_file_bytes": 64 * 1024,
    "max_text_chars": 16000,
    "max_bundle_bytes": 256 * 1024,
}
# 包内允许出现的文件名 / 后缀：说明文档、清单与文本资源；脚本一律不收进包。
_ALLOWED_NAMES = {"LICENSE", "README", "requirements.txt", "pyproject.toml"}
_ALLOWED_SUFFIX = (".md", ".txt", ".yaml", ".yml", ".toml")


def _scan_limits(overrides):
    limits = dict(_SCAN_DEFAULTS)
    for key, val in (overrides or {}).items():
        if isinstance(val, int) and val > 0:
            limits[key] = val
    return limits


def _segments(path):
    return [seg for seg in str(path or "").split("/") if seg not in ("", ".")]


def scan_bundle(p):
    """不可信包清单安全校验：白名单后缀、路径穿越 / 绝对路径 / 符号链接逃逸、大小与数量上限。

    入参: files=[{path, text, link?, is_link?}], limits?(可选覆盖), tpl?(文案)
    回包: ok / accepted / rejected / totals / limits。任一文件越界即 ok=False，
    被拒条目带 code 与原因；不落盘、不起进程。
    """
    limits = _scan_limits(p.get("limits"))
    files = p.get("files") or []
    tpl = p.get("tpl") or {}
    accepted, rejected = [], []
    total_bytes = 0

    def reject(path, code):
        rejected.append({"path": path, "code": code, "reason": tpl.get(code) or ""})

    for entry in files:
        if not isinstance(entry, dict):
            reject("", "bad_entry")
            continue
        path = str(entry.get("path") or "").strip()
        text = entry.get("text")
        text = text if isinstance(text, str) else ""
        if not path:
            reject(path, "empty_path")
            continue
        if "\\" in path:
            reject(path, "bad_separator")
            continue
        if path.startswith("/") or path.startswith("~") or (len(path) > 1 and path[1] == ":"):
            reject(path, "absolute_path")
            continue
        segs = _segments(path)
        if any(seg == ".." for seg in segs):
            reject(path, "path_traversal")
            continue
        link = str(entry.get("link") or "").strip()
        if entry.get("is_link") or link:
            if link.startswith("/") or link.startswith("~") or any(s == ".." for s in _segments(link)):
                reject(path, "symlink_escape")
                continue
        name = segs[-1] if segs else path
        ok_name = name in _ALLOWED_NAMES or name.endswith(_ALLOWED_SUFFIX)
        if not ok_name:
            reject(path, "disallowed_type")
            continue
        raw_bytes = len(text.encode("utf-8"))
        if raw_bytes > limits["max_file_bytes"]:
            reject(path, "oversized_file")
            continue
        if len(text) > limits["max_text_chars"]:
            reject(path, "oversized_text")
            continue
        accepted.append({"path": path, "bytes": raw_bytes})
        total_bytes += raw_bytes

    if len(files) > limits["max_files"]:
        rejected.append({"path": "", "code": "too_many_files",
                         "reason": tpl.get("too_many_files") or ""})
    if total_bytes > limits["max_bundle_bytes"]:
        rejected.append({"path": "", "code": "oversized_bundle",
                         "reason": tpl.get("oversized_bundle") or ""})
    if not files:
        rejected.append({"path": "", "code": "empty_bundle", "reason": tpl.get("empty_bundle") or ""})

    return {"ok": not rejected, "accepted": accepted, "rejected": rejected,
            "totals": {"files": len(files), "bytes": total_bytes}, "limits": limits}


# ---------------------------------------------------------------- 环境探测

def env_probe(p):
    """从包声明的运行时 / 依赖推导缺失命令与环境变量；纯计算，不碰主机。

    入参: runtime?(命令清单), deps?{cli, env}, snapshot?{cli:{name:found}, env:{name:value}}
    回包: ready / missing{cli,env} / checked{cli,env}。主机探测结果由路由层传入。
    """
    deps = p.get("deps") or {}
    cli = _as_list(deps.get("cli")) or _as_list(p.get("runtime"))
    env = _as_list(deps.get("env"))
    snap = p.get("snapshot") or {}
    cli_snap = snap.get("cli") or {}
    env_snap = snap.get("env") or {}
    missing_cli = [c for c in cli if not cli_snap.get(c)]
    missing_env = [e for e in env if not str(env_snap.get(e) or "").strip()]
    return {"ready": not missing_cli and not missing_env,
            "missing": {"cli": missing_cli, "env": missing_env},
            "checked": {"cli": cli, "env": env}}


# ---------------------------------------------------------------- 依赖计划

def dep_plan(p):
    """requirements 清单 ∩ 已装快照 → 缺失清单与固定 argv 安装计划。

    入参: requirements=[str], installed=[pkg 名], tpl?(文案)
    回包: plan / missing / rejected / installed。包名先过 safe_pkg 白名单校验，
    非法条目进 rejected（code=bad_pkg），不进安装计划；不在这里起进程装包。
    """
    requirements = p.get("requirements") or []
    installed = list(p.get("installed") or [])
    installed_set = {str(x).strip().lower() for x in installed}
    plan, missing, rejected = [], [], []
    for req in requirements:
        line = str(req or "").strip()
        if not line or line.startswith("#"):
            continue
        chk = safe_pkg(line, p.get("tpl") or {})
        if not chk["ok"]:
            rejected.append({"requirement": line, "code": "bad_pkg",
                             "error": chk["error"]})
            continue
        pkg = chk["pkg"]
        entry = {"pkg": pkg, "requirement": line,
                 "installed": pkg.lower() in installed_set}
        plan.append(entry)
        if not entry["installed"]:
            missing.append(entry)
    return {"plan": plan, "missing": missing, "rejected": rejected,
            "installed": sorted(installed_set)}


# ---------------------------------------------------------------- 审计条目

def audit_record(p):
    """组装一条拆解审计条目：来源 / 许可证 / 版本 / 时间 / 包清单 / 依赖与结果。

    纯字典成形；时间戳与主机事实由路由层传入。许可证与来源必须留痕，缺失也显式记空。
    """
    return {
        "action": str(p.get("action") or ""),
        "at": p.get("at") or "",
        "source": str(p.get("source") or ""),
        "license": str(p.get("license") or ""),
        "version": str(p.get("version") or ""),
        "skill": str(p.get("skill") or ""),
        "bundle": p.get("bundle") or {"files": [], "bytes": 0},
        "deps": p.get("deps") or {},
        "result": p.get("result") or {},
    }


# ---------------------------------------------------------------- 登记守卫

def register_guard(p):
    """生成物与既有库 / builtin 的冲突判定：builtin 核心字段受保护，只允许新增或覆盖非 builtin。

    入参: products={role:{id}, tools:[{name}]}, existing={roles,tools},
          builtin_ids=[岗位], builtin_tools=[工具]
    回包: ok / writable{role,tools} / rejected[{kind,id,code,reason}]。
    命中 builtin 岗位或内置工具即拒绝并给错误码；非 builtin 同名记 override 允许覆盖。
    """
    products = p.get("products") or {}
    existing = p.get("existing") or {}
    roles = existing.get("roles") or {}
    tools = existing.get("tools") or {}
    builtin_ids = set(p.get("builtin_ids") or [])
    builtin_tools = set(p.get("builtin_tools") or [])
    tpl = p.get("tpl") or {}
    rejected = []

    role = products.get("role") or {}
    rid = str(role.get("id") or "").strip()
    writable_role = None
    if rid:
        if rid in builtin_ids:
            rejected.append({"kind": "role", "id": rid, "code": "builtin_protected",
                             "reason": tpl.get("builtin_protected") or ""})
        else:
            writable_role = {"id": rid, "override": rid in roles}

    writable_tools = []
    for tool in products.get("tools") or []:
        if not isinstance(tool, dict):
            continue
        name = str(tool.get("name") or "").strip()
        if not name:
            continue
        if name in builtin_tools:
            rejected.append({"kind": "tool", "id": name, "code": "builtin_tool_collision",
                             "reason": tpl.get("builtin_tool_collision") or ""})
        else:
            writable_tools.append({"name": name, "override": name in tools})

    return {"ok": not rejected,
            "writable": {"role": writable_role, "tools": writable_tools},
            "rejected": rejected}


# ---------------------------------------------------------------- 幂等键

def idempotent_key(p):
    """同一 skill 标识 + 版本 → 标识与版本归一；摘要由路由层走 codec.digest。

    回包: id / version。不取用外部自报的幂等号。
    """
    rid = str(p.get("id") or "").strip()
    version = str(p.get("version") or "").strip()
    return {"id": rid, "version": version}

