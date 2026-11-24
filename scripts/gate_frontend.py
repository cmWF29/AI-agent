#!/usr/bin/env python3
"""界面信息预算门禁：网格卡只放决策所需信息，说明不铺在正文。

防的不是“丑”，而是 AI 生成界面常见的两个退化：
  1. 一张卡把日期、路径、最近、备注全摊开，列表变成字段堆；
  2. 每个区块用一段解释性 note 复述标题，用户扫不到重点。

规则：
  - ``layout: grid`` 的卡片 meta 最多 2 行；区块 note 可见字符 ≤ 24；
  - ``layout: deck`` 的卡片 note 可见字符 ≤ 32；
  - 说明性文案必须能收进详情/浮层，不允许在网格卡正文继续加解释字段；
  - 品牌区不允许渐变/发光，避免装饰性视觉盖过信息。
"""
from __future__ import annotations

import glob
import re
import sys

import yaml
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEMANDS = ROOT / "ai_new/modules/agent_common/demand_engine/data/demands"
CONSOLE_HTML = ROOT / "ai_new/modules/agent/web/data/console/manage.html"
PUNCT = re.compile(r"[{}|·，。；：、“”‘’（）()\[\]\s]")

GRID_META_MAX = 2
GRID_NOTE_MAX = 24
DECK_NOTE_MAX = 32


def _visible_len(text: str) -> int:
    """去掉占位符与标点后的可见字数：算的是用户真正要读的字，不是模板长度。"""
    text = re.sub(r"\{[^}]*\}", "", text or "")
    return len(PUNCT.sub("", text))


def _scan_specs() -> list[str]:
    bad: list[str] = []
    for path in sorted(glob.glob(str(DEMANDS / "view-*.yaml"))):
        doc = yaml.safe_load(open(path, encoding="utf-8")) or {}
        view = doc.get("view") or {}
        name = Path(path).stem
        for idx, sec in enumerate(view.get("sections") or []):
            if not isinstance(sec, dict) or sec.get("kind") != "cards":
                continue
            layout = sec.get("layout") or ""
            note = str(sec.get("note") or "")
            if layout == "grid":
                meta = sec.get("meta") or []
                if len(meta) > GRID_META_MAX:
                    bad.append("%s 区块#%d 网格卡 meta %d 行 > %d；路径/日期/备注收进详情页"
                               % (name, idx, len(meta), GRID_META_MAX))
                if _visible_len(note) > GRID_NOTE_MAX:
                    bad.append("%s 区块#%d 网格卡 note 可见 %d 字 > %d：%s"
                               % (name, idx, _visible_len(note), GRID_NOTE_MAX, note[:50]))
            elif layout == "deck":
                if _visible_len(note) > DECK_NOTE_MAX:
                    bad.append("%s 区块#%d 堆叠卡 note 可见 %d 字 > %d：%s"
                               % (name, idx, _visible_len(note), DECK_NOTE_MAX, note[:50]))
    return bad


def _scan_brand() -> list[str]:
    src = CONSOLE_HTML.read_text(encoding="utf-8")
    bad = []
    if re.search(r"\.logo\{[^}]*linear-gradient", src):
        bad.append("品牌 logo 仍在使用渐变；改纯色，避免装饰性视觉先于信息")
    if re.search(r"\.logo\{[^}]*box-shadow", src):
        bad.append("品牌 logo 仍带阴影；去掉装饰阴影")
    return bad


def main() -> int:
    bad = _scan_specs() + _scan_brand()
    if bad:
        print("界面信息预算门禁失败：")
        for x in bad:
            print("  - " + x)
        return 1
    print("界面信息预算门禁通过：网格卡字段与说明长度受控，品牌区无渐变/发光")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
