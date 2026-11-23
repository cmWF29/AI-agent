"""文档路径越界校验：相对路径解析成 realpath 后必须落在模块数据根之内。

只做路径推导与包含判定，不读正文、不写盘。绝对路径注入、``..`` 穿越片段、
URL/双重编码穿越、UNC、空字节、Windows 保留名、超长路径一律拒绝。
"""
from __future__ import annotations

import re
import urllib.parse

from . import _panel

MAX_PATH_LEN = 1024
MAX_SEG_LEN = 255

_WIN_RESERVED = {"CON", "PRN", "AUX", "NUL"}
_WIN_RESERVED |= {"COM%d" % i for i in range(1, 10)}
_WIN_RESERVED |= {"LPT%d" % i for i in range(1, 10)}

_ABS_RE = re.compile(r"^[A-Za-z]:[\\/]")


def _decode_twice(raw):
    """剥两层百分号编码：单层 ``%2e%2e`` 与双重 ``%252e%252e`` 都还原成字面片段再判。"""
    once = urllib.parse.unquote(raw)
    if once != raw:
        return urllib.parse.unquote(once)
    return once


def _segments(rel):
    return [s for s in str(rel or "").replace("\\", "/").split("/")
            if s not in ("", ".")]


def guard(module, rel):
    """集中越界/注入校验。

    返回 ``{ok, rel, real, root}``；失败 ``{ok: False, code, error}``。
    校验顺序：空字节 → 总长 → 编码还原 → 绝对/UNC → 穿越片段 → 保留名/段长 → realpath 包含。
    """
    raw = str(rel or "")
    if "\x00" in raw:
        return {"ok": False, "code": "null_byte", "error": "路径含空字节"}
    if len(raw) > MAX_PATH_LEN:
        return {"ok": False, "code": "path_too_long", "error": "路径超长"}

    decoded = _decode_twice(raw)
    if decoded.startswith("/") or decoded.startswith("\\\\") or _ABS_RE.match(decoded):
        return {"ok": False, "code": "abs_path",
                "error": "禁止绝对路径或 UNC 注入"}

    parts = _segments(decoded)
    if any(s == ".." for s in parts):
        return {"ok": False, "code": "traversal", "error": "路径穿越片段被拒绝"}
    for seg in parts:
        if len(seg) > MAX_SEG_LEN:
            return {"ok": False, "code": "path_too_long", "error": "路径段超长"}
        stem = seg.split(".")[0].upper()
        if stem in _WIN_RESERVED:
            return {"ok": False, "code": "reserved_name",
                    "error": "Windows 保留名被拒绝"}

    module_parts = _segments(str(module or ""))
    if any(s == ".." for s in module_parts):
        return {"ok": False, "code": "traversal", "error": "模块名含穿越片段"}

    root_real = _panel._dir_of(module).resolve(strict=False)
    real = (root_real / decoded).resolve(strict=False)
    try:
        real.relative_to(root_real)
    except ValueError:
        return {"ok": False, "code": "escape", "error": "解析后越出模块数据根"}
    return {"ok": True, "rel": raw, "real": str(real), "root": str(root_real)}


def resolve(module, rel):
    """解析模块数据根之下的相对路径。

    返回 ``{ok, rel, real, root}``；失败 ``{ok: False, code, error}``。
    """
    return guard(module, rel)
