"""冷热分层判定纯函数：不碰盘、不取时间、不带默认业务数据。

阈值全部由调用方（配置）传入；本模块只回答「这条记录按给定阈值算不算冷」。
判定口径：

- 热：仍在活跃写入宽限窗口内（``age_seconds < grace_seconds``），或年龄 / 尺寸未达阈值；
- 冷：年龄 ≥ 阈值天数、尺寸 ≥ 阈值字节，且已离开写入宽限窗口。
"""
from __future__ import annotations

SECONDS_PER_DAY = 86400


def age_seconds(now_ts, mtime_ts):
    """文件年龄（秒）；时间由外部（clock）给，本函数不自带表。"""
    return max(0.0, float(now_ts or 0) - float(mtime_ts or 0))


def evaluate(record, threshold):
    """按阈值评估单条候选。

    record:    {size_bytes, age_seconds, category}
    threshold: {age_days, min_bytes, grace_seconds}

    返回 ``{cold, reason, checks, category}``；``reason`` 取值：
    ``cold`` / ``grace`` / ``age_below`` / ``size_below``。
    """
    size = int(record.get("size_bytes") or 0)
    age = float(record.get("age_seconds") or 0)
    age_days = float(threshold.get("age_days") or 0)
    min_bytes = int(threshold.get("min_bytes") or 0)
    grace = float(threshold.get("grace_seconds") or 0)

    grace_ok = age >= grace
    age_ok = age >= age_days * SECONDS_PER_DAY
    size_ok = size >= min_bytes
    cold = grace_ok and age_ok and size_ok

    if not grace_ok:
        reason = "grace"
    elif not age_ok:
        reason = "age_below"
    elif not size_ok:
        reason = "size_below"
    else:
        reason = "cold"

    return {
        "cold": cold,
        "reason": reason,
        "checks": {"grace_ok": grace_ok, "age_ok": age_ok, "size_ok": size_ok},
        "category": record.get("category") or "",
    }


# 模块元数据 / 清单类文件不参与压缩：它们是小文件且常被读写，压缩无收益还会伤索引。
SKIP_NAMES = frozenset({
    "api.yaml", "index.yaml", "messages.yaml", "session-tools.yaml",
    "config.yaml", "config.json", "manifest.json",
})


def is_skipped(name):
    """清单 / 元数据文件跳过压缩；目录与后缀由扫描层判断。"""
    return name in SKIP_NAMES
