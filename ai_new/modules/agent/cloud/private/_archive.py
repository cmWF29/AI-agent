"""archive 只读接缝：清单真源 = archive 压缩索引 + store 路径。

假定接口签名（archive 侧只读路由，待其暴露后对齐）::

    archive.index_query(ctx, {category?, older_than?, limit?})
      -> {rows: [{path, module, layer, category, status, size_orig,
                 size_comp, algorithm, checksum, compressed_at}]}

本层只经 ``ctx.api.call`` 消费该只读路由；不 import、不读 archive 的 private。
若路由尚未暴露，接缝降级为空清单并标注 ``adapter_unwired``，不抛掀翻同步流程。
"""
from __future__ import annotations

ROUTE = "archive.index_query"


def list_archived(ctx, category=None, limit=None):
    """读 archive 索引只读面；返回 ``{rows, seam}``。"""
    try:
        row = ctx.api.call(ROUTE, {"category": category, "limit": limit}, caller=None)
        rows = (row or {}).get("rows") or []
        return {"rows": rows, "seam": "wired"}
    except Exception as exc:  # noqa: BLE001 —— 接缝降级：路由缺失/未登记不阻断同步
        return {"rows": [], "seam": "adapter_unwired",
                "reason": type(exc).__name__}
