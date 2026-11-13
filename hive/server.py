"""Daemon 入口：python -m hive.server

生产环境由 watchdog 拉起；本地调试可以直接跑。
"""
from __future__ import annotations

import argparse
import os
import sys

from .kernel import Kernel
from .kernel.config import load_config, save_config


def main(argv=None):
    parser = argparse.ArgumentParser(prog="hive.server")
    parser.add_argument("--config", default=None, help="config.json 路径")
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--web-dir", default=None)
    parser.add_argument("--print-token", action="store_true", help="启动后打印 API token")
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    if args.host:
        cfg["server"]["host"] = args.host
    if args.port:
        cfg["server"]["port"] = args.port

    kernel = Kernel(cfg=cfg, web_dir=args.web_dir)
    kernel.boot()
    kernel.install_signals()
    kernel.start_http()

    pid_path = os.path.join(cfg["root"], "data", "agent.pid")
    os.makedirs(os.path.dirname(pid_path), exist_ok=True)
    with open(pid_path, "w", encoding="utf-8") as f:
        f.write(str(os.getpid()))

    print("=" * 68)
    print(" Hive Agent 已启动")
    print("   版本   : %s" % __import__("hive.version", fromlist=["__version__"]).__version__)
    print("   根目录 : %s" % cfg["root"])
    print("   监听   : %s" % kernel.http.url())
    print("   网页   : %s" % kernel.http.url())
    if args.print_token:
        print("   token  : %s" % kernel.http.token)
    print("=" * 68, flush=True)

    try:
        kernel.run_forever()
    finally:
        try:
            os.remove(pid_path)
        except OSError:
            pass
        kernel.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
