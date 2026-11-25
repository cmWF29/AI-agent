"""Windows 路径语义纯判定（不碰 OS、不读盘，可在 Linux/macOS 上跑同一批单测）。

覆盖 Win32 路径规则：

- 盘符 ``C:`` / ``c:``，盘符大小写不敏感；
- 反斜杠 / 正斜杠混用，比较前统一归一；
- 大小写不敏感（比较形式归一为小写）；
- 段尾的点号 / 空格被 Win32 剥离（``file.txt. `` → ``file.txt``）；
- 保留设备名 ``CON / PRN / AUX / NUL / COM1..9 / LPT1..9``（可带扩展名）；
- UNC ``\\\\server\\share\\...``；
- 长路径前缀 ``\\\\?\\``（含 ``\\\\?\\UNC\\server\\share``）；
- 符号链接 / junction 逃逸：纯判定层只做归一后包含比对；真实链接解析必须由
  调用方在 realpath 之后复核（POSIX 见 store/_isolate，Windows 见验收清单）。

本文件不 import 其它模块，不读时钟、不写盘；所有返回都是可 JSON 序列化的
普通 dict / str / list。
"""
from __future__ import annotations

import re

LONG_PREFIX = "\\\\?\\"
LONG_UNC_PREFIX = "\\\\?\\UNC\\"
UNC_PREFIX = "\\\\"

_RESERVED_BASE = {"CON", "PRN", "AUX", "NUL"}
_RESERVED_RE = re.compile(r"^(COM|LPT)[1-9]$")
_DRIVE_RE = re.compile(r"^([A-Za-z]):$")


def strip_long_prefix(path):
    """剥离长路径前缀。

    返回 ``(kind, rest)``：kind 为 ``"unc"`` / ``"drive"``；无前缀返回 ``(None, raw)``。
    """
    raw = str(path or "")
    upper = raw.upper()
    if upper.startswith(LONG_UNC_PREFIX):
        return "unc", raw[len(LONG_UNC_PREFIX):]
    if upper.startswith(LONG_PREFIX):
        return "drive", raw[len(LONG_PREFIX):]
    return None, raw


def is_reserved_name(name):
    """段名是否为 Win32 保留设备名（大小写不敏感，忽略扩展名）。"""
    seg = str(name or "").strip()
    if not seg:
        return False
    base = seg.split(".", 1)[0].strip().upper()
    if base in _RESERVED_BASE:
        return True
    return bool(_RESERVED_RE.match(base))


def normalize_segment(seg):
    """段归一：剥段尾点号 / 空格，转小写（Win32 大小写不敏感比较）。"""
    out = str(seg or "")
    out = out.rstrip(". ")
    return out.lower()


def split_root(path):
    """把路径拆成根类型 + 根标识 + 分段。

    返回 dict::

        {kind: "drive" / "unc" / "relative",
         drive: 盘符字符串或 None, server: 主机名或 None, share: 共享名或 None,
         segments: [str, ...], canonical_root: str}

    ``segments`` 尚未做穿越/保留名判定，只做分隔拆分与段尾清理。
    """
    kind, rest = strip_long_prefix(path)
    # 统一分隔符后再判 UNC / 盘符
    flat = rest.replace("\\", "/")
    if kind == "unc" or (flat.startswith("//") and not flat.startswith("///")):
        parts = [p for p in flat.split("/") if p not in ("",)]
        if len(parts) >= 2:
            return {"kind": "unc", "drive": None,
                    "server": parts[0].lower(), "share": parts[1].lower(),
                    "segments": parts[2:],
                    "canonical_root": "//%s/%s" % (parts[0].lower(),
                                                   parts[1].lower())}
        return {"kind": "unc", "drive": None, "server": None, "share": None,
                "segments": parts[2:], "canonical_root": "//"}
    drive = None
    # 长前缀剥离后盘符仍是 "C:"，与无前缀同一判定；不存在第二种写法
    if flat and flat[1:2] == ":":
        drive = flat[:2].lower()
        flat = flat[2:]
    parts = [p for p in flat.split("/") if p not in ("", ".")]
    if drive is not None:
        return {"kind": "drive", "drive": drive, "server": None, "share": None,
                "segments": parts, "canonical_root": drive}
    return {"kind": "relative", "drive": None, "server": None, "share": None,
            "segments": parts, "canonical_root": ""}


def canonical(path):
    """生成用于包含比较的规范形式（小写、段尾点空格剥离、``/`` 分隔）。

    仅做字符串归一，不解析 ``..``；穿越段由 :func:`guard_path` 判出。
    """
    root = split_root(path)
    segs = [normalize_segment(p) for p in root["segments"]]
    segs = [p for p in segs if p not in ("", ".")]
    if root["canonical_root"]:
        if segs:
            return root["canonical_root"] + "/" + "/".join(segs)
        return root["canonical_root"]
    return "/".join(segs)


def _segment_codes(segments):
    """分段级违规判定：穿越 / 保留名。返回错误码或 None。"""
    for seg in segments:
        if seg == "..":
            return "traversal"
        if is_reserved_name(seg):
            return "reserved_name"
    return None


def guard_rel(rel):
    """相对路径守卫：拒绝绝对路径、盘符、UNC、穿越段、保留设备名。

    返回 ``{ok: bool, code: str}``；通过时 ``code`` 为 ``"ok"``。
    """
    raw = str(rel or "").strip()
    if not raw:
        return {"ok": False, "code": "empty_target"}
    if raw.startswith("/"):
        return {"ok": False, "code": "abs_path"}
    root = split_root(raw)
    if root["kind"] != "relative":
        return {"ok": False, "code": "abs_or_drive_or_unc"}
    code = _segment_codes(root["segments"])
    if code:
        return {"ok": False, "code": code}
    return {"ok": True, "code": "ok"}


def guard_path(root, target):
    """根目录包含守卫（Windows 语义）。

    校验顺序：根非空且为绝对根 → 目标非空 → 根/目标同根型同盘符/UNC →
    无穿越段 / 保留名 → 规范形式包含在根之内。

    返回 ``{ok, code, root_canonical?, target_canonical?}``；失败码：
    ``empty_root / empty_target / root_not_absolute / root_kind_mismatch /
    drive_escape / unc_escape / traversal / reserved_name / escape``。
    """
    if not str(root or "").strip():
        return {"ok": False, "code": "empty_root"}
    if not str(target or "").strip():
        return {"ok": False, "code": "empty_target"}
    r = split_root(root)
    t = split_root(target)
    if r["kind"] == "relative":
        return {"ok": False, "code": "root_not_absolute",
                "root_canonical": r["canonical_root"]}
    if t["kind"] == "relative":
        return {"ok": False, "code": "root_not_absolute",
                "target_canonical": t["canonical_root"]}
    if r["kind"] != t["kind"]:
        return {"ok": False, "code": "root_kind_mismatch",
                "root_kind": r["kind"], "target_kind": t["kind"]}
    if r["kind"] == "drive" and r["drive"] != t["drive"]:
        return {"ok": False, "code": "drive_escape",
                "root_drive": r["drive"], "target_drive": t["drive"]}
    if r["kind"] == "unc" and (r["server"] != t["server"]
                               or r["share"] != t["share"]):
        return {"ok": False, "code": "unc_escape",
                "root": r["canonical_root"], "target": t["canonical_root"]}
    code = _segment_codes(t["segments"])
    if code:
        return {"ok": False, "code": code}
    rc = canonical(root)
    tc = canonical(target)
    if tc == rc:
        return {"ok": True, "code": "ok",
                "root_canonical": rc, "target_canonical": tc}
    if tc.startswith(rc + "/"):
        return {"ok": True, "code": "ok",
                "root_canonical": rc, "target_canonical": tc}
    return {"ok": False, "code": "escape",
            "root_canonical": rc, "target_canonical": tc}
