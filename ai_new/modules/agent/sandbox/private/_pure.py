"""隔离档位策略纯计算：轻/强两档描述、切换条件、资源开销、执行计划。

本文件不碰 IO、不读时钟；OS 能力探测由 host/store 路由给出，策略与计划在这里
推导。模块之间不 import。

两档口径：
- **weak（轻量隔离，默认档）**：项目独立目录 + 路径 realpath 解析与穿越拦截 +
  拒绝绝对路径注入 + 进程 cwd 约束 + 项目级跨进程锁。Linux 用独立 uid/目录
  权限位；Windows 用目录 ACL + Job Object 约束进程树/资源。
- **strong（强隔离，升级档）**：Linux unshare namespace / bwrap / 容器；
  Windows 容器 / 低权限服务账户 + 受限令牌。

路径守卫分平台：Windows 语义（盘符/UNC/保留名/长路径前缀/段尾点空格/大小写
不敏感）见 ``_winpath``；POSIX 段归一在这里完成。真实符号链接/junction 逃逸
必须在 realpath 之后复核（store/_isolate 已做 POSIX 复核）。
"""
from __future__ import annotations

from . import _winpath

WEAK = {
    "tier": "weak",
    "title": "轻量隔离（默认档）",
    "mechanisms": {
        "linux": [
            "独立运行 uid（或当前受限账户）",
            "项目独立目录，属主/权限位 0700",
            "路径 realpath 解析，符号链接与 .. 归一后做包含判定",
            "拒绝绝对路径注入与盘符路径",
            "进程 cwd 约束在项目根之内",
            "项目级跨进程锁：POSIX fcntl.flock",
        ],
        "windows": [
            "目录 ACL 限项目主体，拒绝跨主体访问",
            "Job Object 约束进程树、CPU/内存/句柄上限",
            "路径 realpath 解析与穿越拦截",
            "拒绝绝对路径注入",
            "进程 cwd 约束在项目根之内",
            "项目级跨进程锁：msvcrt.locking",
        ],
    },
    "overhead": {
        "memory": "≈0：不额外起隔离实例",
        "cpu": "≈0：仅路径解析与锁的系统调用",
        "setup_latency": "毫秒级",
        "strength": "防误越界、防串项目；不防同机特权进程，不防恶意代码逃逸",
    },
}

STRONG = {
    "tier": "strong",
    "title": "强隔离（升级档）",
    "mechanisms": {
        "linux": [
            "unshare user/mount/pid namespace",
            "bwrap 沙箱（二进制可用时优先）",
            "chroot 或 OCI 容器运行时",
            "独立 uid + 只读根 + 受限能力集",
        ],
        "windows": [
            "Windows Container / Hyper-V 隔离容器",
            "低权限服务账户 + CreateRestrictedToken 受限令牌",
            "目录 ACL 复核",
        ],
    },
    "overhead": {
        "memory": "每隔离实例数十~数百 MB",
        "cpu": "namespace/容器运行时额外开销",
        "setup_latency": "百毫秒~秒级",
        "strength": "进程/文件系统/挂载视图隔离；恶意代码逃逸面显著收窄",
    },
}

# 升级到强隔离的触发条件（满足其一即建议 strong）
UPGRADE_CONDITIONS = [
    "执行来自外部交付件或不可信代码（脚本、二进制、模型产物）",
    "多租户不可信输入同机共存，要求文件系统/进程视图互不可见",
    "需要限制网络访问、挂载可见性或系统调用面",
    "合规要求进程级隔离与资源限额审计",
]

# 维持轻量档的条件（全部成立才保持 weak）
KEEP_WEAK_CONDITIONS = [
    "执行体为本系统自产的工单/知识处理逻辑，输入落在项目作用域内",
    "仅需项目间目录/定时器/知识不可见，不存在恶意代码执行面",
    "资源预算不允许每项目一个隔离实例",
]


def describe():
    """两档描述 + 条件 + 开销表（只读策略数据，不含本机探测结果）。"""
    return {
        "weak": WEAK,
        "strong": STRONG,
        "upgrade_conditions": UPGRADE_CONDITIONS,
        "keep_weak_conditions": KEEP_WEAK_CONDITIONS,
    }


def _root_segments(root):
    seg = str(root or "").strip().replace("\\", "/")
    if not seg:
        return None, "empty_root"
    if not seg.startswith("/"):
        return None, "root_not_absolute"
    parts = [p for p in seg.split("/") if p not in ("", ".")]
    if ".." in parts:
        return None, "traversal"
    return "/" + "/".join(parts), None


def validate_root(root):
    """项目根路径校验：必须绝对、无 .. 穿越片段。"""
    normalized, code = _root_segments(root)
    if code:
        return {"ok": False, "code": code}
    return {"ok": True, "root": normalized}


def pick_tier(policy):
    """按策略选择档位。

    ``policy.tier`` 显式 weak/strong 优先；否则按标志位判定：
    untrusted_code / multi_tenant / network_restrict / audit_isolation 任一
    为真即 strong；缺省 weak。
    """
    policy = policy or {}
    explicit = str(policy.get("tier") or "").strip().lower()
    if explicit in ("weak", "strong"):
        return {"tier": explicit, "reason": "policy_requested"}
    flagged = [key for key in ("untrusted_code", "multi_tenant",
                               "network_restrict", "audit_isolation")
               if policy.get(key) is True]
    if flagged:
        return {"tier": "strong", "reason": "condition_matched",
                "flags": flagged, "conditions": UPGRADE_CONDITIONS}
    return {"tier": "weak", "reason": "default",
            "conditions": KEEP_WEAK_CONDITIONS}


def plan(project, tier, workspace):
    """生成执行计划（纯计划，不起进程、不写盘）。

    workspace: {root, lock_path?}。计划给出 cwd、锁路径、受限环境变量；
    strong 档附 wrap 描述符，真正起进程由 exec 能力在需求编排下执行。
    """
    workspace = workspace or {}
    project = str(project or "").strip()
    root_check = validate_root(workspace.get("root"))
    if not root_check["ok"]:
        return {"ok": False, "code": root_check["code"]}
    root = root_check["root"]
    lock_path = str(workspace.get("lock_path") or "").strip() or (
        root + "/.locks/" + project + ".lock")
    chosen = tier or pick_tier({}).get("tier")
    out = {
        "ok": True,
        "project": project,
        "tier": chosen,
        "cwd": root,
        "lock_path": lock_path,
        "env": {"AI_NEW_PROJECT": project},
        "strong_wrap": None,
    }
    if chosen == "strong":
        out["strong_wrap"] = {
            "linux": ["unshare", "--user", "--map-root-user", "--mount", "--pid"],
            "windows": ["container", "job-object", "restricted-token"],
        }
    return out


# ---------------------------------------------------------------- 路径守卫

def _posix_norm(path):
    """POSIX 纯字符串归一：``.`` 丢弃，``..`` 弹栈；不解析真实链接。"""
    parts = []
    for seg in str(path or "").split("/"):
        if seg in ("", "."):
            continue
        if seg == "..":
            if parts:
                parts.pop()
            continue
        parts.append(seg)
    return "/" + "/".join(parts)


def _posix_guard(root, target):
    if not str(root or "").strip():
        return {"ok": False, "code": "empty_root"}
    if not str(target or "").strip():
        return {"ok": False, "code": "empty_target"}
    if not str(root).startswith("/"):
        return {"ok": False, "code": "root_not_absolute"}
    if not str(target).startswith("/"):
        return {"ok": False, "code": "root_not_absolute"}
    if ".." in str(root).split("/") or ".." in str(target).split("/"):
        return {"ok": False, "code": "traversal"}
    rc, tc = _posix_norm(root), _posix_norm(target)
    within = tc == rc or tc.startswith(rc + "/")
    if not within:
        return {"ok": False, "code": "escape",
                "root_canonical": rc, "target_canonical": tc}
    return {"ok": True, "code": "ok",
            "root_canonical": rc, "target_canonical": tc}


def guard_path(root, target, platform="posix"):
    """平台感知的根包含守卫（纯判定，不读 stdlib）。

    ``platform``: ``"windows"/"nt"`` 走 Win32 语义（盘符/UNC/保留名/长前缀/
    段尾点空格/大小写不敏感）；``"posix"/"linux"``（缺省）走 POSIX 段归一。
    真实 OS 由路由层经 store/host 能力解析后显式传入，纯函数层不直接探 os。
    返回 ``{ok, code, ...}``，错误码与 ``_winpath`` 对齐。

    注意：本守卫只做字符串归一与包含判定；符号链接 / junction 逃逸必须由调用方
    在 realpath 之后复核（POSIX 见 store/_isolate._is_within）。
    """
    plat = str(platform or "posix").lower()
    if plat in ("windows", "nt"):
        return _winpath.guard_path(root, target)
    return _posix_guard(root, target)


# ------------------------------------------------- 轻/强档机制差异对照矩阵

# 五个隔离机制维度，逐条列 weak/strong 在 linux/windows 的落地口径；
# 供 capability 上报与用例逐条核对，不夹带本机探测结果。
MECHANISM_MATRIX = {
    "directory": {
        "weak": {
            "linux": "项目独立目录，属主/权限位 0700",
            "windows": "项目独立目录，目录 ACL 限项目主体",
        },
        "strong": {
            "linux": "独立 uid + 只读根 + 受限能力集",
            "windows": "低权限服务账户 + 目录 ACL 复核",
        },
    },
    "path_interception": {
        "weak": {
            "linux": "realpath 解析后包含判定；拒绝绝对路径/穿越段注入",
            "windows": "Win32 规范形式包含判定；拒绝盘符/UNC 逃逸、保留设备名、穿越段",
        },
        "strong": {
            "linux": "mount namespace 内只见挂载视图，越界路径不可见",
            "windows": "容器/受限令牌内文件系统视图受限，跨主体不可见",
        },
    },
    "acl": {
        "weak": {
            "linux": "目录权限位 0700（属主独占）",
            "windows": "目录 ACL 拒绝跨主体访问",
        },
        "strong": {
            "linux": "独立属主 + 只读根 + 能力裁剪",
            "windows": "受限令牌 + ACL 复核，主体边界收窄",
        },
    },
    "cwd": {
        "weak": {
            "linux": "进程 cwd 约束在项目根之内",
            "windows": "进程 cwd 约束在项目根之内",
        },
        "strong": {
            "linux": "namespace 内根目录即项目根，chroot/挂载隔离",
            "windows": "容器工作目录锁定项目根",
        },
    },
    "lock": {
        "weak": {
            "linux": "项目级跨进程锁：POSIX fcntl.flock",
            "windows": "项目级跨进程锁：msvcrt.locking",
        },
        "strong": {
            "linux": "namespace/容器内进程互斥由隔离边界保证",
            "windows": "容器内进程互斥由隔离边界保证",
        },
    },
}


def mechanism_diff():
    """轻/强档五维度机制对照（只读策略数据，不含本机探测结果）。"""
    return {
        "mechanisms": MECHANISM_MATRIX,
        "dimensions": sorted(MECHANISM_MATRIX.keys()),
    }
