"""验收用的路径与暂存：验证者只读被验证对象，不改它的数据。

数据布局：每个模块的数据在 <组>/<模块>/data/；部署时 AI_NEW_DATA 指向新根，
布局镜像 modules/。所以测试要"暂存一份"时，按模块拷，而不是拷一个公共 data 桶。
"""
import json
import os
import shutil
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
    return dest


def write_config(dest, config):
    path = Path(dest) / "agent_common" / "config" / "config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
