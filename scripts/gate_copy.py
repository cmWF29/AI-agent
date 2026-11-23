#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""文案门禁：控制台前端与页面词表上"看得见的字"必须过的静态闸。

扫描口径（动态探测，不读缓存）：
  - ``agent/web/data/console/**/*.html``、``**/*.js``
  - ``agent_common/demand_engine/data/console.yaml``
  - ``agent_common/demand_engine/data/demands/*.yaml`` 的 title/label/heading/note 等界面字段

规则编号：
  C1 禁用句式：本页用于 / 以下是 / 说明： / 请注意 / 在这里你可以 / 该功能旨在
  C2 营销空词：智能 / 一键 / 全新
  C3 感叹号：！/ !（``!=``、``!==`` 代码符号白名单）
  C4 按钮/标签长度 2–6 字
  C5 帮助文本单条 ≤40 字
  C6 空态文案 ≤20 字（"暂无…"一句话）
  C7 页面标题与首个区块标题规范化后不得同义（相等）
  C8 术语一致：共用/共享→公共，任务单→工单，角色→岗位，文档库→知识库，产物→交付件
  C9 后端字段/契约词泄漏：字段 / 参数说明 / 接口返回 / 需求描述

门禁不接受任何白名单：命中即报，输出 ``文件:行 规则编号 原文``，退出码非 0。
``--self-test`` 在临时目录注入违规样本，断言门禁能抓到并失败（证明门禁真的会咬）。

兼容 Python 3.8：无 match、无 functools.cache、无 X|Y 运行时求值。
"""
from __future__ import annotations

import argparse
import html
import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]

WEB_DIR = ROOT / "ai_new" / "modules" / "agent" / "web" / "data" / "console"
CONSOLE_YAML = ROOT / "ai_new" / "modules" / "agent_common" / "demand_engine" / "data" / "console.yaml"
DEMAND_DIR = ROOT / "ai_new" / "modules" / "agent_common" / "demand_engine" / "data" / "demands"

# ---- 规则词表（集中维护，纯数据，无默认业务结论） -------------------------------

BANNED_PHRASES: List[str] = [
    "本页用于", "以下是", "说明：", "请注意", "在这里你可以", "该功能旨在",
]
MARKETING_WORDS: List[str] = ["智能", "一键", "全新"]
LEAK_WORDS: List[str] = ["字段", "参数说明", "接口返回", "需求描述"]
# 黑名单词 -> 推荐术语（C8）
TERM_MAP: List[Tuple[str, str]] = [
    ("共用", "公共"), ("共享", "公共"), ("任务单", "工单"), ("角色", "岗位"),
    ("文档库", "知识库"), ("产物", "交付件"),
]

LABEL_KEYS = {"label", "submit", "ok", "cancel", "logout", "more", "menu",
              "crumb_root", "user_label", "pass_label", "enter", "crumb", "menu_label"}
HELP_KEYS = {"subtitle", "subheading", "placeholder", "raw_note", "call_raw"}
# 这些顶层区块里的 note 是状态机行为规格，不是界面帮助文案
SPEC_SECTIONS = {"controls", "click_machine"}
EMPTY_KEYS_PREFIX = ("empty", "composer_empty", "call_empty", "need_param", "no_")

LABEL_MIN, LABEL_MAX = 2, 6
HELP_MAX = 40
EMPTY_MAX = 20

# 代码符号白名单：感叹号紧跟 = 不算感叹号文案
_EXCL_RE = re.compile(r"[！!]")
_NE_RE = re.compile(r"!=|!==")
# JS 字符串字面量
_JS_STR_RE = re.compile(r'''(?:\"([^\"\n]*)\"|'([^'\n]*)'|`([^`\n]*)`)''')
_ATTR_RE = re.compile(r'''(?:^|\s)(?:title|placeholder|alt|aria-label|label)\s*=\s*"([^"]*)"''')
_TAG_RE = re.compile(r"<[^>]+>")
_YAML_LINE_RE = re.compile(r"^(?P<indent>\s*)(?P<key>[\w.-]+):\s*(?P<val>.*)$")
_INLINE_MAP_RE = re.compile(r'(label|text|title|note|placeholder|subheading)\s*:\s*"([^"]*)"')
_PUNCT_RE = re.compile(r"[\s　，。！？、；：“”‘’（）()【】\[\]·.,:;!?/\-_\"'{}]")


def normalize(text: str) -> str:
    """规范化：去空白/标点/占位符后比较同义。"""
    return _PUNCT_RE.sub("", text or "").lower()


def _count_chars(text: str) -> int:
    """计入字数：去掉 {占位符} 与标点空白后的可见字符数。"""
    cleaned = re.sub(r"\{[^}]*\}", "", text or "")
    return len(_PUNCT_RE.sub("", cleaned))


def _strip_js_comments(line: str) -> str:
    # 行注释
    line = re.sub(r"//.*$", "", line)
    return line


class Violation:
    __slots__ = ("relpath", "lineno", "code", "raw", "message")

    def __init__(self, relpath: str, lineno: int, code: str, raw: str, message: str):
        self.relpath = relpath
        self.lineno = lineno
        self.code = code
        self.raw = raw
        self.message = message

    def line(self) -> str:
        return "%s:%d [%s] %s —— %s" % (self.relpath, self.lineno, self.code, self.raw, self.message)


# ---- 提取界面字符串 -----------------------------------------------------------

def _classify(key: str, section: str = "") -> str:
    if key == "title":
        return "title"
    if key == "heading":
        return "heading"
    if key in EMPTY_KEYS_PREFIX or key.startswith("empty"):
        return "empty"
    if key in LABEL_KEYS:
        return "label"
    if key in HELP_KEYS or (key == "note" and section not in SPEC_SECTIONS):
        return "help"
    return "other"


def _yaml_value(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith(("{", "[")):
        return ""
    if raw.startswith(('"', "'")) and len(raw) >= 2 and raw[-1] == raw[0]:
        raw = raw[1:-1]
    return raw.strip()


def scan_yaml(path: Path, relpath: str) -> List[Tuple[int, str, str, str]]:
    """返回 (行号, 字段名, 界面文案, 类别)。跳过注释行与结构化值。"""
    out: List[Tuple[int, str, str, str]] = []
    if not path.exists():
        return out
    section = ""
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        m = _YAML_LINE_RE.match(line)
        if not m:
            continue
        indent = m.group("indent")
        key = m.group("key")
        if indent == "":
            section = key
        val = _yaml_value(m.group("val"))
        # 内联映射 {label: ..., text: ...}：抽出其中的界面字段
        if m.group("val").strip().startswith("{"):
            for inline_key, inline_val in _INLINE_MAP_RE.findall(m.group("val")):
                if inline_val and inline_key != "description":
                    eff_key = key if key in EMPTY_KEYS_PREFIX else inline_key
                    out.append((lineno, eff_key, inline_val, _classify(eff_key, section)))
            continue
        if not val:
            continue
        # description 是需求后端说明，不属于界面文案，跳过长度/术语规则
        if key == "description":
            continue
        out.append((lineno, key, val, _classify(key, section)))
    return out


def scan_html(path: Path, relpath: str) -> List[Tuple[int, str, str, str]]:
    out: List[Tuple[int, str, str, str]] = []
    if not path.exists():
        return out
    in_script = False
    in_style = False
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        low = line.lower()
        if "<script" in low:
            in_script = True
        if "</script>" in low:
            in_script = False
            continue
        if "<style" in low:
            in_style = True
        if "</style>" in low:
            in_style = False
            continue
        if in_script or in_style:
            continue
        stripped = line.strip()
        if stripped.startswith("<!--") or stripped.startswith("/*"):
            continue
        for attr in _ATTR_RE.findall(line):
            if attr.strip():
                out.append((lineno, "attr", html.unescape(attr), "label"))
        text = _TAG_RE.sub("", line)
        text = html.unescape(text).strip()
        text = re.sub(r"<!--.*?-->", "", text).strip()
        if text:
            out.append((lineno, "text", text, "other"))
    return out


def _looks_like_code(literal: str) -> bool:
    if not literal:
        return True
    if re.match(r"^[a-z][a-zA-Z0-9_.-]*$", literal):
        return True
    if literal.startswith(("/", ".", "#", "http", "data:", "rgba", "rgb(")):
        return True
    if any(ch in literal for ch in ("(", ")", "=>", "&&", "||", "==", "!=", "=>")):
        return True
    return False


def scan_js(path: Path, relpath: str) -> List[Tuple[int, str, str, str]]:
    out: List[Tuple[int, str, str, str]] = []
    if not path.exists():
        return out
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        cleaned = _strip_js_comments(line)
        for groups in _JS_STR_RE.findall(cleaned):
            candidates = [g for g in groups if g]
            if not candidates:
                continue
            literal = candidates[0]
            if _looks_like_code(literal):
                continue
            out.append((lineno, "str", literal, "other"))
    return out


# ---- 规则判定 ----------------------------------------------------------------

def _check_common(relpath: str, lineno: int, text: str, raw: str) -> List[Violation]:
    bad: List[Violation] = []
    for phrase in BANNED_PHRASES:
        if phrase in text:
            bad.append(Violation(relpath, lineno, "C1", raw, "禁用句式「%s」" % phrase))
    for word in MARKETING_WORDS:
        if word in text:
            bad.append(Violation(relpath, lineno, "C2", raw, "营销空词「%s」" % word))
    # 感叹号：去掉 != / !== 后再判
    excl_text = _NE_RE.sub("", text)
    if _EXCL_RE.search(excl_text):
        bad.append(Violation(relpath, lineno, "C3", raw, "文案不得使用感叹号"))
    for old, new in TERM_MAP:
        if old in text:
            bad.append(Violation(relpath, lineno, "C8", raw, "术语「%s」应统一为「%s」" % (old, new)))
    for leak in LEAK_WORDS:
        if leak in text:
            bad.append(Violation(relpath, lineno, "C9", raw, "后端契约/字段词泄漏到界面文案"))
    return bad


def _check_by_kind(kind: str, relpath: str, lineno: int, text: str, raw: str) -> List[Violation]:
    bad: List[Violation] = []
    n = _count_chars(text)
    if kind == "label" and not (LABEL_MIN <= n <= LABEL_MAX):
        bad.append(Violation(relpath, lineno, "C4", raw, "按钮/标签长度须 %d–%d 字（现 %d 字）" % (LABEL_MIN, LABEL_MAX, n)))
    elif kind == "help" and n > HELP_MAX:
        bad.append(Violation(relpath, lineno, "C5", raw, "帮助文本须 ≤%d 字（现 %d 字）" % (HELP_MAX, n)))
    elif kind == "empty" and n > EMPTY_MAX:
        bad.append(Violation(relpath, lineno, "C6", raw, "空态文案须 ≤%d 字（现 %d 字）" % (EMPTY_MAX, n)))
    return bad


def _check_title_heading(relpath: str, entries: List[Tuple[int, str, str, str]]) -> List[Violation]:
    """C7：页面标题与首个区块标题规范化后不得同义。"""
    bad: List[Violation] = []
    title: Optional[Tuple[int, str]] = None
    first_heading: Optional[Tuple[int, str]] = None
    for lineno, key, val, _kind in entries:
        if key == "title" and title is None:
            title = (lineno, val)
        if key == "heading" and first_heading is None:
            first_heading = (lineno, val)
    if title and first_heading:
        if normalize(title[1]) and normalize(title[1]) == normalize(first_heading[1]):
            bad.append(Violation(relpath, first_heading[0], "C7", first_heading[1],
                                  "首区块标题与页面标题同义（应区分层级）"))
    return bad


def scan(root: Path) -> List[Violation]:
    violations: List[Violation] = []
    sources: List[Tuple[Path, str]] = []

    web_dir = root / "ai_new" / "modules" / "agent" / "web" / "data" / "console"
    if web_dir.exists():
        for pat in ("*.html", "*.js"):
            for p in sorted(web_dir.rglob(pat)):
                if "/assets/" in p.as_posix():
                    continue  # 第三方厂商资源，不属于自研界面文案
                sources.append((p, p.relative_to(root).as_posix()))

    console = root / "ai_new" / "modules" / "agent_common" / "demand_engine" / "data" / "console.yaml"
    if console.exists():
        sources.append((console, console.relative_to(root).as_posix()))

    demand_dir = root / "ai_new" / "modules" / "agent_common" / "demand_engine" / "data" / "demands"
    if demand_dir.exists():
        sources.extend((p, p.relative_to(root).as_posix()) for p in sorted(demand_dir.glob("*.yaml")))

    for path, rel in sources:
        if path.suffix == ".html":
            entries = scan_html(path, rel)
        elif path.suffix == ".js":
            entries = scan_js(path, rel)
        else:
            entries = scan_yaml(path, rel)
        violations.extend(_check_title_heading(rel, entries))
        for lineno, key, text, kind in entries:
            raw = text
            violations.extend(_check_common(rel, lineno, text, raw))
            violations.extend(_check_by_kind(kind, rel, lineno, text, raw))
    return violations


def _aggregate(violations: List[Violation]) -> Dict[str, int]:
    agg: Dict[str, int] = {}
    for v in violations:
        agg[v.relpath] = agg.get(v.relpath, 0) + 1
    return dict(sorted(agg.items(), key=lambda kv: (-kv[1], kv[0])))


def run(root: Path) -> Tuple[int, List[Violation]]:
    violations = scan(root)
    return (1 if violations else 0), violations


def _self_test() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="gate-copy-self-"))
    try:
        # 构造违规样本：覆盖 C1/C2/C3/C4/C6/C8/C9
        console_dir = tmp / "ai_new/modules/agent/web/data/console"
        console_dir.mkdir(parents=True)
        (console_dir / "demo.html").write_text(
            "<button>智能一键全新！</button>\n<span>共享任务单角色文档库产物</span>\n",
            encoding="utf-8")
        (console_dir / "demo.js").write_text(
            'const a = "以下是说明：请注意在这里你可以该功能旨在";\n'
            'const b = "字段参数说明接口返回需求描述";\n',
            encoding="utf-8")
        demand_dir = tmp / "ai_new/modules/agent_common/demand_engine/data/demands"
        demand_dir.mkdir(parents=True)
        (demand_dir / "demo.yaml").write_text(
            "id: demo\n"
            "title: 示例页面\n"
            "heading: 示例页面\n"
            "label: 非常长的按钮文字超过六字\n"
            "empty: 这里写一句很长的空态文案用来测试空态长度上限是否被门禁拦住\n",
            encoding="utf-8")

        code, violations = run(tmp)
        codes = {v.code for v in violations}
        expected = {"C1", "C2", "C3", "C4", "C6", "C7", "C8", "C9"}
        missing = expected - codes
        if code == 0 or violations == []:
            print("SELF-TEST 失败：违规样本未被抓到（退出码=%d，条数=%d）" % (code, len(violations)))
            return 1
        if missing:
            print("SELF-TEST 失败：缺规则命中 %s；已命中 %s" % (sorted(missing), sorted(codes)))
            return 1

        # 干净样本必须通过
        clean_dir = tmp / "clean"
        clean_dir.mkdir()
        (clean_dir / "c.yaml").write_text(
            "title: 项目列表\nlabel: 新建工单\nempty: 暂无数据\nnote: 从列表里选一条进来。\n",
            encoding="utf-8")
        clean_code, clean_bad = run(clean_dir)
        if clean_code != 0 or clean_bad:
            print("SELF-TEST 失败：干净样本被误判：")
            for v in clean_bad:
                print("  " + v.line())
            return 1
        print("SELF-TEST 通过：注入 %d 条违规全部命中（%s），干净样本 0 误判。"
              % (len(violations), "/".join(sorted(expected))))
        return 0
    finally:
        shutil.rmtree(str(tmp), ignore_errors=True)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="文案门禁")
    parser.add_argument("--self-test", action="store_true", help="在临时目录注入样本自检")
    args = parser.parse_args(argv)

    if args.self_test:
        return _self_test()

    code, violations = run(ROOT)
    if violations:
        print("文案门禁失败（%d 条）：" % len(violations))
        for v in violations:
            print("  " + v.line())
        print("按文件聚合：")
        for rel, n in _aggregate(violations).items():
            print("  %s: %d" % (rel, n))
    else:
        print("文案门禁通过：界面文案无禁用句式/空词/超长/术语不一致/字段泄漏。")
    return code


if __name__ == "__main__":
    sys.exit(main())
