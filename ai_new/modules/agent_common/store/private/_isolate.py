"""工作区路径解析与越界校验（只读能力，不写盘）。

模块之间不 import：本文件只做纯路径推导，输入由调用方显式给出。

- 输入：``project``（项目 id）、``ticket``（事项 id，可空）、``root``（项目自定义
  绝对根路径，可空）。
- 输出：工作区根 / documents / tickets/<id> / logs / artifacts 解析后的绝对目录，
  以及当前 OS 可达的隔离档位 ``capability`` 报告。

越界规则：候选目录先 ``realpath``（解析符号链接与 ``..``），再与根 ``realpath`` 比
包含关系；落在根之外即判 ``escape``。做不到的档位在 capability 里显式标
``supported / verified = false``，不许静默降级成"已支持"。
"""
from __future__ import annotations

import os

# 平台开关只在这里断言一次：用例改这个常量，不改全局 os.name。
PLATFORM = "nt" if os.name == "nt" else "posix"
import shutil
import subprocess
from pathlib import Path

from ai_new.modules.agent_common.plat.private import _winjob


# 各层目录归属的模块：数据归谁，路径就从谁的模块数据目录推导。
_OWNERS = {
    "documents": "agent/knowledge",
    "tickets": "agent/tickets",
    "logs": "agent/logs",
    "artifacts": "agent/artifacts",
}


def _real(path):
    return Path(path).resolve(strict=False)


def _is_within(root_real, target_real):
    """target_real 是否落在 root_real 之内（含相等）。"""
    try:
        target_real.relative_to(root_real)
    except ValueError:
        return False
    return True


def _seg(value):
    """路径段归一：拒绝 ``..`` 等越界片段；非法段返回空串。"""
    seg = str(value or "").strip().replace("\\", "/")
    if not seg or seg == "." or seg == "..":
        return ""
    if ".." in seg.split("/"):
        return ""
    return seg


def _bwrap_ready():
    """强档是否真的能起：不只查 bwrap 在不在，还跑一次最小 namespace 探针。

    只在首次解析时探测，结果进程内缓存；探测失败一律降为路径档，不冒充支持。
    """
    global _BWRAP_STATE
    if _BWRAP_STATE is not None:
        return _BWRAP_STATE
    _BWRAP_STATE = False
    if PLATFORM != "posix":
        return False
    bwrap = shutil.which("bwrap")
    if not bwrap:
        return False
    probe = [bwrap, "--unshare-all", "--share-net", "--die-with-parent",
             "--new-session"]
    for path in ("/usr", "/bin", "/lib", "/lib64", "/etc"):
        if Path(path).exists():
            probe += ["--ro-bind", path, path]
    probe += ["--", "/bin/sh", "-c", "exit 0"]
    try:
        _BWRAP_STATE = subprocess.run(
            probe, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=5).returncode == 0
    except (OSError, subprocess.SubprocessError):
        _BWRAP_STATE = False
    return _BWRAP_STATE


_BWRAP_STATE = None


def _cap_posix():
    bwrap = shutil.which("bwrap")
    ready = _bwrap_ready()
    return {
        "os": "posix",
        "strong": {
            "tier": "bwrap-mount-namespace",
            "supported": bool(bwrap),
            "verified": bool(ready),
            "mechanisms": ["bwrap", "user/mount/pid namespace",
                           "project root bind-mounted at /workspace",
                           "read-only host toolchain"],
            "note": ("bwrap 已实测可起；项目根只以 /workspace 挂载视图出现。"
                     if ready else
                     "bwrap 入口存在但最小 namespace 探针未通过，实际仍走路径档。"),
        },
        "weak": {
            "tier": "independent-uid-and-directory-permissions",
            "supported": True,
            "verified": False,
            "mechanisms": ["独立 uid 运行", "目录属主/权限位"],
            "note": "弱档口径已定义；独立 uid 运行尚未在装配中落地，verified=false。",
        },
    }


def _cap_nt():
    job = _winjob.probe()
    return {
        "os": "nt",
        "strong": {
            "tier": "job-object-process-tree",
            "supported": True,
            "verified": bool(job.get("verified")),
            "mechanisms": ["Job Object 进程树", "活动进程数/内存上限",
                           "kill-on-close 收掉整棵进程树", "目录路径边界校验"],
            "note": ("Job Object 已起短进程 assign 实测通过；与 POSIX bwrap 在 "
                     "exec 的 sandbox 接口层归一为同一 engine 槽位。"
                     if job.get("verified") else
                     "Job Object 入口存在但 assign 探针未通过，实际仍走路径档。"),
        },
        "weak": {
            "tier": "directory-acl-and-path-boundary",
            "supported": True,
            "verified": True,
            "mechanisms": ["目录 ACL", "realpath 根内校验", "cwd 层级约束"],
            "note": "Windows 弱档走目录 ACL + 路径边界；不做 POSIX uid 语义的假等价。",
        },
    }


def capabilities():
    """当前 OS 的隔离档位报告；跨平台分支只在这里。"""
    return _cap_nt() if PLATFORM == "nt" else _cap_posix()


def _legacy_dirs(dir_of, pid, tid):
    """未配置自定义根：各层仍落在归属模块自己的 data 目录（存量行为，不迁移）。"""
    dirs = {
        "documents": dir_of(_OWNERS["documents"]) / "projects" / pid,
        "logs": dir_of(_OWNERS["logs"]) / "projects" / pid,
        "artifacts": dir_of(_OWNERS["artifacts"]) / "projects" / pid,
    }
    tickets_base = dir_of(_OWNERS["tickets"]) / "projects" / pid / "tickets"
    dirs["tickets"] = tickets_base / tid if tid else tickets_base
    return dirs


def _configured_dirs(root_real, pid, tid):
    """配置了自定义根：项目工作区整体收在根之下，固定分层子目录。"""
    dirs = {
        "documents": root_real / "documents",
        "logs": root_real / "logs",
        "artifacts": root_real / "artifacts",
    }
    dirs["tickets"] = root_real / "tickets" / tid if tid else root_real / "tickets"
    return dirs


def _cwd_info(raw, root_real, dirs, tid):
    """解析显式 cwd 并给出边界事实；策略由调用方（tools）决定，这里只算不判。

    返回 cwd 的 realpath、是否默认、是否在允许层、是否落在别的 ticket 目录。
    对 ``tid`` 会话，允许范围是本 ticket 目录 + 项目公共层；无 ticket 时允许项目根内。
    """
    raw = str(raw or "")
    base = dirs["tickets"] if tid else root_real
    if not raw:
        return {"cwd": str(base), "cwd_default": True, "cwd_allowed": True,
                "cwd_ticket": bool(tid), "cwd_shared": False,
                "cwd_other_ticket": False}
    p = Path(raw)
    if not p.is_absolute():
        p = base / p
    cand = _real(p)
    shared = [_real(dirs[k]) for k in ("documents", "logs", "artifacts")]
    ticket_dir = _real(dirs["tickets"]) if tid else None
    if tid:
        allowed = _is_within(ticket_dir, cand) or any(_is_within(s, cand) for s in shared)
    else:
        allowed = _is_within(root_real, cand)
    tickets_base = root_real / "tickets"
    other = bool(tid and ticket_dir and _is_within(tickets_base, cand)
                 and not _is_within(ticket_dir, cand))
    return {"cwd": str(cand), "cwd_default": False, "cwd_allowed": allowed,
            "cwd_ticket": bool(ticket_dir and _is_within(ticket_dir, cand)),
            "cwd_shared": any(_is_within(s, cand) for s in shared),
            "cwd_other_ticket": other}


def _sandbox_info(root_real, dirs, tid, cwd):
    """给执行层的强档描述：Linux=bwrap mount，Windows=Job Object。

    ticket 会话只挂本 ticket 目录 + 三个公共层，项目根不整体暴露；无 ticket 的
    项目会话才把整个项目根挂到 /workspace。这样 mount namespace 内也看不到别的
    ticket 目录，不是只靠 cwd 字符串拦。
    """
    if PLATFORM == "nt":
        if not _winjob.ready():
            return {"engine": "path"}
        return {"engine": "winjob", "root": str(root_real), "cwd": str(cwd),
                "mount": str(root_real),
                "limits": {"active_processes": 64, "memory_mb": 4096}}
    if not _bwrap_ready():
        return {"engine": "path"}
    try:
        rel = Path(cwd).relative_to(root_real)
    except ValueError:
        return {"engine": "path"}
    rel_posix = rel.as_posix()
    target = "/workspace" if rel_posix in ("", ".") else "/workspace/" + rel_posix
    binds = []
    if tid:
        binds.append({"src": dirs["tickets"], "dst": "/workspace/tickets/%s" % tid})
        for layer in ("documents", "logs", "artifacts"):
            binds.append({"src": dirs[layer], "dst": "/workspace/" + layer})
    else:
        binds.append({"src": str(root_real), "dst": "/workspace"})
    return {"engine": "bwrap", "root": str(root_real),
            "mount": "/workspace", "cwd": target, "binds": binds}


def resolve_workspace(payload, dir_of=None):
    """解析项目工作区目录（含 ticket 子目录）并做越界校验。

    ``dir_of`` 注入模块数据目录推导（同模块私有直调）；缺省用 store 自己的推导。
    返回形状：``{ok, mode, project, ticket, root, dirs, capability}``，失败时带
    ``code / status / error``。
    """
    payload = payload or {}
    cap = capabilities()
    pid = _seg(payload.get("project"))
    tid = _seg(payload.get("ticket"))
    if not pid:
        return {"ok": False, "code": "missing_project", "status": 400,
                "error": "project 不能为空", "capability": cap}

    if dir_of is None:
        from . import _panel
        dir_of = _panel._dir_of

    root_raw = str(payload.get("root") or "").strip()
    if root_raw:
        root_path = Path(root_raw)
        # 文件系统根会被当成“项目根 + 固定子目录”，cwd 永远进不了真实仓库，
        # 且 bwrap 也拒绝 root=/；在落档前就拒，避免建出“看着配了、实际跑不了”的项目。
        if root_path == root_path.parent:
            return {"ok": False, "code": "root_unsafe", "status": 400,
                    "error": "项目根不能是文件系统根目录", "capability": cap}
        if not root_path.is_absolute():
            return {"ok": False, "code": "root_not_absolute", "status": 400,
                    "error": "项目根路径必须是绝对路径", "capability": cap}
        root_real = _real(root_path)
        dirs = _configured_dirs(root_real, pid, tid)
        for name, candidate in dirs.items():
            if not _is_within(root_real, _real(candidate)):
                return {"ok": False, "code": "escape", "status": 400,
                        "error": "目录解析越出项目根: %s" % name, "capability": cap}
        out = {"ok": True, "mode": "root", "project": pid, "ticket": tid,
               "root": str(root_real),
               "dirs": {k: str(v) for k, v in dirs.items()},
               "capability": cap}
        out.update(_cwd_info(payload.get("cwd"), root_real, dirs, tid))
        out["sandbox"] = _sandbox_info(root_real, dirs, tid, out["cwd"])
        return out

    dirs = _legacy_dirs(dir_of, pid, tid)
    return {"ok": True, "mode": "legacy", "project": pid, "ticket": tid,
            "root": None, "dirs": {k: str(v) for k, v in dirs.items()},
            "sandbox": {"engine": "path"}, "capability": cap}
