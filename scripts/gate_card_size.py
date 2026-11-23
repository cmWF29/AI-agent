#!/usr/bin/env python3
"""静态卡片尺寸门禁：同一堆叠区的卡片必须整宽同高。

检查对象是控制台源码而不是渲染结果：
- `.pcard` 基类只允许 `height:var(--pcard-h)`，不允许写死数字宽高；
- 展开态 `.deck[data-open="1"] .deck-stage>.pcard` 必须整宽、同高，且清掉
  收缩态的位移与过渡；
- 模板里不允许给 `.pcard` 写内联 width/height；
- 不允许按序号/奇偶给卡片单独改宽高。
这样不需要起浏览器就能挡住"展开后一张比一张窄"的回归。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "ai_new/modules/agent/web/data/console/manage.html"
RENDER = ROOT / "ai_new/modules/agent/web/data/console/render.js"


def css_rules(text: str):
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", text):
        yield m.group(1).strip(), m.group(2)


def decl(body: str, name: str) -> str | None:
    hit = re.search(r"(?:^|;)\s*" + re.escape(name) + r"\s*:\s*([^;]+)", body)
    return hit.group(1).strip() if hit else None


def direct_card_selector(sel: str) -> bool:
    """选择器末端就是卡片本身，不是卡片里的头像/箭头等子元素。"""
    tail = sel.strip().split()[-1] if sel.strip() else ""
    return bool(re.search(r"\.pcard(?::(?:active|hover|focus))?$", tail))


def main() -> int:
    bad: list[str] = []
    if not HTML.is_file() or not RENDER.is_file():
        print("卡片尺寸门禁：缺少 manage.html / render.js")
        return 1
    html = HTML.read_text(encoding="utf-8")
    render = RENDER.read_text(encoding="utf-8")

    style = "\n".join(re.findall(r"<style[^>]*>(.*?)</style>", html, re.S))
    style = re.sub(r"/\*.*?\*/", "", style, flags=re.S)
    if not style:
        print("卡片尺寸门禁：manage.html 里没有内联样式")
        return 1

    root_h = re.findall(r"--pcard-h\s*:\s*([^;]+)", style)
    # 允许「基础值 + 一个移动端断点覆盖」两处；同一断点内只允许一份。
    if len(root_h) not in (1, 2):
        bad.append("--pcard-h 只允许基础值 + 一个断点覆盖，实际 %d 次" % len(root_h))
    expanded_ok = {"width": False, "height": False, "transform": False, "transition": False}

    for sel, body in css_rules(style):
        if ".pcard" not in sel:
            continue
        parts = [p.strip() for p in sel.split(",")]
        for part in parts:
            if direct_card_selector(part) and re.search(
                    r":(?:nth-child|nth-of-type|first-child|last-child|odd|even)", part):
                bad.append("不允许按序号给卡片单独改样式：%s" % part)
            if "data-open=\"1\"" in part and ".deck-stage" in part and direct_card_selector(part):
                w = decl(body, "width")
                h = decl(body, "height")
                tr = decl(body, "transform")
                trans = decl(body, "transition")
                if w != "100%":
                    bad.append("展开态卡片必须 width:100%%，实际 %r：%s" % (w, part))
                else:
                    expanded_ok["width"] = True
                if h != "var(--pcard-h)":
                    bad.append("展开态卡片必须 height:var(--pcard-h)，实际 %r：%s" % (h, part))
                else:
                    expanded_ok["height"] = True
                if (tr or "").replace(" ", "") != "none!important":
                    bad.append("展开态卡片必须 transform:none!important，实际 %r：%s" % (tr, part))
                else:
                    expanded_ok["transform"] = True
                if (trans or "").replace(" ", "") != "none!important":
                    bad.append("展开态卡片必须 transition:none!important，实际 %r：%s" % (trans, part))
                else:
                    expanded_ok["transition"] = True
                continue
            if not direct_card_selector(part):
                continue # 卡片内部的图标/箭头允许固定尺寸
            w = decl(body, "width")
            h = decl(body, "height")
            if w is not None and not re.fullmatch(r"(?:100%|auto|var\(--pcard-[wh]\))", w):
                bad.append("卡片宽度只能是 100%%/auto/变量，实际 %r：%s" % (w, part))
            if h is not None and not re.fullmatch(r"var\(--pcard-[wh]\)", h):
                bad.append("卡片高度只能是变量，实际 %r：%s" % (h, part))

    missing = [k for k, ok in expanded_ok.items() if not ok]
    if missing:
        bad.append("展开态尺寸规则缺字段：%s" % ", ".join(missing))

    # 模板内联尺寸：只查 pcard 本身，卡片内元素除外
    for m in re.finditer(r"class=\"[^\"]*\bpcard\b[^\"]*\"[^>]*?style=\"([^\"]*)\"", render):
        if re.search(r"(?:^|;)\s*(?:width|height)\s*:", m.group(1)):
            bad.append("render.js 的 pcard 模板不允许内联 width/height：%s" % m.group(0)[:120])

    if bad:
        print("卡片尺寸门禁：FAIL")
        for item in bad:
            print(" - " + item)
        return 1
    print("卡片尺寸门禁：PASS（基类同高，展开态整宽同高，无序号/内联尺寸）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
