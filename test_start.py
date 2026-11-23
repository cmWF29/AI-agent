"""AI_NEW 验收入口：python test_start.py [--only structure|assembly|language|transport|behaviour] [--smoke]

它和 agent_start.py 是平级的两个脚本 —— 系统怎么起、验收怎么跑，各有一个入口，
没有第三个"特殊目录"。

- 清单在 `data/checks.json`（验哪些、静态还是运行时）；这里只做转调。
- `--smoke` 会**真的执行 agent_start.py**：起一个临时数据目录、挑一个空闲端口、
  等它自己报到，然后核对 health / 模块数 / 需求 / hook 点 / 启动日志，最后收掉。
  静态检查证明"结构没坏"，运行时冒烟证明"它真的能跑起来"。
"""
import importlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

ENTRY = ROOT / "agent_start.py"


def _free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _get(url, path, token=""):
    req = urllib.request.Request(url + path, headers={"X-Auth-Token": token} if token else {})
    return json.load(urllib.request.urlopen(req, timeout=5))


def _stage(dest):
    """把每个模块自己的数据拷到 dest（布局镜像 modules/）。"""
    modules = ROOT / "ai_new" / "modules"
    for group in sorted(p for p in modules.iterdir() if p.is_dir()):
        for module in sorted(p for p in group.iterdir() if p.is_dir() and not p.name.startswith("__")):
            src = module / "data"
            if src.is_dir():
                shutil.copytree(src, dest / group.name / module.name, dirs_exist_ok=True)


def smoke():
    """执行真的 agent_start.py，验证它自己报到、装配齐全、控制台能开，然后收掉。"""
    workdir = Path(tempfile.mkdtemp(prefix="ai_new_smoke_"))
    data = workdir / "data"
    _stage(data)
    port = _free_port()
    config = data / "agent_common" / "config" / "config.json"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(json.dumps({
        "server": {"host": "127.0.0.1", "port": port, "token": ""},
        "tickets": {"stall_check": {"enabled": False}},
    }), encoding="utf-8")

    env = dict(os.environ, AI_NEW_DATA=str(data), AI_NEW_PORT=str(port))
    proc = subprocess.Popen([sys.executable, str(ENTRY)], cwd=str(ROOT), env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    base = "http://127.0.0.1:%d" % port
    failures = []
    try:
        live = None
        for _ in range(100):
            if proc.poll() is not None:
                break
            try:
                live = _get(base, "/api/health/live")
                break
            except Exception:  # noqa: BLE001
                time.sleep(0.1)
        if not live:
            out, err = proc.communicate(timeout=5)
            return ["agent_start.py 没能起来:\n%s\n%s" % (out[-1500:], err[-1500:])]
        print("  进程 %s 已报到：%s" % (proc.pid, live))

        modules = _get(base, "/api/health/self")["modules"]
        print("  模块: %d" % len(modules))
        if len(modules) != 38:
            failures.append("模块数不是 38: %s" % len(modules))

        demands = _get(base, "/api/demand_engine/list")
        points = _get(base, "/api/hooks/points")
        print("  需求: %s | hook 点: %d" % ([d["id"] for d in demands], len(points)))
        # 闭合而不是计数：需求的 on 必须在已声明的点里，声明的点必须有人订阅
        declared = {p["name"] for p in points}
        subscribed = set()
        for rec in demands:
            if rec.get("enabled", True):
                subscribed.update(rec.get("on") or [])
        unknown = sorted(subscribed - declared)
        orphan = sorted(declared - subscribed)
        if unknown:
            failures.append("需求订阅了没声明的点: %s" % unknown)
        if orphan:
            failures.append("这些点没有需求订阅（没有需求就不该留点）: %s" % orphan)

        page = urllib.request.urlopen(base + "/", timeout=5).read().decode("utf-8")
        print("  控制台: %d 字节，标题 %s" % (len(page), "Hive AI" in page))
        if "Hive AI" not in page:
            failures.append("控制台首页没有内容（web.asset 没走通）")

        log = data / "agent_common" / "ops" / "logs" / "app.jsonl"
        print("  运维日志: %s 行（没有需求订阅时就不该有日志）"
              % (len(log.read_text(encoding="utf-8").strip().splitlines())
                 if log.is_file() else 0))
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:  # noqa: PERF203
            proc.kill()
        shutil.rmtree(workdir, ignore_errors=True)
    return failures


def main(argv=None):
    argv = list(argv or [])
    code = importlib.import_module("ai_new.modules.agent_test").main(argv)
    if "--smoke" in argv:
        print("\n== smoke（真的执行 agent_start.py）")
        problems = smoke()
        for problem in problems:
            print("  !! %s" % problem)
        print("  冒烟结果: %s" % ("通过" if not problems else "失败"))
        if problems:
            code = 1
    return code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
