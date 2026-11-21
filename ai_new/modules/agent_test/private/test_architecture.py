"""模块结构契约（评审者视角的静态检查）。

规则从**目录**读出来，不维护第二份名单，也不靠文件名前缀：

    ai_new/modules/<组>/<模块>/__init__.py
    ai_new/modules/<组>/<模块>/private/...   ← 私有由目录表达

组（agent_common / agent / agent_test）只是装配单位，不是三级特权：
同一个扫描器、同一套规则，`data/profiles.json` 决定哪个入口装哪些组。
"""
import ast
import yaml
import re
import unittest
from pathlib import Path

from _fixtures import module_dir  # noqa: E402

ROOT = Path(__file__).resolve().parents[4]
MODULES = ROOT / "ai_new" / "modules"
BUSINESS_WORDS = ["工单", "秘书", "角色", "PM"]
RUNTIME_GROUPS = ("agent_common", "agent")
_CN = re.compile(r"[\u4e00-\u9fff]")

# 私有层允许保留的中文诊断/身份（文件相对 modules/，函数名）。
# 这些类比标准库异常：门面错误码、本地引擎安装诊断、后端身份枚举，不属于面向用户的业务文案；
# 面向模型的职责正文、面向用户的标签/规则句仍须外置到 messages.yaml / seed.yaml。
COPY_WHITELIST = {
    # web 门面：静态资源越界 / 缺失的 HTTP 错误诊断
    ("agent/web/private/_panel.py", "asset"),
    # decompose：工具定义结构校验的内部诊断
    ("agent/decompose/private/_pure.py", "_norm_tool"),
    # asr：本地离线引擎/模型安装与音频解析诊断
    ("agent/asr/private/_engine.py", "_load_model"),
    ("agent/asr/private/_engine.py", "transcribe"),
}


def src_files(base):
    """模块源码文件：`data/` 是运行期产物目录（交付件里可能有 .py），不算源码。"""
    return sorted(p for p in base.rglob("*.py")
                  if "__pycache__" not in p.parts and "data" not in p.parts)


def runtime_modules():
    """运行时模块（评审对象）：[(组, 模块, 目录)]。"""
    out = []
    for group in RUNTIME_GROUPS:
        for entry in sorted((MODULES / group).iterdir()):
            if entry.is_dir() and not entry.name.startswith("_") and (entry / "__init__.py").is_file():
                out.append((group, entry.name, entry))
    return out


def all_modules():
    """全部模块（含评审者自己）。"""
    out = []
    for group in sorted(p.name for p in MODULES.iterdir()
                        if p.is_dir() and not p.name.startswith("_")):
        for entry in sorted((MODULES / group).iterdir()):
            if entry.is_dir() and (entry / "__init__.py").is_file():
                out.append((group, entry.name, entry))
    return out


def platform_modules():
    """平台模块 = 在 setup 里装填了 ctx 面的模块（从装配图读，不维护名单）。"""
    from ai_new.modules.agent_common.boot.private._graph import plan
    dirs = [MODULES / group for group in RUNTIME_GROUPS]
    return set(plan(dirs)["providers"].values())


def _module_of(path):
    """文件属于哪个模块：ai_new/modules/<组>/<模块>/... -> (组, 模块)。"""
    try:
        parts = path.relative_to(MODULES).parts
    except ValueError:
        return None
    if len(parts) < 2:
        return None
    return parts[0], parts[1]


def _package_of(path):
    """文件所在包名（用于 import 解析）。"""
    parts = list(path.relative_to(ROOT / "ai_new").with_suffix("").parts)[:-1]
    return "ai_new" + ("." + ".".join(parts) if parts else "")


def _resolve(package, level, module):
    if level == 0:
        return module or ""
    parts = package.split(".")
    keep = len(parts) - (level - 1)
    if keep < 1:
        return ""
    base = parts[:keep]
    if module:
        base.extend(module.split("."))
    return ".".join(base)


class StructureTest(unittest.TestCase):
    def test_groups_are_declared(self):
        """装配清单只引用存在的组 —— 换组等于换一套装配。"""
        profiles = yaml.safe_load((module_dir("agent_common", "boot") / "data" / "profiles.yaml")
                              .read_text(encoding="utf-8"))
        for name, groups in (profiles.get("profiles") or {}).items():
            for group in groups:
                self.assertTrue((MODULES / group).is_dir(),
                                "%s 引用了不存在的组: %s" % (name, group))

    def test_module_root_holds_only_init(self):
        """模块根目录只放 __init__.py —— 其他实现一律进 private/。"""
        for group, name, path in all_modules():
            extra = [p.name for p in path.glob("*.py") if p.name != "__init__.py"]
            self.assertEqual(extra, [], "%s/%s 根目录还有别的 .py: %s" % (group, name, extra))

    def test_private_impl_lives_in_private_dir(self):
        """私有实现只在 <module>/private/ 下；文件名不再承担"私有"这个语义。"""
        for group, name, path in all_modules():
            self.assertTrue((path / "private").is_dir(), "%s/%s 缺少 private/" % (group, name))
            strays = [str(p.relative_to(path)) for p in src_files(path)
                      if p.parent != path / "private" and p.name != "__init__.py"]
            self.assertEqual(strays, [], "%s/%s 有跑到 private/ 之外的文件: %s" % (group, name, strays))

    def test_no_cross_module_imports(self):
        """运行时模块之间不 import；agent_test 可以（评审者能看被评审对象，反之不行）。"""
        violations = []
        for path in src_files(ROOT / "ai_new"):
            owner = _module_of(path)
            if owner and owner[0] == "agent_test":
                continue
            own = _package_of(path)
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name.startswith("ai_new.modules"):
                            violations.append((str(path.relative_to(ROOT)), alias.name))
                elif isinstance(node, ast.ImportFrom):
                    target = _resolve(own, node.level, node.module)
                    if target.startswith("ai_new.modules") and not (
                            target == own or target.startswith(own + ".")):
                        violations.append((str(path.relative_to(ROOT)),
                                           "." * node.level + (node.module or ""), target))
        self.assertEqual(violations, [], "存在跨模块 import: %s" % violations)

    def test_abilities_declare_effects_instead_of_touching_disk(self):
        """能力不留副作用：写盘与驱动别的需求都是 effect，只能由需求经 runtime 执行。

        平台设施（store 落盘、runtime 执行、demand_engine 引擎本身）不受此限。
        """
        write_routes = {"store.write", "store.remove", "store.remove_dir",
                        "store.append_text", "store.archive", "store.write_text",
                        "store.write_bytes", "store.rename"}
        allowed_modules = {"store", "runtime", "demand_engine"}
        hits = []
        for group, name, path in all_modules():
            if group == "agent_test" or name in allowed_modules:
                continue
            for p in src_files(path):
                text = p.read_text(encoding="utf-8")
                for route in sorted(write_routes):
                    if '"%s"' % route in text:
                        hits.append((str(p.relative_to(ROOT)), route))
                if '"demand_engine.run"' in text:
                    hits.append((str(p.relative_to(ROOT)), "demand_engine.run"))
        self.assertEqual(hits, [], "能力自己伸手了（应改成效果，由需求执行）: %s" % hits)

    def test_modules_have_no_policy_powers(self):
        """运行时模块不许持有政策能力：没有 ctx.log、没有直接订阅。"""
        hits = []
        for group, name, path in runtime_modules():
            for p in src_files(path):
                text = p.read_text(encoding="utf-8")
                for marker in ("ctx.log", "ctx.bus"):
                    if marker in text:
                        hits.append((str(p.relative_to(ROOT)), marker))
        self.assertEqual(hits, [], "模块直接调用了日志/总线能力: %s" % hits)

    def test_modules_touch_no_stdlib_io_directly(self):
        """模块不自己碰文件/网络/进程：四个能力各管一段，其余模块只能调它们。

        能力归属（从职责定，不从文件名定）：
          store: 运行时文件系统（自己的 data）   net: 出站网络
          host:  主机资源读数                     http: 入站传输
        装配期例外：boot（组合根，装配前读 profiles/源码）、api（绑定生成）、
        config（任何模块之前就要知道配置）。
        """
        capabilities = {"store", "net", "host", "http", "exec"}
        bootstrap = {"boot", "api", "config"}
        banned = ("import pathlib", "from pathlib import", "import os", "import shutil",
                  "import zipfile", "import tempfile", "import glob", "from glob import",
                  "import urllib", "from urllib", "import socket", "import ssl",
                  "import http.client", "import subprocess", "import ctypes")
        hits = []
        for group, name, path in runtime_modules():
            if name in capabilities | bootstrap:
                continue
            for p in src_files(path):
                for line in p.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    for token in banned:
                        if line.startswith(token):
                            hits.append((str(p.relative_to(ROOT)), line[:46]))
                    if re.search(r"\bopen\(", line) and "def open" not in line:
                        hits.append((str(p.relative_to(ROOT)), line[:46]))
        self.assertEqual(hits, [], "模块直接用了标准库 I/O: %s" % hits)

    def test_modules_do_not_bring_their_own_clock_or_codec(self):
        """时间和编码也是能力：业务模块只能问 clock / codec。

        这条规则是"模块只做本角色的纯计算"的落地：一个模块自己 `import time` 就是
        自带一块表，自己 `import json` 就是自带一套格式；两个模块各带一份，早晚对不上。
        允许自带的一方是能力模块本身（clock/codec/store/host 的实现里必然要用），
        以及装配期的 boot/api/config/net/http。
        """
        owners = {"clock", "codec", "store", "host", "net", "http", "exec",
                  "boot", "api", "config", "trace"}
        banned = ("import time", "from time import", "import datetime",
                  "from datetime import", "import json", "from json import", "import yaml", "from yaml import",
                  "import base64", "import binascii", "import hashlib",
                  "import tempfile", "import uuid", "import random",
                  "import secrets")
        hits = []
        for group, name, path in runtime_modules():
            if name in owners:
                continue
            for src in src_files(path):
                for line in src.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    for token in banned:
                        if line.startswith(token):
                            hits.append((str(src.relative_to(ROOT)), line[:52]))
        self.assertEqual(hits, [], "模块自带时钟/编解码/摘要实现: %s" % hits)

    def test_llm_does_not_own_the_network(self):
        """llm 不持有网络/序列化/配置实现；这些经 api 通道委托 net/codec/config 路由。"""
        path = MODULES / "agent_common" / "llm"
        text = "\n".join(p.read_text(encoding="utf-8") for p in src_files(path))
        for token in ("import urllib", "urllib.request", "import socket", "http.client", "import yaml", "ctx.cfg"):
            self.assertNotIn(token, text, "模块 llm 越界了（它不是纯语义）: %s" % token)
        self.assertIn("llm.encode", text, "llm 没有提供载荷构造")

    def test_platform_modules_have_no_business_words(self):
        hits = []
        names = {name for _, name, _ in runtime_modules()}
        for name in platform_modules():
            path = next((p for _, n, p in runtime_modules() if n == name), None)
            if path is None or name not in names:
                continue
            for p in src_files(path):
                text = p.read_text(encoding="utf-8")
                for w in BUSINESS_WORDS:
                    if w in text:
                        hits.append((str(p.relative_to(ROOT)), w))
        self.assertEqual(hits, [], "平台模块出现业务词: %s" % hits)

    def test_no_prompt_text_in_code(self):
        hits = []
        for p in src_files(ROOT / "ai_new"):
            owner = _module_of(p)
            if owner and owner[0] == "agent_test":
                continue
            if "你是" in p.read_text(encoding="utf-8"):
                hits.append(str(p.relative_to(ROOT)))
        self.assertEqual(hits, [], "代码里出现提示词正文: %s" % hits)

    def test_private_layer_hides_no_business_copy(self):
        """业务私有层不内置面向用户/模型的中文文案；诊断与身份枚举走白名单。

        平台能力模块（agent_common）整体豁免：其报错类比标准库异常。
        工具 schema 的 ``desc`` 键值是接口元数据，随定义一起登记，不属业务文案。
        面向模型的职责正文、面向用户的标签/规则句须外置到 messages.yaml / seed.yaml。
        """
        hits = []
        for p in src_files(MODULES / "agent"):
            if "private" not in p.parts:
                continue
            tree = ast.parse(p.read_text(encoding="utf-8"), filename=str(p))
            rel = str(p.relative_to(MODULES)).replace("\\", "/")
            desc_values = {id(v) for d in ast.walk(tree) if isinstance(d, ast.Dict)
                           for k, v in zip(d.keys, d.values)
                           if isinstance(k, ast.Constant) and k.value == "desc"}
            for func in [n for n in ast.walk(tree)
                         if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
                body = func.body[1:] if (func.body and isinstance(func.body[0], ast.Expr)
                        and isinstance(func.body[0].value, ast.Constant)
                        and isinstance(func.body[0].value.value, str)) else func.body
                for fnode in body:
                    for node in ast.walk(fnode):
                        if not (isinstance(node, ast.Constant) and isinstance(node.value, str)
                                and _CN.search(node.value)):
                            continue
                        if id(node) in desc_values or (rel, func.name) in COPY_WHITELIST:
                            continue
                        hits.append((rel, func.name, node.lineno, node.value[:40]))
        self.assertEqual(hits, [], "私有层内置了未外置的业务文案: %s" % hits)

    def test_prompts_and_rules_are_data(self):
        """每样数据都在它主人自己的 data 里，没有一个公共筐。"""
        for group, name, rel in [
            ("agent", "library", "prompts/roles/developer.md"),
            ("agent", "sessions", "prompts/pm.md"),
            ("agent", "sessions", "prompts/secretary.md"),
            ("agent", "tickets", "messages.yaml"),
            ("agent", "sessions", "session-tools.yaml"),
            ("agent", "library", "seed.yaml"),
            # calls.json 已下架：能力只对需求开放，矩阵不再需要
            ("agent_common", "config", "config.default.yaml"),
            ("agent_common", "boot", "profiles.yaml"),
            ("agent_test", "agent_test", "checks.yaml"),
        ]:
            path = module_dir(group, name) / "data" / rel
            self.assertTrue(path.is_file(), "数据文件缺失: %s/%s/%s" % (group, name, rel))

    def test_boot_exposes_only_main(self):
        """组合根对外只能有 main；自己不定义公开函数，也不提供 ctx 面。"""
        init = MODULES / "agent_common" / "boot" / "__init__.py"
        tree = ast.parse(init.read_text(encoding="utf-8"), filename=str(init))
        public_defs = [n.name for n in tree.body
                       if isinstance(n, (ast.FunctionDef, ast.ClassDef))
                       and not n.name.startswith("_")]
        self.assertEqual(public_defs, [], "组合根对外暴露了额外符号: %s" % public_defs)
        exported = set()
        for node in tree.body:
            if isinstance(node, ast.ImportFrom) and node.module != "__future__":
                exported.update(alias.asname or alias.name for alias in node.names)
        self.assertEqual(exported, {"main"}, "组合根对外只应导出 main: %s" % exported)

    def test_no_call_matrix_file(self):
        """调用矩阵已下架：能力只对需求开放，接线关系只写在需求的 do 树里。

        消息结构的显性化换了个落点：每条路由收发什么字段写在模块自己的 data/api.yaml，
        由 api 模块装载并在 test_core 里做运行时双向校验。
        """
        legacy = module_dir("agent_common", "api") / "data" / "rules" / "calls.yaml"
        self.assertFalse(legacy.exists(), "calls.yaml 又出现了：接线关系只能写在需求 do 树里")

    def test_demand_payload_fields_are_declared_in_contracts(self):
        """需求里传的每个字段都必须在契约里声明：字段名只许出现在数据里，不许只在代码里。"""
        contracts = {}
        for path in sorted(MODULES.glob("*/*/data/api.yaml")):
            rec = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            for route, spec in (rec.get("routes") or {}).items():
                contracts[route] = spec or {}
        demands = (module_dir("agent_common", "demand_engine") / "data" / "demands")
        problems = []
        for path in sorted(demands.glob("*.yaml")):
            rec = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            for stmt in rec.get("do") or []:
                route = stmt.get("call") or stmt.get("send") if isinstance(stmt, dict) else None
                if not route:
                    continue
                payload = stmt.get("with") or {}
                if not isinstance(payload, dict):
                    continue
                spec = contracts.get(route)
                if spec is None:
                    problems.append("%s 调了没有契约的路由 %s" % (rec.get("id"), route))
                    continue
                declared = set((spec.get("in") or {}).keys())
                stray = sorted(set(payload.keys()) - declared)
                if stray:
                    problems.append("%s 给 %s 传了未声明字段 %s" % (rec.get("id"), route, stray))
        self.assertEqual(problems, [], "需求字段没在契约里声明: %s" % problems)

    def test_every_route_declares_contract_file(self):
        """每个模块的 data/api.yaml 必须是合法结构：module 名与目录一致，routes 是字典。"""
        bad = []
        for group, name, mdir in all_modules():
            path = mdir / "data" / "api.yaml"
            if not path.is_file():
                continue
            rec = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            if rec.get("module") != name:
                bad.append((str(path.relative_to(ROOT)), "module 名与目录不一致"))
            routes = rec.get("routes")
            if not isinstance(routes, dict) or not routes:
                bad.append((str(path.relative_to(ROOT)), "routes 为空或不是字典"))
            for route, spec in (routes or {}).items():
                if not isinstance(spec, dict):
                    bad.append((route, "契约不是字典"))
                for key in ("in", "out"):
                    if key in spec and not isinstance(spec[key], dict):
                        bad.append((route, "%s 不是字典" % key))
        self.assertEqual(bad, [], "契约文件结构不合法: %s" % bad)

    def test_demands_and_checks_are_bound_both_ways(self):
        """需求 ↔ 用例双向闭合：没用例的需求不许上线，没需求的用例也不许留着。"""
        demands = {p.stem for p in (module_dir("agent_common", "demand_engine")
                                    / "data" / "demands").glob("*.yaml")}
        checks = yaml.safe_load((module_dir("agent_test", "agent_test") / "data" / "checks.yaml")
                            .read_text(encoding="utf-8"))
        claimed = set()
        for check in checks.get("checks") or []:
            claimed.update(check.get("demands") or [])
        self.assertEqual(sorted(demands - claimed), [],
                         "这些需求没有绑定验收用例: %s" % sorted(demands - claimed))
        self.assertEqual(sorted(claimed - demands), [],
                         "这些用例点名的需求不存在: %s" % sorted(claimed - demands))

    def test_no_shared_data_bucket(self):
        """数据跟着模块走：不许出现公共数据根，也不许用旧的全局存储接口。"""
        banned = ("ctx.storage.data_dir(", "ctx.storage.data_path(", "ctx.storage.json_read(", "ctx.storage.yaml_read(",
                  "ctx.storage.json_write(", "ctx.storage.yaml_write(", "ctx.storage.read_data_text(",
                  "ctx.storage.list_data_dir(", 'paths.data', 'ctx.root / "data"')
        hits = []
        for path in src_files(ROOT / "ai_new"):
            owner = _module_of(path)
            if owner and owner[0] == "agent_test":
                continue  # 评审者读被评审对象的路径是允许的（单向）
            body = path.read_text(encoding="utf-8")
            for token in banned:
                if token in body:
                    hits.append((str(path.relative_to(ROOT)), token))
        self.assertEqual(hits, [], "存在跨模块共享的数据桶: %s" % hits)

    def test_root_holds_only_two_entrypoints(self):
        """根目录只有两个脚本和一个包：没有第三个特殊目录。"""
        entries = {p.name for p in ROOT.iterdir()}
        allowed = {"ai_new", "agent_start.py", "test_start.py",
                   "README.md", "ARCHITECTURE.md", "install_skill.md", "scripts",
                   # 审视与方案文档：文档在这个仓里是契约的一部分
                   "AUDIT-2026-11-21.md", "IDEMPOTENCY.md", "ROADMAP.md",
                   "agent_start.out.log", "agent_start.err.log",
                   # VCS 元数据；部署副本运行期产物（TLS 材料目录、运行日志）
                   ".git", ".gitignore", "certs", "run.log"}
        self.assertEqual(sorted(entries - allowed), [],
                         "根目录多出了东西: %s" % sorted(entries - allowed))
        self.assertTrue((ROOT / "agent_start.py").is_file())
        self.assertTrue((ROOT / "test_start.py").is_file())


class TestViewPaths(unittest.TestCase):
    """页面路径只有一套根：视图不许自带根词，层级必须和 parent 链一次不差。

    这一条是"前端页面到底有没有被管起来"的机械答案：
    面包屑 = 词表里唯一的根 + 视图声明的各级；谁想偷偷换根、跳级挂靠，直接红灯。
    """

    @staticmethod
    def _views():
        demands = module_dir("agent_common", "demand_engine") / "data" / "demands"
        out = {}
        for path in sorted(demands.glob("view-*.yaml")):
            rec = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            view = rec.get("view")
            if not isinstance(view, dict) or not view.get("key"):
                continue
            out[view["key"]] = (path.name, view)
        return out

    @staticmethod
    def _parent_key(view):
        parent = view.get("parent")
        if isinstance(parent, dict):
            return parent.get("view")
        if isinstance(parent, str):
            return None if parent.startswith("$") else parent
        return None

    def test_one_root_for_the_whole_console(self):
        console = yaml.safe_load((module_dir("agent_common", "demand_engine") / "data"
                                  / "console.yaml").read_text(encoding="utf-8")) or {}
        root = str((console.get("ui") or {}).get("crumb_root") or "")
        self.assertTrue(root, "词表没声明面包屑根 ui.crumb_root")
        for key, (name, view) in self._views().items():
            for part in view.get("crumb") or []:
                self.assertNotEqual(str(part), root,
                                    "%s 自己写了根词，路径会出现第二个根" % name)

    def test_breadcrumb_depth_matches_parent_chain(self):
        views = self._views()
        problems = []
        for key, (name, view) in views.items():
            crumb = [str(x) for x in (view.get("crumb") or [])]
            if not crumb:
                problems.append("%s 没有声明 crumb，页面顶上看不出自己在哪一级" % name)
                continue
            chain, seen = [], {key}
            at = key
            while True:
                parent = self._parent_key(views[at][1])
                if not parent:
                    break
                if parent in seen or parent not in views:
                    problems.append("%s 的 parent 链断了或成环: %s" % (name, parent))
                    break
                seen.add(parent)
                chain.insert(0, parent)
                at = parent
            top = views[chain[0]][1] if chain else view
            label = (top.get("menu") or {}).get("label")
            if not label:
                problems.append("%s 的层级终点不是导航页（%s 没 menu）" % (name, chain[0]))
                continue
            if crumb[0] != str(label):
                problems.append("%s 的第一级是 %r，不是它所在的导航页 %r"
                                % (name, crumb[0], str(label)))
            if len(crumb) != len(chain) + 1:
                problems.append("%s 写了 %d 级，parent 链只有 %d 级"
                                % (name, len(crumb), len(chain) + 1))
        self.assertEqual(problems, [], "页面路径不统一: %s" % problems)

    def test_nav_label_is_the_page_title(self):
        """导航名就是页面名：侧栏与标题不许两种叫法，否则面包屑第一级会跟着漂。"""
        bad = []
        for key, (name, view) in self._views().items():
            menu = view.get("menu") or {}
            if not menu:
                continue
            label = str(menu.get("label") or "")
            head = str(view.get("heading") or "")
            if head and label and label != head:
                bad.append("%s 导航叫 %r，标题叫 %r" % (name, label, head))
        self.assertEqual(bad, [], "导航名与页面标题不一致: %s" % bad)


class TestViewLayouts(unittest.TestCase):
    """区块排版也是契约：只允许写已知版式，且只能挂在该版式成立的区块类型上。"""

    LAYOUTS = {"deck": ("cards",)}   # 卡片堆叠只对卡片清单成立

    def test_section_layout_is_known(self):
        demands = module_dir("agent_common", "demand_engine") / "data" / "demands"
        bad = []
        for path in sorted(demands.glob("view-*.yaml")):
            rec = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            view = rec.get("view") or {}
            for sec in view.get("sections") or []:
                layout = sec.get("layout")
                if not layout:
                    continue
                kinds = self.LAYOUTS.get(str(layout))
                if kinds is None:
                    bad.append("%s 用了未登记的版式 %r" % (path.name, layout))
                elif sec.get("kind") not in kinds:
                    bad.append("%s 把版式 %r 挂到了 %r 区块上"
                               % (path.name, layout, sec.get("kind")))
        self.assertEqual(bad, [], "区块版式不合法: %s" % bad)


class TestInvalidationDeclarations(unittest.TestCase):
    """写后失效不是"代码自己猜"：touch 与区块 as 都是需求层的声明，这里守着它们不虚指向。"""

    def _demands(self):
        root = module_dir("agent_common", "demand_engine") / "data" / "demands"
        recs = {}
        for path in sorted(root.glob("*.yaml")):
            rec = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            recs[rec.get("id")] = rec
        return recs

    def test_touch_points_at_real_data_source(self):
        recs = self._demands()
        views = [r for r in recs.values() if (r.get("view") or {}).get("key")]
        used = {str(src.get("demand")) for v in views for src in (v["view"].get("data") or [])}
        bad = []
        for rid, rec in recs.items():
            for name in (rec.get("touch") or []):
                if name not in recs:
                    bad.append("%s 的 touch 指向不存在的需求 %r" % (rid, name))
                elif name not in used:
                    bad.append("%s 的 touch 指向没有任何视图取的数据 %r" % (rid, name))
                if not rec.get("callable"):
                    bad.append("%s 声明了 touch 却不可按名调用（失效通知永远等不到它跑）" % rid)
        self.assertEqual(bad, [], "失效声明不合法: %s" % bad)

    def test_view_params_have_no_transforms(self):
        """视图取数参数由引擎填：引擎只认 route/data 取值，不认 |when 这类渲染变换。"""
        bad = []
        for rid, rec in self._demands().items():
            for src in (rec.get("view") or {}).get("data") or []:
                for key, val in (src.get("params") or {}).items():
                    if isinstance(val, str) and "|" in val:
                        bad.append("%s 的取数参数 %s 写了变换 %r" % (rid, key, val))
        self.assertEqual(bad, [], "取数参数应只做取值: %s" % bad)

    def test_section_as_belongs_to_view_data(self):
        bad = []
        for rid, rec in self._demands().items():
            view = rec.get("view") or {}
            names = {str(src.get("as")) for src in (view.get("data") or [])}
            for sec in view.get("sections") or []:
                as_ = sec.get("as")
                if as_ and str(as_) not in names:
                    bad.append("%s 的区块声明了视图没取的数据 %r" % (rid, as_))
        self.assertEqual(bad, [], "区块数据源归属不合法: %s" % bad)


DEAD_DOC_CONCEPTS = (
    "data/rules/calls.yaml",
    "三种通道",
    "| `memory` |",
)


class TestDocsMatchImplementation(unittest.TestCase):
    """文档在这个仓里是契约，写错了就是契约失真：已下线的东西不许还留在文档里。"""

    def test_architecture_doc_has_no_dead_concepts(self):
        from pathlib import Path
        root = Path(__file__).resolve().parents[4]
        for name in ("ARCHITECTURE.md", "README.md"):
            text = (root / name).read_text(encoding="utf-8")
            for dead in DEAD_DOC_CONCEPTS:
                self.assertNotIn(dead, text, "%s 仍在描述已下线的东西：%s" % (name, dead))

    def test_readme_module_list_matches_tree(self):
        from pathlib import Path
        root = Path(__file__).resolve().parents[4]
        import re
        text = (root / "README.md").read_text(encoding="utf-8")
        lines = text.splitlines()
        head = [i for i, l in enumerate(lines) if l.startswith("**agent（业务能力）**")][0]
        chunk = []
        for l in lines[head:]:
            if not l.strip():
                break
            chunk.append(l)
        listed = set()
        for part in re.split("·", " ".join(chunk)):
            mod = re.sub(r"[^a-z0-9_]", "", part.split("：")[-1])
            if mod:
                listed.add(mod)
        actual = {p.name for p in (root / "ai_new" / "modules" / "agent").iterdir() if p.is_dir()}
        self.assertEqual(listed, actual)


if __name__ == "__main__":
    unittest.main(verbosity=2)
