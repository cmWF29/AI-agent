"""工具输出策略：先落盘，再由“我们自己的代码”决定给大模型看多少。

规则（config.tool_output）：
  * 字符数 <= inline_max_chars         -> 原文内联进上下文
  * 字符数 >  inline_max_chars         -> 全文落盘，上下文里只给：路径 / 体积 / 头尾预览 / 读法提示
这一步不经过大模型判断，是我们自己的确定性逻辑，省 token 也省上下文。
"""
from __future__ import annotations

import os
import re
import time

from .store import ensure_dir, safe_id


class OutputPolicy:
    def __init__(self, cfg):
        c = cfg["tool_output"]
        self.inline_max_chars = int(c["inline_max_chars"])
        self.preview_chars = int(c["preview_chars"])
        root = c.get("root") or "data/toolout"
        self.root = root if os.path.isabs(root) else os.path.join(cfg["root"], root)
        ensure_dir(self.root)

    def _session_dir(self, session_id):
        return ensure_dir(os.path.join(self.root, safe_id(session_id)))

    def _write(self, session_id, tool_name, text):
        d = self._session_dir(session_id)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        name = "%s_%03d_%s.txt" % (stamp, int(time.time() * 1000) % 1000, safe_id(tool_name))
        path = os.path.join(d, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path

    def apply(self, session_id, tool_name, text, tool_call_id=None):
        text = text if text is not None else ""
        chars = len(text)
        if chars <= self.inline_max_chars:
            return {"mode": "inline", "chars": chars, "text": text, "path": None}

        path = self._write(session_id, tool_name, text)
        lines = text.count("\n") + 1
        head = text[: self.preview_chars]
        tail = text[-200:] if chars > self.preview_chars + 200 else ""
        notice = (
            "[输出过大，已落盘，未直接注入上下文]\n"
            "tool=%s chars=%d lines=%d\npath=%s\n"
            "---- head ----\n%s\n%s"
            "---- 读取方式 ----\n"
            "不要一次性 read_file 整份。建议：\n"
            "  1) 先用 shell: grep -n \"关键字\" %s （或 grep -c 统计）定位行号；\n"
            "  2) 再用 read_file(path=\"%s\", offset=行号-20, limit=80) 只读需要的那段；\n"
            "  3) 需要结论时先 grep 出关键行，只在上下文里保留这些行。\n"
        ) % (
            tool_name,
            chars,
            lines,
            path,
            head,
            ("---- tail ----\n%s\n" % tail) if tail else "",
            path,
            path,
        )
        return {"mode": "file", "chars": chars, "lines": lines, "text": notice, "path": path}

    def stats(self):
        return {
            "root": self.root,
            "inline_max_chars": self.inline_max_chars,
            "preview_chars": self.preview_chars,
            "files": self._count_files(),
        }

    def _count_files(self):
        total = 0
        for _, _, files in os.walk(self.root):
            total += len([f for f in files if f.endswith(".txt")])
        return total
