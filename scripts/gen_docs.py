#!/usr/bin/env python3
"""源码文档幂等生成器：每个源码文件一份 `docs/code/<镜像路径>.md`，拆到函数/类级别。

口径：
  - 每次全仓扫描现算，不读缓存、不维护人工清单；
  - 机读头登记：源码路径、内容哈希、符号清单、更新时间、生成方式；门禁靠头扫；
  - 文档按文件拆细、单篇从简，不复制源码全文；
  - 幂等：哈希不变时保留原更新时间，重复跑不产生 diff、不重排符号。

用法：
  python3 scripts/gen_docs.py            # 生成/刷新 docs/code
  python3 scripts/gen_docs.py --check     # 只比对不写盘，有漂移非零退出（CI 用）
  python3 scripts/gen_docs.py <路径前缀>  # 限定生成范围
"""
from __future__ import annotations

import hashlib
import sys
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from scan import js_scan, python_scan  # noqa: E402

DOCS_ROOT = ROOT / "docs" / "code"
GENERATOR = "gen_docs.py v1"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _py_symbols(src: str) -> list[dict]:
    try:
        info = python_scan.parse_python(Path("<src>"), src)
    except SyntaxError:
        return []
    return info["defs"]


def _js_symbols(src: str) -> list[dict]:
    return js_scan.parse_js(Path("<src>"), src)["defs"]


def _yaml_keys(rec: dict) -> list[str]:
    return [str(k) for k in (rec.keys() if isinstance(rec, dict) else [])]


def _safe_yaml(src: str) -> tuple[dict, str | None]:
    """解析 yaml；失败返回 ({}, 错误信息)，不让门禁崩溃在并发改动的文件上。"""
    try:
        return yaml.safe_load(src) or {}, None
    except yaml.YAMLError as e:
        return {}, str(e)


def _collect_sources(root: Path, scope: str | None) -> list[tuple[str, str, str]]:
    """返回 [(rel, kind, src)]。kind: py / js / yaml。"""
    out: list[tuple[str, str, str]] = []

    def keep(rel: str) -> bool:
        return not scope or rel.startswith(scope)

    for p in python_scan.collect_python_files(root):
        rel = str(p.relative_to(root))
        if keep(rel):
            out.append((rel, "py", p.read_text(encoding="utf-8")))
    for p in js_scan.collect_js_files(root):
        rel = str(p.relative_to(root))
        if keep(rel):
            out.append((rel, "js", p.read_text(encoding="utf-8")))

    import os
    modules = root / "ai_new" / "modules"
    # 运行期快照/落盘子目录（幂等台账、归档快照、产物、语音样本）不纳入文档源；
    # 模块 data 下的静态配置（api/messages/roles/seed/flows/tools 等）仍纳入。
    RUNTIME_DIRS = {"idem", "exports", "public", "files", "dirs", "prompts",
                    "sessions", "trace", "tickets", "projects", "channels",
                    "_archive_orphans"}
    if modules.is_dir():
        for dirpath, dirnames, filenames in os.walk(modules):
            here = Path(dirpath).relative_to(modules).parts
            # 只在模块自己的 data 目录下裁运行期子目录；模块目录本身叫 tickets/trace/sessions
            # 也照常扫描（否则会把整个模块的契约文档当孤儿）。
            if here and here[-1] == "data":
                dirnames[:] = [d for d in dirnames if d not in RUNTIME_DIRS]
            if "data" not in here:
                continue
            for fn in filenames:
                if fn.endswith((".yaml", ".yml")):
                    p = Path(dirpath) / fn
                    rel = str(p.relative_to(root))
                    if keep(rel):
                        out.append((rel, "yaml", p.read_text(encoding="utf-8")))

    scripts = root / "scripts"
    if scripts.is_dir():
        for p in sorted(scripts.glob("*.py")):
            rel = str(p.relative_to(root))
            if keep(rel):
                out.append((rel, "py", p.read_text(encoding="utf-8")))
    return sorted(out)


def _summary(docstring: str | None) -> str:
    if not docstring:
        return "（无 docstring）"
    return docstring.strip().splitlines()[0].strip()


def render_doc(rel: str, kind: str, src: str, prev: dict | None) -> str:
    """生成单篇文档。prev 为已有文档头（用于保留更新时间）。"""
    digest = _sha256(src.encode("utf-8"))
    updated = (prev or {}).get("updated_at") or _now_iso()

    if kind == "py":
        symbols = _py_symbols(src)
    elif kind == "js":
        symbols = _js_symbols(src)
    else:
        rec, _err = _safe_yaml(src)
        symbols = [{"name": k, "kind": "key", "docstring": None} for k in _yaml_keys(rec)]

    header = {
        "source": rel,
        "hash": digest,
        "symbols": [s["name"] for s in symbols],
        "generated": GENERATOR,
        "updated_at": updated,
    }
    head = yaml.safe_dump(header, allow_unicode=True, sort_keys=False).strip()

    lines = [
        "---", head, "---", "",
        "# " + Path(rel).name, "",
        "> 由 `scripts/gen_docs.py` 生成；手改会被下次生成覆盖。",
        "> 职责/入参出参/副作用/依赖/不变量/关联需求由人工在下方补充；生成器只提取 docstring 与符号。",
        "",
        "## 概览", "",
    ]
    if kind == "py":
        try:
            import ast
            tree = ast.parse(src)
            doc = ast.get_docstring(tree)
        except SyntaxError:
            doc = None
        lines += [_summary(doc), ""]
    elif kind == "yaml":
        lines += ["YAML 配置：按键/段登记摘要。", ""]
    else:
        lines += ["前端 JS 模块：按函数/常量登记摘要。", ""]

    lines.append("## 符号")
    for s in symbols:
        lines += [
            "",
            "### `%s`（%s）" % (s["name"], s["kind"]),
            "- 职责: %s" % _summary(s.get("docstring")),
            "- 入参/出参: 待人工补充",
            "- 副作用/依赖/不变量: 待人工补充",
            "- 关联需求/测试: 待人工补充",
        ]
    lines.append("")
    return "\n".join(lines)


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())


def _doc_path(root: Path, rel: str) -> Path:
    return root / "docs" / "code" / (rel + ".md")


def parse_doc(text: str) -> dict | None:
    """解析文档机读头；无头或坏头返回 None。"""
    if not text.startswith("---"):
        return None
    parts = text.split("---", 2)
    try:
        return yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError:
        return None


def generate(root: Path | None = None, write: bool = True,
             scope: str | None = None) -> dict:
    """全量生成/比对。返回 {drift, missing, stale_hash, stale_symbols, orphans, stats}。"""
    root = root or ROOT
    sources = _collect_sources(root, scope)

    missing, stale_hash, stale_symbols, orphans = [], [], [], []
    parse_errors: list[tuple[str, str]] = []
    docs_seen: set[str] = set()

    for rel, kind, src in sources:
        path = _doc_path(root, rel)
        docs_seen.add(str(path))
        prev = parse_doc(path.read_text(encoding="utf-8")) if path.is_file() else None
        digest = _sha256(src.encode("utf-8"))

        if prev is None:
            missing.append(rel)
        else:
            if prev.get("hash") != digest:
                stale_hash.append(rel)
            if kind == "yaml":
                rec, err = _safe_yaml(src)
                if err:
                    parse_errors.append((rel, err))
                cur_syms = [{"name": k} for k in _yaml_keys(rec)]
            else:
                cur_syms = _py_symbols(src) if kind == "py" else _js_symbols(src)
            prev_syms = list(prev.get("symbols") or [])
            if set(s["name"] for s in cur_syms) != set(prev_syms):
                stale_symbols.append(rel)

        if write:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(render_doc(rel, kind, src, prev), encoding="utf-8")

    # 孤儿文档：源码已删/改名，文档残留
    docs_root = root / "docs" / "code"
    if docs_root.is_dir():
        for path in docs_root.rglob("*.md"):
            if str(path) not in docs_seen:
                orphans.append(str(path.relative_to(docs_root))[:-3])

    stats = {"sources": len(sources), "missing": len(missing),
             "stale_hash": len(stale_hash), "stale_symbols": len(stale_symbols),
             "orphans": len(orphans), "parse_errors": len(parse_errors)}
    return {"missing": missing, "stale_hash": stale_hash, "stale_symbols": stale_symbols,
            "orphans": orphans, "parse_errors": parse_errors, "stats": stats}


def main(argv: list[str] | None = None) -> int:
    argv = list(argv or sys.argv[1:])
    check = "--check" in argv
    scope = next((a for a in argv if not a.startswith("--")), None)

    result = generate(write=not check, scope=scope)
    s = result["stats"]
    print("代码文档同步：源码 %d，缺文档 %d，哈希过期 %d，符号过期 %d，孤儿文档 %d"
          % (s["sources"], s["missing"], s["stale_hash"], s["stale_symbols"], s["orphans"]))

    bad = result["missing"] + result["stale_hash"] + result["stale_symbols"] + result["orphans"]
    if bad:
        print("\n代码-文档同步未通过：")
        for rel in result["missing"]:
            print("  - 缺文档: %s" % rel)
        for rel in result["stale_hash"]:
            print("  - 哈希过期（源码改动未同步文档）: %s" % rel)
        for rel in result["stale_symbols"]:
            print("  - 符号清单过期（新增/改名/删除函数未同步）: %s" % rel)
        for rel in result["orphans"]:
            print("  - 孤儿文档（源码已删/改名）: %s" % rel)
        return 1
    print("代码-文档同步通过：文档与源码哈希、符号清单一致")
    return 0


if __name__ == "__main__":
    sys.exit(main())
