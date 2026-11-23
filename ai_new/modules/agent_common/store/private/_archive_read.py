"""透明读出口：原文在就读原文；原文不在则按索引读压缩流。

store 是文件 IO 收编方，解压解析统一走这里；logs / trace / channel / artifacts
不用各自改读路径，经过 store 的读都会落到这个出口。

解析委托给 archive 模块的内部路由；store 不持有压缩算法与索引形状。
"""
from __future__ import annotations

from pathlib import Path


def read_bytes_resolved(ctx, path):
    """读字节：原文缺失时回落到压缩流；不存在返回 None。"""
    p = Path(path)
    if p.is_file():
        return p.read_bytes()
    res = ctx.api.call("archive.resolve_abs", {"abs": str(p)}, caller=None)
    if not res.get("exists"):
        return None
    return res["raw"]


def read_text_resolved(ctx, path):
    """读文本：解压后按 utf-8 解码（替换坏字节）；不存在返回 None。"""
    raw = read_bytes_resolved(ctx, path)
    if raw is None:
        return None
    return raw.decode("utf-8", errors="replace")
