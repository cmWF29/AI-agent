#!/usr/bin/env python3
"""视图层静态门禁（三条规则，任一不满足即失败）：

1. 条件引擎自检 + 视图条件语法
   - 用真身 spec.js 的 condOf 跑一组真值断言，防止"运算符写法变了但没人发现"
     （历史上 `row.disabled == true` 因空格解析失败，导致禁用态永远不显示）
   - 扫所有 view-*.yaml 的 disabled_when / when / hide_when / show_when：
     能拆成 || / && 子句，每子句必须是 {路径} 或 path op value
2. 只读覆盖：项目/工单上下文里的写操作，必须有禁用条件
   - view-project-detail：写操作按钮的 disabled_when 必须含 project.archived
   - view-ticket-thread：写操作必须含 thread.locked（结单或归档）
   - 其余视图：写操作必须有 disabled_when，不许裸奔
3. 工具卡单一出口：render.js 只允许一个 toolCardHtml，卡片默认折叠（点开才看细节）
"""
import glob
import json
import os
import re
import subprocess
import sys

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONSOLE = ROOT + "/ai_new/modules/agent/web/data/console"
DEMANDS = ROOT + "/ai_new/modules/agent_common/demand_engine/data/demands"

# 写操作需求：打 write 标签的需求。新增写需求必须打标，否则门禁看不见它。
WRITE_TAG = "write"

COND_KEYS = ("disabled_when", "when", "hide_when", "show_when")
# 合法子句：{路径} / 裸路径（row.archived 这类，引擎按真值取）/ path op value
PATH = re.compile(r"^(?:route|row|data|cache|fields|field|result|thread|project)(?:\.\w+)+$")
CLAUSE = re.compile(r"^\s*(?:(?P<brace>\{(?P<patha>.+)\})|(?P<field>\S+)\s*(?P<op>!=|==|>=|<=|=|>|<)\s*(?P<val>\S+)|(?P<bare>\S+))\s*$")

NODE_PROBES = r"""
const fs = require('fs');
const vm = require('vm');
const src = fs.readFileSync(process.env.SPEC_JS, 'utf8');
const box = { console };
vm.createContext(box);
vm.runInContext(src, box);
const cases = [
  ['row.disabled == true', {row:{disabled:true}}, true],
  ['row.disabled == true', {row:{disabled:false}}, false],
  ['row.disabled != true', {row:{disabled:true}}, false],
  ['row.disabled == true || {project.archived}', {row:{disabled:true}}, true],
  ['row.disabled == true || {project.archived}', {row:{disabled:false}, data:{project:{archived:true}}}, true],
  ['row.disabled == true || {project.archived}', {row:{disabled:false}, data:{project:{archived:false}}}, false],
  ['{project.archived}', {data:{project:{archived:true}}}, true],
  ['{project.archived}', {data:{project:{archived:false}}}, false],
  ['a == 1 && b == 2', {data:{a:1,b:2}}, true],
  ['a == 1 && b == 2', {data:{a:1,b:3}}, false],
];
const bad = [];
for (const [expr, ctx, want] of cases) {
  let got;
  try { got = box.condOf(expr, ctx); } catch (e) { bad.push(expr + ' 抛错: ' + e.message); continue; }
  if (got !== want) bad.push(expr + ' => ' + got + '，应为 ' + want);
}
process.stdout.write(JSON.stringify(bad));
"""


def node_cond_selftest():
    path = CONSOLE + "/spec.js"
    try:
        env = dict(os.environ, SPEC_JS=path)
        out = subprocess.run(["node", "-e", NODE_PROBES], capture_output=True, text=True, timeout=60, env=env)
    except FileNotFoundError:
        return ["没有 node，条件引擎自检跑不了"]
    if out.returncode != 0:
        return ["node 执行失败：" + (out.stderr or out.stdout).strip()[:160]]
    try:
        return json.loads(out.stdout or "[]")
    except ValueError:
        return ["node 输出不可解析：" + (out.stdout or "")[:120]]


def strings_of(node, key):
    """递归收集指定键上的字符串条件（含 list 里的 mapping）。"""
    out = []
    if isinstance(node, dict):
        for k, v in node.items():
            if k in COND_KEYS and isinstance(v, str) and v.strip():
                out.append((k, v.strip()))
            elif k in COND_KEYS and isinstance(v, bool):
                pass
            else:
                out.extend(strings_of(v, key))
    elif isinstance(node, list):
        for it in node:
            out.extend(strings_of(it, key))
    return out


def clause_problems():
    bad = []
    for f in sorted(glob.glob(DEMANDS + "/view-*.yaml")):
        spec = yaml.safe_load(open(f, encoding="utf-8")) or {}
        for key, expr in strings_of(spec, key=None):
            for orpart in expr.split("||"):
                for clause in orpart.split("&&"):
                    if not clause.strip():
                        bad.append(f"{os.path.basename(f)} {key}: 空子句 `{expr}`")
                        continue
                    m = CLAUSE.match(clause)
                    if not m:
                        bad.append(f"{os.path.basename(f)} {key}: 子句 `{clause.strip()}` 不是 {{路径}} 或 path op value")
                    elif m.group("bare") and not PATH.match(m.group("bare")):
                        bad.append(f"{os.path.basename(f)} {key}: 裸子句 `{m.group('bare')}` 不像数据路径（拼错的条件会恒为空）")
    return bad


def write_demands():
    ids = set()
    for f in glob.glob(DEMANDS + "/*.yaml"):
        spec = yaml.safe_load(open(f, encoding="utf-8")) or {}
        tags = spec.get("tags") or []
        if WRITE_TAG in tags:
            ids.add(spec.get("id") or os.path.basename(f)[:-5])
    return ids


def acts_of(node, inherited=None):
    """展开视图里所有动作节点（mapping 里带 demand 的）。
    disabled_when 是容器级声明时可继承（composer 的四个控件共用一个判据）。"""
    out = []
    if isinstance(node, dict):
        inh = node.get("disabled_when") if isinstance(node.get("disabled_when"), str) else inherited
        if isinstance(node.get("demand"), str):
            out.append((node, inh))
        for v in node.values():
            out.extend(acts_of(v, inh))
    elif isinstance(node, list):
        for it in node:
            out.extend(acts_of(it, inherited))
    return out


# 项目/工单内容页：写操作必须带归档/只读判据
COVER_RULES = {
    "view-project-detail.yaml": "project.archived",
    "view-projects-list.yaml": "project.archived",
    "view-ticket-thread.yaml": "thread.locked",
}
# 真删（purge）刻意不受归档守卫约束：归档是只读封存，不是防删除
EXEMPT_DEMANDS = {"projects-delete"}
# 弹窗提交由打开它的按钮守卫（按钮灰了点不到）；系统级页面没有项目上下文
EXEMPT_VIEWS = {"view-forms.yaml", "view-ops.yaml", "view-skills.yaml", "view-tools.yaml"}


def readonly_problems():
    writes = write_demands()
    bad = []
    for f in sorted(glob.glob(DEMANDS + "/view-*.yaml")):
        name = os.path.basename(f)
        if name in EXEMPT_VIEWS:
            continue
        spec = yaml.safe_load(open(f, encoding="utf-8")) or {}
        need = COVER_RULES.get(name)
        for act, inherited in acts_of(spec):
            is_write = act.get("demand") in writes and act.get("demand") not in EXEMPT_DEMANDS
            # 弹窗动作（改名/建单/结单）自己不带 demand，写操作在表单里；按钮同样必须有归档判据
            is_modal = bool(act.get("modal")) and bool(need)
            if not (is_write or is_modal):
                continue
            label = act.get("label") or act.get("text") or act.get("demand")
            cond = str(act.get("disabled_when") or inherited or "")
            if not cond:
                bad.append(f"{name}: 写操作「{label}」没有 disabled_when（{act.get('demand')}）")
            elif need and need not in cond:
                bad.append(f"{name}: 写操作「{label}」的禁用条件缺 `{need}`：{cond}")
    return bad


def tool_card_problems():
    src = open(CONSOLE + "/render.js", encoding="utf-8").read()
    bad = []
    defs = re.findall(r"function\s+(toolCardHtml|toolBodyHtml|toolCallCard)\s*\(", src)
    others = [d for d in defs if d != "toolCardHtml"]
    if defs.count("toolCardHtml") != 1:
        bad.append(f"toolCardHtml 定义次数 = {defs.count('toolCardHtml')}，必须恰好 1 个出口")
    # 允许薄适配器（toolCallCard/toolBodyHtml），但它们只能转调 toolCardHtml，不许自己拼结构
    for fn in sorted(set(others)):
        body = re.search(r"function " + fn + r"\(.*?\n\}", src, re.S)
        text = body.group(0) if body else ""
        if "toolCardHtml(" not in text:
            bad.append(f"{fn} 自己拼工具卡，没有转调 toolCardHtml（会出现第二种样式）")
        elif "tool-call" in text:
            bad.append(f"{fn} 里直接写了 tool-call 结构，样式会分叉")
    body = re.search(r"function toolCardHtml\(.*?\n\}", src, re.S)
    if not body:
        bad.append("找不到 toolCardHtml 函数体")
    else:
        text = body.group(0)
        for token, why in (("foldAttr", "折叠键没有持久化"), ("<details", "卡片不是默认折叠（点开才看细节）"),
                           ("tool-call-head", "头行结构丢了")):
            if token not in text:
                bad.append(f"toolCardHtml 缺 {token}：{why}")
    return bad


def problems():
    out = []
    out += [f"条件引擎自检: {p}" for p in node_cond_selftest()]
    out += clause_problems()
    out += readonly_problems()
    out += tool_card_problems()
    return out


def main():
    bad = problems()
    if bad:
        print("视图层门禁失败：")
        for p in bad:
            print("  - " + p)
        return 1
    print("视图层门禁通过：条件引擎自检 + 条件语法 + 只读覆盖 + 工具卡单一折叠出口")
    return 0


if __name__ == "__main__":
    sys.exit(main())
