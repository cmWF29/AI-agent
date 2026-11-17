"""工具库纯函数：注册表清单成形。不读盘、不裁剪、不执行。"""
from __future__ import annotations


def listing(p):
    """注册表全量工具翻成只读清单行：参数与可见类型成形为可读文本。

    成形规则归工具模块；注册表只负责登记，清单视图只认这里给好的行。
    """
    rows = []
    for t in p.get("tools") or []:
        params = t.get("params") or []
        param_text = "; ".join(
            "%s: %s%s" % (x.get("name") or "", x.get("type") or "string",
                          "*" if x.get("required") else "")
            for x in params)
        kinds = t.get("kinds") or []
        kinds_text = "全部" if not kinds else "、".join(str(k) for k in kinds)
        rows.append({"name": t.get("name") or "", "desc": t.get("desc") or "",
                     "module": t.get("module") or "", "params": param_text,
                     "kinds": kinds_text})
    return {"items": rows}
