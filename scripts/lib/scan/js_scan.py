"""前端 JS 结构化扫描：函数/常量定义、标识符引用、window 挂载、HTML 绑定。

第三方 assets（cytoscape/dagre/js-yaml 等）不纳入扫描范围。
"""
from __future__ import annotations

import re
from pathlib import Path

JS_FUNC_RE = re.compile(r"(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(")
JS_CONST_RE = re.compile(
    r"(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:function|\()")
JS_IDENT_RE = re.compile(r"[A-Za-z_$][\w$]*")
JS_WINDOW_RE = re.compile(r"window\.([A-Za-z_$][\w$]*)")

JS_GLOBALS = {
    "window", "document", "console", "Math", "JSON", "Promise", "Object", "Array",
    "String", "Number", "Boolean", "Map", "Set", "Date", "Error", "RegExp", "Symbol",
    "Reflect", "Proxy", "localStorage", "sessionStorage", "location", "navigator",
    "AudioContext", "webkitAudioContext", "jsyaml", "requestAnimationFrame", "setTimeout",
    "setInterval", "clearTimeout", "clearInterval", "confirm", "alert", "fetch", "URL",
    "URLSearchParams", "Blob", "FileReader", "Event", "CustomEvent", "HTMLElement",
    "Node", "getComputedStyle", "parseInt", "parseFloat", "isNaN", "encodeURIComponent",
    "decodeURIComponent", "btoa", "atob", "structuredClone", "queueMicrotask",
}

CONSOLE_DIR_REL = Path("ai_new/modules/agent/web/data/console")


def parse_js(path: Path, src: str) -> dict:
    defs, seen = [], set()
    for rx in (JS_FUNC_RE, JS_CONST_RE):
        for m in rx.finditer(src):
            name = m.group(1)
            if name in seen:
                continue
            seen.add(name)
            line = src[:m.start()].count("\n") + 1
            defs.append({"name": name, "lineno": line, "kind": "js-function"})
    refs = {t for t in JS_IDENT_RE.findall(src) if t not in JS_GLOBALS}
    mounted = set(JS_WINDOW_RE.findall(src))
    return {"path": str(path), "defs": defs, "refs": refs, "mounted": mounted}


def collect_js_files(root: Path) -> list[Path]:
    console = root / CONSOLE_DIR_REL
    if not console.is_dir():
        return []
    return sorted(p for p in console.glob("*.js") if "assets" not in p.parts)


def analyze(root: Path, sources: dict[str, str] | None = None,
            html: str | None = None) -> dict:
    files: dict[str, dict] = {}
    if sources:
        for rel, src in sources.items():
            files[rel] = parse_js(Path(rel), src)
    else:
        for p in collect_js_files(root):
            files[str(p.relative_to(root))] = parse_js(p, p.read_text(encoding="utf-8"))

    if html is None:
        html_path = root / CONSOLE_DIR_REL / "manage.html"
        html = html_path.read_text(encoding="utf-8") if html_path.is_file() else ""
    html_tokens = set(JS_IDENT_RE.findall(html))

    global_refs: set[str] = set()
    mounted: set[str] = set()
    for info in files.values():
        global_refs |= info["refs"]
        mounted |= info["mounted"]

    return {"files": files, "global_refs": global_refs, "mounted": mounted,
            "html_tokens": html_tokens}
