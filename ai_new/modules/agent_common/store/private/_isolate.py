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
import shutil
from pathlib import Path


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


def _cap_posix():
    bwrap = shutil.which("bwrap")
    userns = hasattr(os, "unshare")  # Linux user namespace 入口
    return {
        "os": "posix",
        "strong": {
            "tier": "userns/bwrap-or-chroot",
            "supported": bool(bwrap or userns),
            "verified": False,
            "mechanisms": ["bwrap", "unshare user namespace", "chroot"],
            "note": "强档未在本机实测；supported 仅表示机制入口存在，不代表已验证可用。",
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
    return {
        "os": "nt",
        "strong": {
            "tier": "job-object-plus-restricted-token-or-service-account-plus-acl",
            "supported": False,
            "verified": False,
            "mechanisms": ["Job Object 进程树/资源约束",
                           "CreateRestrictedToken 或低权限服务账户", "目录 ACL"],
            "note": "Windows 隔离未实现，且未在 Windows 验证；不得视为已支持。",
        },
        "weak": {
            "tier": "directory-acl-and-permissions",
            "supported": False,
            "verified": False,
            "mechanisms": ["目录 ACL", "目录权限位"],
            "note": "Windows 弱档未实现，且未在 Windows 验证。",
        },
    }


def capabilities():
    """当前 OS 的隔离档位报告；跨平台分支只在这里。"""
    return _cap_nt() if os.name == "nt" else _cap_posix()


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
        if not root_path.is_absolute():
            return {"ok": False, "code": "root_not_absolute", "status": 400,
                    "error": "项目根路径必须是绝对路径", "capability": cap}
        root_real = _real(root_path)
        dirs = _configured_dirs(root_real, pid, tid)
        for name, candidate in dirs.items():
            if not _is_within(root_real, _real(candidate)):
                return {"ok": False, "code": "escape", "status": 400,
                        "error": "目录解析越出项目根: %s" % name, "capability": cap}
        return {"ok": True, "mode": "root", "project": pid, "ticket": tid,
                "root": str(root_real),
                "dirs": {k: str(v) for k, v in dirs.items()},
                "capability": cap}

    dirs = _legacy_dirs(dir_of, pid, tid)
    return {"ok": True, "mode": "legacy", "project": pid, "ticket": tid,
            "root": None, "dirs": {k: str(v) for k, v in dirs.items()},
            "capability": cap}
