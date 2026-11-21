"""按运行时注册的路由 + 需求实际传参，补齐模块 data/api.yaml 的 in 契约。

背景：artifacts / ops / projects 三个模块的数据目录整体被 .gitignore 排除，
其 api.yaml 曾被误清且从未入库。契约里 in 的字段来源就是"需求 with 键"，
所以这里从需求 do 树反推，避免手抄漏字段。
"""
import os
import sys
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "ai_new/modules/agent_test/private"))

from ai_new.modules.agent_common.boot.private._boot import _build as build  # noqa: E402
from ai_new.modules.agent_common.boot.private._context import Context  # noqa: E402
from _fixtures import module_data, stage, write_config  # noqa: E402

TARGETS = {
    "artifacts": ("agent", "artifacts"),
    "ops": ("agent_common", "ops"),
    "projects": ("agent", "projects"),
}
HEAD = (
    "# 消息契约：本模块每条能力收什么、回什么。\n"
    "# in 字段由需求 with 键反推（scripts/gen_module_contracts.py 生成，可复跑）；\n"
    "# 改动路由或需求传参后重跑脚本，别手抄。\n"
)


def _walk(stmts):
    for st in stmts or []:
        if not isinstance(st, dict):
            continue
        if st.get("call"):
            yield st
        yield from _walk(st.get("do"))


def collect_inputs(prefix):
    keys = {}
    demands_dir = module_data("agent_common", "demand_engine") / "demands"
    for path in sorted(demands_dir.glob("*.yaml")):
        rec = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for st in _walk([rec]):
            route = st.get("call") or ""
            if not route.startswith(prefix + "."):
                continue
            for key in (st.get("with") or {}):
                keys.setdefault(route, set()).add(key)
    return keys


def main():
    tmp = tempfile.TemporaryDirectory()
    root = Path(tmp.name)
    stage(root)
    write_config(root, {"server": {"host": "127.0.0.1", "port": 0, "token": "t"},
                        "tickets": {"stall_check": {"enabled": False}}})
    os.environ["AI_NEW_DATA"] = str(root)
    ctx = Context(root)
    build(ctx)

    written = []
    for name, (group, mod) in TARGETS.items():
        routes = sorted(r for r in ctx.api._routes if r.split(".")[0] == name)
        inputs = collect_inputs(name)
        spec = {}
        for route in routes:
            fields = sorted(inputs.get(route) or [])
            spec[route] = {"in": {f: {"type": "any", "req": False} for f in fields},
                           "out": {}}
        dest = ROOT / "ai_new/modules" / group / mod / "data" / "api.yaml"
        body = {"module": name, "routes": spec}
        text = HEAD + yaml.safe_dump(body, allow_unicode=True, sort_keys=False, width=120)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8")
        written.append((str(dest.relative_to(ROOT)), len(routes)))
    tmp.cleanup()
    for path, n in written:
        print("wrote %s (%d routes)" % (path, n))
    sys.stdout.flush()
    os._exit(0)   # 装配会起服务线程，写完即退


if __name__ == "__main__":
    main()
