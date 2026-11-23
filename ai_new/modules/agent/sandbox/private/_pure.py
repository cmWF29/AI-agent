"""隔离档位策略纯计算：轻/强两档描述、切换条件、资源开销、执行计划。

本文件不碰 IO、不读时钟；OS 能力探测由 host/store 路由给出，策略与计划在这里
推导。模块之间不 import。

两档口径：
- **weak（轻量隔离，默认档）**：项目独立目录 + 路径 realpath 解析与穿越拦截 +
  拒绝绝对路径注入 + 进程 cwd 约束 + 项目级跨进程锁。Linux 用独立 uid/目录
  权限位；Windows 用目录 ACL + Job Object 约束进程树/资源。
- **strong（强隔离，升级档）**：Linux unshare namespace / bwrap / 容器；
  Windows 容器 / 低权限服务账户 + 受限令牌。
"""
from __future__ import annotations

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
