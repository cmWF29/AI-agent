"""AI_NEW 启动入口：python agent_start.py

进程入口只做一件事 —— 把装配交给组合根，然后等它返回退出码。
真正的装配、顺序推导、启动都在 ai_new/modules/boot/private/_boot.py。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ai_new.modules.agent_common.boot import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
