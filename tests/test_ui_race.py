#!/usr/bin/env python3
"""前端竞态回归测试：createTicket 必须先刷新分组再打开会话。

用法：python3 tests/test_ui_race.py

为什么用源码静态断言而不是 DOM 测试：
  本项目前端是零依赖的原生 JS（hive/modules/projects/ui.js 直接挂到 window 上），
  tests/ 里没有 jsdom / puppeteer 之类的 DOM 运行时依赖，起浏览器成本高且 CI 不稳。
  而这次要防的回归是「顺序」问题：只要源码里 chat:open 的 emit 不在 loadGroups 的
  then 回调里，就说明竞态回来了。所以读源码做结构断言足够，且不依赖缩进/换行。
"""
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UI = os.path.join(REPO, "hive", "modules", "projects", "ui.js")


def _read():
    with open(UI, encoding="utf-8") as f:
        return f.read()


def _strip_comments(src):
    """去掉 // 行注释与 /* */ 块注释，避免注释里的字样干扰断言。"""
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    out = []
    for line in src.splitlines():
        # 只处理行首/空白后的整行注释，避免误伤字符串里的 "//"
        if line.lstrip().startswith("//"):
            continue
        out.append(line)
    return "\n".join(out)


def _extract_function(src, name):
    """按大括号配对截出 function name(...) { ... } 的函数体（含签名）。"""
    m = re.search(r"function\s+" + re.escape(name) + r"\s*\([^)]*\)\s*\{", src)
    if not m:
        return None
    i = m.end() - 1  # 指向 '{'
    depth = 0
    for j in range(i, len(src)):
        c = src[j]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return src[m.start():j + 1]
    return None


def _norm(s):
    """压缩空白，让断言不受缩进/换行影响。"""
    return re.sub(r"\s+", " ", s)


def run():
    """返回 (ok, errors)。供 tests/run_all.py 直接调用。"""
    errors = []
    src = _strip_comments(_read())

    body = _extract_function(src, "createTicket")
    if not body:
        return False, ["ui.js 里找不到 createTicket 函数"]
    flat = _norm(body)

    # 1) chat:open 必须出现在 loadGroups(...).then( 之后
    # 允许 loadGroups() 后面挂任意 .catch(...) 兜底，再 .then(
    m_load = re.search(r"loadGroups\s*\(\s*\)\s*(?:\.\s*catch\s*\(.*?\)\s*)?\.\s*then\s*\(", flat)
    m_chat = re.search(r"chat:open", flat)
    if not m_load:
        errors.append("createTicket 里没有 loadGroups().then(...) 链")
    elif not m_chat:
        errors.append("createTicket 里找不到 chat:open 的 emit")
    elif m_chat.start() < m_load.start():
        errors.append("chat:open 出现在 loadGroups().then 之前（竞态回归）")

    # 2) chat:open 必须落在 then 回调体内（而不是 then 之后又跑到外面）
    if m_load and m_chat and m_chat.start() > m_load.start():
        # 从 then( 开始做括号配对，确认 chat:open 在回调函数体内部
        start = flat.index("(", m_load.start() + flat[m_load.start():].index("then"))
        depth = 0
        end = None
        for k in range(start, len(flat)):
            if flat[k] == "(":
                depth += 1
            elif flat[k] == ")":
                depth -= 1
                if depth == 0:
                    end = k
                    break
        if end is None or not (start < m_chat.start() < end):
            errors.append("chat:open 不在 loadGroups().then 的回调体内")

    # 3) queued 分支仍然走 openProject，不打开 chat
    if not re.search(r"status\s*!==\s*'queued'", flat):
        errors.append("createTicket 丢失了 status !== 'queued' 判断")
    if not re.search(r"else\s+openProject\s*\(\s*state\.project\s*,\s*true\s*\)", flat):
        errors.append("queued 分支没有走 openProject(state.project, true)")

    # 4) loadGroups 必须返回 promise（return api(...) 或 return Promise）
    lg = _extract_function(src, "loadGroups")
    if not lg:
        errors.append("ui.js 里找不到 loadGroups 函数")
    else:
        lg_flat = _norm(lg)
        if not re.search(r"return\s+(api\s*\(|Promise\b|new\s+Promise\b)", lg_flat):
            errors.append("loadGroups 没有返回 promise（return api(...) / return Promise）")

    return (not errors), errors


def main():
    ok, errors = run()
    if ok:
        print("PASS createTicket 先刷新分组再打开会话（无竞态）")
        return 0
    for e in errors:
        print("FAIL " + e)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
