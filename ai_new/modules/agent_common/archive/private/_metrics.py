"""解压时延观测：进程内环形样本 + 真实分位统计。

口径：
- 样本只记真实解压耗时（perf_counter 差值），不估算、不回填；
- 环形缓冲超容量淘汰最旧样本；样本数低于阈值时显式标 ``insufficient_samples``，
  P50/P95 置空，不拿少量样本冒充分位；
- 观测态不持久化：进程重启样本清空，台账字节口径仍以索引为准。
"""
from __future__ import annotations

import math
import threading
from collections import deque

DEFAULT_MAX_SAMPLES = 256
DEFAULT_MIN_SAMPLES = 5


def _percentile(ordered: list, pct: float) -> float:
    """最近秩分位：ordered 已升序；空表返回 0。"""
    if not ordered:
        return 0.0
    rank = max(1, math.ceil(pct / 100.0 * len(ordered)))
    return ordered[rank - 1]


class LatencyRecorder:
    """解压耗时环形记录器；线程安全。"""

    def __init__(self, max_samples=DEFAULT_MAX_SAMPLES):
        self._max = int(max_samples or DEFAULT_MAX_SAMPLES)
        self._samples: "deque[float]" = deque(maxlen=self._max)
        self._lock = threading.Lock()

    def record(self, seconds: float) -> None:
        if seconds is None or seconds < 0:
            return
        with self._lock:
            self._samples.append(float(seconds))

    def configure(self, max_samples=None) -> None:
        with self._lock:
            if max_samples is not None:
                self._max = int(max_samples)
            if self._max and len(self._samples) > self._max:
                # 容量收窄时从左侧（最旧）裁掉多余样本
                while len(self._samples) > self._max:
                    self._samples.popleft()

    def snapshot(self, min_samples: int = DEFAULT_MIN_SAMPLES) -> dict:
        with self._lock:
            samples = list(self._samples)
        count = len(samples)
        if count < int(min_samples or DEFAULT_MIN_SAMPLES):
            return {"samples": count, "p50_ms": None, "p95_ms": None,
                    "status": "insufficient_samples"}
        ordered = sorted(samples)
        return {
            "samples": count,
            "p50_ms": round(_percentile(ordered, 50) * 1000, 3),
            "p95_ms": round(_percentile(ordered, 95) * 1000, 3),
            "status": "ok",
        }
