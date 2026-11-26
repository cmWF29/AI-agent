"""验收用的路径与暂存：验证者只读被验证对象，不改它的数据。

数据布局：每个模块的数据在 <组>/<模块>/data/；部署时 AI_NEW_DATA 指向新根，
布局镜像 modules/。所以测试要"暂存一份"时，按模块拷，而不是拷一个公共 data 桶。
"""
import yaml
import os
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
MODULES = ROOT / "ai_new" / "modules"
GROUPS = ("agent_common", "agent", "agent_test")


def module_dir(group, name):
    """模块目录：组下面一层就是模块；"组即模块"（如 agent_test）也成立。"""
    candidate = MODULES / group / name
    return candidate if candidate.is_dir() else MODULES / group


def module_data(group, name):
    """某个模块自己的数据目录（部署覆盖优先，布局镜像 modules/）。"""
    module = module_dir(group, name)
    external = os.environ.get("AI_NEW_DATA")
    if external:
        return Path(external) / Path(*module.relative_to(MODULES).parts)
    return module / "data"


@lru_cache(maxsize=1)
def _tracked_data():
    """仓库里被 git 跟踪的数据文件集合（相对 ai_new/modules）。

    运行时会被写进模块 data 的会话/工单/日志不是源码数据，不能跟着暂存走；
    否则每次测试都继承上一轮的历史会话与工单号，断言会撞上别人的对话。
    """
    try:
        out = subprocess.run(["git", "-C", str(ROOT), "ls-files", "--", "ai_new/modules"],
                             text=True, capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    base = "ai_new/modules/"
    rows = []
    for line in (out.stdout or "").splitlines():
        if "/data/" not in line or not line.startswith(base):
            continue
        rows.append(line[len(base):])
    return rows or None


def _prune_untracked_runtime(dest):
    """拷完之后剔掉运行时产物：只保留 git 跟踪的数据文件。

    会话/工单/日志/幂等台账会被测试与门禁写进模块 data；如果原样暂存，下一轮就继承
    上一轮的历史会话与工单号（断言会撞上别人的对话）。有 git 时按跟踪清单过滤，
    没有 git（如部署包）就原样保留，不擅自删数据。
    """
    tracked = _tracked_data()
    if tracked is None:
        return
    keep = set(tracked)
    for dp, dns, fns in os.walk(dest):
        if "__pycache__" in Path(dp).parts:
            dns[:] = []
            continue
        for fn in fns:
            path = Path(dp) / fn
            rel = str(path.relative_to(dest))
            if "/data/" in rel and rel not in keep:
                try:
                    path.unlink()
                except OSError:
                    pass


def stage(dest):
    """把每个模块自己的数据拷到 dest（布局镜像 modules/），返回 dest。"""
    dest = Path(dest)
    for group in GROUPS:
        own = MODULES / group / "data"
        if own.is_dir():  # 组即模块（agent_test）：它自己的 data 就是镜像根
            shutil.copytree(own, dest / group, dirs_exist_ok=True)
        for module in sorted((MODULES / group).iterdir()):
            src = module / "data"
            if module.is_dir() and src.is_dir():
                # "组即模块"（如 agent_test）：镜像时不再多一层同名子目录
                target = dest / group if module.name == group else dest / group / module.name
                shutil.copytree(src, target, dirs_exist_ok=True)
    _prune_untracked_runtime(dest)
    return dest


def write_config(dest, config):
    path = Path(dest) / "agent_common" / "config" / "config.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False, default_flow_style=False), encoding="utf-8")
    return path
