"""文档路径越界校验：相对路径解析成 realpath 后必须落在模块数据根之内。

只做路径推导与包含判定，不读正文、不写盘。绝对路径注入、``..`` 穿越片段、
符号链接逃逸（realpath 后比对）一律拒绝。
"""
from __future__ import annotations

from pathlib import Path

from . import _panel


def _segments(rel):
    return [s for s in str(rel or "").replace("\\", "/").split("/")
            if s not in ("", ".")]


def resolve(module, rel):
    """解析模块数据根之下的相对路径。

    返回 ``{ok, rel, real, root}``；失败 ``{ok: False, code, error}``。
    """
    raw = str(rel or "")
    if Path(raw).is_absolute():
        return {"ok": False, "code": "abs_path",
                "error": "禁止绝对路径注入"}
    parts = _segments(raw)
    if any(s == ".." for s in parts):
        return {"ok": False, "code": "traversal",
                "error": "路径穿越片段被拒绝"}
    root_real = _panel._dir_of(module).resolve(strict=False)
    real = (root_real / raw).resolve(strict=False)
    try:
        real.relative_to(root_real)
    except ValueError:
        return {"ok": False, "code": "escape",
                "error": "解析后越出模块数据根"}
    return {"ok": True, "rel": raw, "real": str(real), "root": str(root_real)}
