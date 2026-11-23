"""压缩后端：gzip 为必然可用基线，zstd 为可选接入点。

约束：
- 只走 Python 库，不许调 tar / gzip / zstd 等平台命令行；
- 环境没有 ``zstandard`` 库时自动回落 gzip；装上库后改配置 ``algorithm: zstd``
  即接入，读路径与索引形状不变；
- 算法记录在索引里，解压按记录里的算法走，不猜后缀。
"""
from __future__ import annotations

import gzip
import importlib.util

_ZSTD_SPEC = importlib.util.find_spec("zstandard")
_ZSTD_INSTALLED = _ZSTD_SPEC is not None


def available_algorithms():
    out = ["gzip"]
    if _ZSTD_INSTALLED:
        out.append("zstd")
    return out


def backend_info():
    """后端档位上报：zstd 未装时显式标未接入，不冒充支持。"""
    return {
        "default": "gzip",
        "algorithms": available_algorithms(),
        "zstd": {
            "installed": _ZSTD_INSTALLED,
            "note": ("环境未装 zstandard 时走 gzip；安装库后配置 algorithm: zstd 即可接入，"
                     "无需改读路径。") if not _ZSTD_INSTALLED else "zstandard 已可导入。",
        },
    }


def _zstd_compress(data: bytes, level: int) -> bytes:
    import zstandard as zstd
    return zstd.ZstdCompressor(level=int(level or 6)).compress(data)


def _zstd_decompress(data: bytes) -> bytes:
    import zstandard as zstd
    return zstd.ZstdDecompressor().decompress(data)


def compress_bytes(data, level=6, algorithm="gzip"):
    """压缩原始字节；返回 ``{data, algorithm}``。"""
    algorithm = algorithm or "gzip"
    raw = bytes(data)
    if algorithm == "gzip":
        return {"data": gzip.compress(raw, compresslevel=int(level or 6)), "algorithm": "gzip"}
    if algorithm == "zstd":
        if not _ZSTD_INSTALLED:
            raise ValueError("zstd 未接入：环境缺少 zstandard 库")
        return {"data": _zstd_compress(raw, level), "algorithm": "zstd"}
    raise ValueError("不支持的压缩算法: %s" % algorithm)


def decompress_bytes(data, algorithm="gzip") -> bytes:
    """按记录里的算法解压；算法不匹配 / 流损坏抛异常，不静默返回坏数据。"""
    algorithm = algorithm or "gzip"
    raw = bytes(data)
    if algorithm == "gzip":
        return gzip.decompress(raw)
    if algorithm == "zstd":
        if not _ZSTD_INSTALLED:
            raise ValueError("zstd 未接入：环境缺少 zstandard 库")
        return _zstd_decompress(raw)
    raise ValueError("不支持的压缩算法: %s" % algorithm)


SUFFIX = {"gzip": ".gz", "zstd": ".zst"}


def suffix_for(algorithm: str) -> str:
    return SUFFIX.get(algorithm or "gzip", ".gz")
