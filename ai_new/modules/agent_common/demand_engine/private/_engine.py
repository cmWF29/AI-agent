"""需求引擎实现：把 data/demands/*.json 读成"可执行的需求"，在 hook 触发时跑它们。

引擎不知道任何业务名词。它只会三件事：
    1. 装载需求（一个文件 = 一个需求 = 一段可插拔的业务）
    2. 按 `on` 找到该跑哪些需求
    3. 用 _lang 跑它们的语句树（顺序、守卫、循环、变量都是数据）

需求是运行时的东西，但它的**语法是结构的**：所有服务调用都在语句树的 `call` 字段里，
静态扫描能读全，所以"业务"既跑得起来，又不必靠运行时日志才能看懂。
"""
from __future__ import annotations

import copy
import re

from . import _lang


WRITE_LIKE = {"projects-archive", "projects-rename", "projects-delete", "projects-create",
              "ticket-create", "ticket-close", "ticket-message", "ticket-note",
              "project-position-toggle", "project-tool-toggle", "project-skill-toggle",
              "project-override-toggle"}

# 需求文件的解析缓存：键是（数据根, 文件名, 大小, 修改时刻）。
# 只缓存"解析结果"，不缓存装载结果：改一条需求仍按指纹整体重装，但另外几百条
# 不再重新 parse —— 否则逐条启停/逐条真投的用例会退化成 O(n²)（173 条 × 173 次）。
_PARSE_CACHE = {}


def _store_base(md):
    """数据根的可比较标识：真实模块用 root，测试桩用 _real('demands')。"""
    try:
        return str(md.root)
    except AttributeError:
        pass
    try:
        return str(md._real("demands"))
    except Exception:
        return ""


def _slug(label):
    s = re.sub(r"[\s+\uff0b]", "", str(label or ""))
    return re.sub(r"[^0-9A-Za-z_\-\u4e00-\u9fff]", "_", s) or "x"


def _canon(value):
    """稳定文本：键按字典序、值递归，保证同一事实两次算出的摘要相同。"""
    if isinstance(value, dict):
        return "{" + ",".join("%s:%s" % (k, _canon(value[k])) for k in sorted(value)) + "}"
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(_canon(v) for v in value) + "]"
    if isinstance(value, str):
        return '"%s"' % value
    return repr(value)


IDEM_MODULE = "agent_common/demand_engine"
IDEM_BUCKET = "hooks"
IDEM_LEASE = 120


class Engine:
    def __init__(self, ctx):
        self.ctx = ctx
        self._cache = None
        self._sig = None
        self._badge_seq = 0
        self._badge_items = []

    # ---- 装载 ----
    def _load(self):
        # 需求是磁盘上的数据，改了就该生效：按文件名+大小+修改时刻判要不要重新装载。
        # 这样改一条需求（含视图菜单、标签）不用重启服务，页面刷新即是新样子。
        sig = self._signature()
        if self._cache is None or (sig is not None and self._sig != sig):
            self._cache = self._read_all()
            self._sig = sig
        return self._cache

    def _signature(self):
        """需求目录的指纹（文件名+大小+修改时刻）；无存储上下文时回 None，退化成不比对。"""
        try:
            md = _md(self.ctx)
        except AttributeError:
            return None
        sig = []
        for name in md.list_dir("demands"):
            if not name.endswith(".yaml"):
                continue
            rel = "demands/%s" % name
            sig.append((name, md.stat_size(rel), md.stat_mtime(rel)))
        return tuple(sig)

    def _read_all(self):
        """按文件名+大小+修改时刻做单文件解析缓存：只重解被改过的那一条。

        热加载的指纹是整目录的；但改一条需求（启停、菜单、标签）不该把另外几百条
        重新 parse 一遍——那会让"逐条启停"的用例与线上热加载都退化成 O(n²)。
        """
        md = _md(self.ctx)
        names = md.list_dir("demands")
        base = _store_base(md)
        items = []
        for name in names:
            if not name.endswith(".yaml"):
                continue
            rel = "demands/%s" % name
            key = (base, name, md.stat_size(rel), md.stat_mtime(rel))
            hit = _PARSE_CACHE.get(key)
            if hit is None:
                hit = md.yaml_read(rel, {}) or {}
                if len(_PARSE_CACHE) > 2000:
                    _PARSE_CACHE.clear()
                _PARSE_CACHE[key] = hit
            rec = copy.deepcopy(hit)
            rec.setdefault("id", name[:-5])
            rec.setdefault("enabled", True)
            rec["on"] = _as_hooks(rec.get("on"))
            rec.setdefault("do", [])
            items.append(rec)
        return sorted(items, key=lambda r: r["id"])

    def reload(self):
        self._cache = None
        self._sig = None

    # ---- 可见性 ----

    # ---- 失效通知：写操作改的是哪条数据源，由需求自己声明 touch ----
    def _views_using(self, demand_ids):
        """反查：哪些视图把某条数据源当 as 用；返回 [{view, as}]。"""
        hits = []
        for rec in self._load():
            view = rec.get("view") or {}
            key = view.get("key")
            if not key:
                continue
            for src in view.get("data") or []:
                if str(src.get("demand")) in demand_ids and src.get("as"):
                    hits.append({"view": key, "as": str(src.get("as"))})
        return hits

    def notify_write(self, demand_id, rec):
        """写需求跑完：声明了 touch 就按数据源推失效，没声明就不发（不噪）。"""
        touch = {str(x) for x in (rec.get("touch") or [])}
        if not touch:
            return
        hits = self._views_using(touch)
        if not hits:
            return
        # 同一条需求连带触发的重复通知（多步写、同数据源）合并掉，避免前端连刷好几轮
        now = float(self.ctx.clock.now()["ts"])
        last = self._badge_items[-1] if self._badge_items else None
        if (last and last.get("demand") == demand_id and last.get("items") == hits
                and now - float(last.get("at") or 0) < 1.5):
            last["at"] = now
            return
        self._badge_seq += 1
        self._badge_items = (self._badge_items + [{"seq": self._badge_seq, "demand": demand_id,
                                                   "items": hits, "at": now}])[-30:]
        self._publish_badges()

    def _publish_badges(self):
        rt = getattr(self.ctx, "runtime", None)
        if rt is None:
            return
        payload = {"seq": self._badge_seq, "items": self._badge_items}
        try:
            # 必须是单行：SSE 层会把这段再包成 YAML 标量，多行会撕成非法文档
            text = self.ctx.codec.json_encode(payload)["text"]
        except Exception:  # noqa: BLE001 — 编码失败不该拖垮写操作本身
            return
        try:
            rt.stream_clear("console.invalidate")
            rt.stream_put("console.invalidate", text)
        except Exception:  # noqa: BLE001
            return

    def items(self):
        return [
            {"id": r["id"], "title": r.get("title", ""),
             "enabled": bool(r.get("enabled", True)),
             "tags": list(r.get("tags") or []),
             "view": r.get("view") or None,
             "on": list(r["on"]),
             "do": _lang.routes_of(r.get("do"))}
            for r in self._load()
        ]

    def manifest(self):
        """全量需求的可视化形状：每条需求的执行链 + 树节点（成形归模块，渲染只认节点）。

        节点约定：`{label,badge,sub}` 表示分支节点，`{name,path}` 表示叶子。
        需求 DSL 只有顺序 call/send，所以树是两层：需求 → 步骤。
        """
        items, nodes, buckets = [], [], {}
        steps_total = views = callable_n = 0
        for r in self._load():
            steps = r.get("do") or []
            leaves = []
            for i, st in enumerate(steps if isinstance(steps, list) else []):
                if not isinstance(st, dict):
                    leaves.append({"name": str(st)[:120], "path": "非结构语句"})
                    continue
                name = st.get("call") or st.get("send") or "?"
                as_ = str(st.get("as") or "")
                with_ = st.get("with")
                keys = ",".join(sorted(with_)) if isinstance(with_, dict) else ""
                sub = ("as " + as_ if as_ else "")
                if keys:
                    sub = (sub + " · with " + keys).strip()
                leaves.append({"name": "%d. %s" % (i + 1, name), "path": sub})
            routes = _lang.routes_of(steps)
            view = r.get("view") if isinstance(r.get("view"), dict) else None
            view_key = (view or {}).get("key") or ""
            callable_ = bool(r.get("callable"))
            steps_total += len(leaves)
            views += 1 if view_key else 0
            callable_n += 1 if callable_ else 0
            exp = r.get("expect") or {}
            expect_calls = [str(x) for x in (exp.get("calls") or [])]
            # 需求自己声明的预期调用 vs 编译出来的实际调用：不一致就是"需求变形"
            drift = sorted(set(routes) ^ set(expect_calls))
            items.append({"id": r["id"], "title": r.get("title", ""),
                          "enabled": bool(r.get("enabled", True)),
                          "tags": list(r.get("tags") or []),
                          "touch": list(r.get("touch") or []),
                          "on": list(r.get("on") or []),
                          "view": view_key or "", "callable": callable_,
                          "steps": len(leaves), "routes": routes,
                          "expect_calls": expect_calls, "drift": drift,
                          "promise": exp.get("promise") or "",
                          "payload": exp.get("payload") or {}})
            touch = list(r.get("touch") or [])
            node = {"label": r["id"],
                    "badge": ("可调" if callable_ else ("视图" if view_key else "内置")),
                    "sub": (r.get("title", "") + ("　写后失效：" + ", ".join(touch) if touch else "")),
                    "children": leaves}
            nodes.append(node)
            first_tag = (r.get("tags") or ["core"])[0]
            buckets.setdefault(first_tag, []).append(node)
        named = {t.get("id"): (t.get("name") or t.get("id"))
                 for t in ((_md(self.ctx).yaml_read("tags.yaml", {}) or {}).get("tags") or [])}
        groups = [{"label": named.get(k, k), "badge": "%d" % len(v), "sub": k,
                   "children": v}
                  for k, v in sorted(buckets.items(), key=lambda kv: (-len(kv[1]), kv[0]))]
        return {"count": len(items), "steps": steps_total, "views": views,
                "callable": callable_n, "items": items, "nodes": nodes, "groups": groups}

    def console(self):
        """控制台外壳：品牌、词表、配色 + 导航菜单一次下发。

        菜单不单独存一份：它是视图的属性，视图在自己规格里写 `menu`，
        这里按 order 汇总。所以"加一个视图"就是"多一个导航项"，前端零改动。
        """
        shell = _md(self.ctx).yaml_read("console.yaml", {}) or {}
        menus = []
        for r in self._load():
            view = r.get("view") if isinstance(r.get("view"), dict) else {}
            menu = view.get("menu") if isinstance(view.get("menu"), dict) else None
            if not menu:
                continue
            key = str(menu.get("key") or view.get("nav") or view.get("key") or "")
            if not key:
                continue
            label = str(menu.get("label") or view.get("heading") or key)
            grp = menu.get("group") if isinstance(menu.get("group"), dict) else {}
            tab = menu.get("tab") if isinstance(menu.get("tab"), dict) else {}
            menus.append({
                "key": key,
                "label": label,
                # 侧栏按概念分组：组名与组序由视图自己声明，前端不存分组表
                "group": str(grp.get("name") or ""),
                "group_order": float(grp.get("order") or 99),
                # 手机底栏位置小，视图可另给短名；没给就用全名
                "short": str(menu.get("short") or label),
                "order": float(menu.get("order") or 100),
                "mobile": bool(menu.get("mobile", True)),
                # 底栏序号：只参与底栏的视图声明 tab.order；0 = 不进底栏
                "tab_order": float(tab.get("order") or 0),
                # 二级菜单：parent 指向父级视图的 key；没有就是一级
                "parent": str(menu.get("parent") or ""),
                "demand": r["id"],
            })
        menus.sort(key=lambda m: (m["group_order"], m["order"], m["key"]))
        shell["menus"] = menus
        return shell

    def screens(self):
        """界面状态图：节点=界面状态（页面/浮层），边=具体控件点下去到哪个状态。

        页面之间的边从视图规格自动推导（act.view 跳页、act.modal 开弹窗、parent 返回），
        壳层（侧栏开合）在 console.yaml 的 screen_machine 里显式声明。
        推导在前端零改动、后端零手维护：加一个按钮跳页，图里就多一条边。
        """
        shell = _md(self.ctx).yaml_read("console.yaml", {}) or {}
        sm = shell.get("screen_machine") or {}
        states, edges, overlays, controls = {}, [], [], []

        def _view_label(v, key):
            """界面上这一页叫什么：菜单名 → 去掉占位符的标题 → 静态面包屑 → key。
            详情页标题是 {project.name} 这类占位符，直接当节点名用户读不懂。"""
            lab0 = str(v.get("screen_label") or "").strip()
            if lab0:
                return lab0
            menu = v.get("menu") or {}
            if isinstance(menu, str):
                menu = {"label": menu}
            lab = str(menu.get("label") or "").strip()
            if lab:
                return lab
            head = re.sub(r"\{[^}]*\}", "", str(v.get("heading") or v.get("heading_from") or "")).strip(" ·，")
            if head:
                return head
            crumb = [str(c) for c in (v.get("crumb") or []) if "{" not in str(c)]
            if crumb:
                return " · ".join(crumb)
            return key

        def node(key, label):
            # 先被引用、后来才轮到的页面先落成 key 占位；轮到它时用真名覆盖，别让用户看到 view:xxx
            if key not in states:
                states[key] = {"id": key, "cn": label or key, "next": []}
            elif label:
                states[key]["cn"] = label
            return states[key]

        def edge(frm, to, ctl, label):
            if frm == to:
                return
            # 边只补节点、不改名：名字由视图自己声明（菜单名 / screen_label）
            node(frm, "")
            node(to, "")
            states[frm]["next"].append({"to": to, "when": label or ""})
            edges.append({"from": frm, "to": to, "ctl": ctl, "label": label or ""})

        views = []
        mains = {}
        for rec in self._load():
            v = rec.get("view") or {}
            if v.get("key"):
                views.append((v.get("key"), v, rec))
                # 每页"就一件事"：视图自己声明的副标题，页面地图上直接给用户看
                mains["view:%s" % v.get("key")] = str(v.get("subheading") or "")
        forms = set()
        for key, v, rec in views:
            label = _view_label(v, key)
            node("view:%s" % key, label)
            par = v.get("parent") or {}
            parent = par if isinstance(par, str) else par.get("view")
            if parent:
                edge("view:%s" % key, "view:%s" % parent, "ctl.crumb_up", "面包屑返回")
            for kind, blob in [("head_act", (v.get("actions") or [])),
                               ("card_act", []), ("row_act", [])]:
                pass
            acts = list(v.get("actions") or [])
            for sec in v.get("sections") or []:
                acts += list(sec.get("actions") or [])
                sub = sec.get("submit")
                if sub:
                    acts.append(dict(sub, label=sub.get("label")))
                if sec.get("on_click"):
                    acts.append(dict(sec["on_click"], label=sec.get("click_label") or "打开卡片"))
            for act in acts:
                target, ctl_kind = None, "card_act"
                # 每个按钮都登记进控件清单：不换状态的按钮（归档/删除/启停）也要有去向说明
                effect = "本页刷新"
                if act.get("view"):
                    effect = "跳到 %s" % (act["view"] if isinstance(act["view"], str)
                                        else (act["view"].get("key") or act["view"].get("view")))
                elif act.get("modal"):
                    effect = "打开弹窗 %s" % act["modal"]
                elif act.get("demand") in WRITE_LIKE:
                    effect = "本页刷新"
                elif act.get("demand") or act.get("confirm") or act.get("flash"):
                    effect = "本页刷新"
                else:
                    effect = "只改本页显示"
                label_inv = act.get("label") or act.get("text") or ""
                if label_inv:
                    controls.append({"view": "view:%s" % key, "view_cn": label,
                                     "label": label_inv,
                                     "ctl": act.get("ctl") or "ctl.%s.%s" % (ctl_kind, _slug(label_inv)),
                                     "effect": effect})
                if act.get("view"):
                    tv = act["view"]
                    target = "view:%s" % (tv if isinstance(tv, str) else (tv.get("key") or tv.get("view")))
                    ctl_kind = "card_open" if act.get("label") is None else "head_act"
                elif act.get("modal"):
                    target = "overlay:form:%s" % act["modal"]
                    forms.add(str(act["modal"]))
                    ctl_kind = "card_act"
                if target:
                    label_ = act.get("label") or act.get("text") or "打开"
                    edge("view:%s" % key, target, "ctl.%s.%s" % (ctl_kind, _slug(label_)), label_)
        for form in sorted(forms):
            node("overlay:form:%s" % form, "弹窗·%s" % form)
        # 侧栏：任何页面都能点开；导航项点完落到目标页并收起
        node("overlay:sidebar", (sm.get("overlays") or [{}])[0].get("label") or "侧栏")
        for key, v, rec in views:
            edge("view:%s" % key, "overlay:sidebar", "ctl.shell.menu", "点三条杠展开侧栏")
            menu = v.get("menu") or {}
            if isinstance(menu, str):
                menu = {"label": menu}
            if menu:
                edge("overlay:sidebar", "view:%s" % key,
                     "ctl.nav.%s" % _slug(menu.get("label") or key), "导航：%s（收起侧栏）" % (menu.get("label") or key))
        for ov in (sm.get("overlays") or []):
            if ov.get("key") in states:
                overlays.append({"id": ov.get("key"), "label": ov.get("label"), "close": ov.get("close_ctl"), "note": ov.get("close_note")})
        # 用户视角的页面地图：一页从哪进、点哪里走、这一页只讲一件事。
        # 页面之间的边里排除"侧栏进来"的那几条（侧栏是外壳，不算一次业务跳转）
        entry_key = sm.get("entry") or "view:projects"
        meta = {}
        for key, v, rec in views:
            menu = v.get("menu") or {}
            if isinstance(menu, str):
                menu = {"label": menu}
            grp = menu.get("group") if isinstance(menu.get("group"), dict) else {}
            meta["view:%s" % key] = (bool(menu), float(grp.get("order") or 99),
                                     float(menu.get("order") or 100), str(key))
        pages = []
        for st in states.values():
            if not str(st["id"]).startswith("view:"):
                continue
            ins = [e for e in edges if e["to"] == st["id"] and not str(e["from"]).startswith("overlay:sidebar")]
            outs = [e for e in edges if e["from"] == st["id"] and str(e["to"]).startswith("view:")]
            pages.append({
                "key": st["id"], "label": st["cn"],
                # 副标题里带 {占位符} 的（"建 {project.created}"）不摊到页面地图上，留给详情页自己渲染
                "main": "" if "{" in mains.get(st["id"], "") else mains.get(st["id"], ""),
                "entry": st["id"] == entry_key,
                "from": [{"label": states.get(e["from"], {}).get("cn", e["from"]), "by": e["label"]} for e in ins],
                "to": [{"label": states.get(e["to"], {}).get("cn", e["to"]), "by": e["label"]} for e in outs],
            })
        pages.sort(key=lambda p: (p["key"] != entry_key, not meta.get(p["key"], (False,))[0],
                                  meta.get(p["key"], (False, 99, 100, p["key"]))[1:]))
        # 页面→页面 的跳转清单（浮层单独列，用户读的是"点了哪个、到了哪"）
        seen = set()
        routes = []
        for e in edges:
            # 页面→页面/弹窗才算一次用户跳转；侧栏进来、退回侧栏是外壳动作，不占页面地图
            if not (str(e["from"]).startswith("view:") and str(e["to"]).startswith(("view:", "overlay:form:"))):
                continue
            sig = (e["from"], e["to"], e["label"])
            if sig in seen:
                continue
            seen.add(sig)
            routes.append({"from": states.get(e["from"], {}).get("cn", e["from"]),
                            "from_key": e["from"], "by": e["label"],
                            "to": states.get(e["to"], {}).get("cn", e["to"]), "to_key": e["to"]})
        return {
            "entry": entry_key,
            "pages": pages,
            "routes": routes,
            "states": list(states.values()),
            "edges": edges,
            "overlays": overlays,
            "controls": controls,
            "stats": {"states": len(states), "edges": len(edges), "overlays": len(overlays),
                      "controls": len(controls), "pages": len(pages), "routes": len(routes)},
            "close_controls": [{"ctl": o.get("close_ctl"), "note": o.get("close_note")} for o in (sm.get("overlays") or [])],
        }

    def inventory(self):
        """可点实例清单（由 scripts/ui_inventory.py 生成）：每条都带控件 id、状态机与点后去向。"""
        return _md(self.ctx).yaml_read("ui-inventory.json", {}) or {}

    def chrome(self):
        """登录页要的那点字：品牌 + 登录文案。

        未登录可读，所以只回这一小块——导航、岗位、字段、状态这些结构信息一概不给。
        """
        shell = _md(self.ctx).yaml_read("console.yaml", {}) or {}
        return {"brand": shell.get("brand") or {}, "login": shell.get("login") or {}}

    # ---- 插拔 ----
    def set_enabled(self, demand_id, enabled):
        for rec in self._load():
            if rec["id"] != demand_id:
                continue
            rec["enabled"] = bool(enabled)
            _md(self.ctx).yaml_write("demands/%s.yaml" % demand_id, rec)
            self.reload()
            return {"id": demand_id, "enabled": bool(enabled)}
        raise self.ctx.ApiError("需求不存在: %s" % demand_id, code="no_demand", status=404)

    # ---- 运行 ----
    # ---- 链路 span：一次需求执行/一次派发 = 一棵子树 ----
    def _span(self, name, attrs=None):
        try:
            return self.ctx.api.call("trace.open", {
                "name": name, "caller": "demand_engine", "attrs": attrs or {}},
                caller="demand_engine")
        except Exception:
            return {}

    def _span_close(self, span, status="ok", code=""):
        sid = (span or {}).get("span") or ""
        if not sid:
            return
        try:
            self.ctx.api.call("trace.close", {
                "span": sid, "status": status, "code": code}, caller="demand_engine")
        except Exception:
            pass

    def run_callable(self, demand_id, inputs=None):
        sp = self._span("demand:" + str(demand_id))
        status, code = "ok", ""
        try:
            return self._run_callable(demand_id, inputs)
        except Exception as exc:
            status = "error"
            code = getattr(exc, "code", "") or type(exc).__name__
            raise
        finally:
            self._span_close(sp, status, code)

    async def arun_callable(self, demand_id, inputs=None):
        sp = self._span("demand:" + str(demand_id))
        status, code = "ok", ""
        try:
            return await self._arun_callable(demand_id, inputs)
        except Exception as exc:
            status = "error"
            code = getattr(exc, "code", "") or type(exc).__name__
            raise
        finally:
            self._span_close(sp, status, code)

    def dispatch(self, hook, envelope):
        sp = self._span("dispatch:" + str(hook), {"on": str(hook)})
        status, code = "ok", ""
        try:
            return self._dispatch(hook, envelope)
        except Exception as exc:
            status = "error"
            code = getattr(exc, "code", "") or type(exc).__name__
            raise
        finally:
            self._span_close(sp, status, code)

    async def adispatch(self, hook, envelope):
        sp = self._span("dispatch:" + str(hook), {"on": str(hook)})
        status, code = "ok", ""
        try:
            return await self._adispatch(hook, envelope)
        except Exception as exc:
            status = "error"
            code = getattr(exc, "code", "") or type(exc).__name__
            raise
        finally:
            self._span_close(sp, status, code)

    def _run_callable(self, demand_id, inputs=None):
        """按名跑一段"编排需求"（不挂在点上），返回最后一次调用的结果。"""
        for rec in self._load():
            if rec["id"] != demand_id:
                continue
            if not rec.get("enabled", True):
                return {"ok": False, "error": "需求已下线", "code": "disabled", "demand": demand_id}
            if not rec.get("callable"):
                raise self.ctx.ApiError("需求不按名调用: %s" % demand_id,
                                        code="not_callable", status=400)
            scope = {"input": inputs or {}, "caller": None}
            results = _lang.run(rec.get("do"), scope, self.ctx.api, self.ctx, demand_id)
            last = next((r for r in reversed(results) if r.get("call")), None)
            if last is None:
                return {"ok": False, "error": "没有任何调用", "code": "empty", "demand": demand_id}
            out = last.get("result")
            # 能力结果可以是任意形状（清单类返回列表），只有 dict 才看 ok 字段。
            ok = (bool(out.get("ok", True)) if isinstance(out, dict) else True) \
                and all(r.get("ok") for r in results)
            res = {"ok": ok, "demand": demand_id, "result": out,
                   "calls": [r.get("call") for r in results]}
            # 失败步不吞：最后一步往往只是"无事可做"的空结果，真正被拒的原因在中间某一步，
            # 不外显的话调用方只看到 ok:false 而拿不到 code/文案。
            bad = next((r for r in results if not r.get("ok")), None)
            if bad is not None:
                res["failed"] = {"call": bad.get("call"),
                                 "result": bad.get("result"),
                                 "error": bad.get("error") or "",
                                 "code": bad.get("code") or ""}
            if "write" in (rec.get("tags") or []):
                self.notify_write(demand_id, rec)   # 改完就通知，前端只换受影响的那一块
            return res
        raise self.ctx.ApiError("需求不存在: %s" % demand_id, code="no_demand", status=404)


    # ---- 派发幂等：一条事件 + 一条需求 = 一个键 ----
    def _event_digest(self, hook, envelope):
        raw = _canon({"hook": hook, "event": envelope or {}})
        try:
            got = self.ctx.api.call("codec.digest", {"text": raw}, caller="demand_engine")
        except Exception:
            got = {}
        return str(got.get("hex") or _canon(raw)[:40])[:40]

    def _claim(self, hook, demand_id, digest):
        """拿执行权。台账不可用时宁可执行一次，也不丢活（fail-open 但留证据）。"""
        try:
            return self.ctx.api.call("store.claim", {
                "module": IDEM_MODULE, "bucket": IDEM_BUCKET,
                "key": "%s|%s|%s" % (hook, demand_id, digest),
                "route": demand_id, "scope": hook,
                "lease_seconds": IDEM_LEASE}, caller="demand_engine")
        except Exception:
            return {"claimed": True, "status": "claimed", "degraded": True}

    def _settle(self, hook, demand_id, digest, ok, code=""):
        try:
            self.ctx.api.call("store.settle", {
                "module": IDEM_MODULE, "bucket": IDEM_BUCKET,
                "key": "%s|%s|%s" % (hook, demand_id, digest),
                "status": "done" if ok else "failed",
                "result_digest": demand_id if ok else "",
                "error_code": "" if ok else (code or "failed")}, caller="demand_engine")
        except Exception:
            pass

    def _dispatch(self, hook, envelope):
        results = []
        digest = self._event_digest(hook, envelope)
        for rec in self._load():
            if not rec.get("enabled", True) or hook not in rec["on"]:
                continue
            claim = self._claim(hook, rec["id"], digest)
            if not claim.get("claimed"):
                results.append({"demand": rec["id"], "ok": True, "call": None,
                                "skipped": claim.get("status") or "in_flight",
                                "reused": bool(claim.get("reused"))})
                continue
            scope = {"event": envelope or {}, "hook": hook, "caller": None}
            rows = _lang.run(rec.get("do"), scope, self.ctx.api, self.ctx, rec["id"])
            results.extend(rows)
            bad = next((r for r in rows if not r.get("ok")), None)
            self._settle(hook, rec["id"], digest, bad is None,
                         code=(bad or {}).get("code") or (bad or {}).get("error") or "")
        return results

    async def _arun_callable(self, demand_id, inputs=None):
        """异步轨：按名跑一段编排需求（不挂在点上），返回最后一次调用的结果。"""
        for rec in self._load():
            if rec["id"] != demand_id:
                continue
            if not rec.get("enabled", True):
                return {"ok": False, "error": "需求已下线", "code": "disabled", "demand": demand_id}
            if not rec.get("callable"):
                raise self.ctx.ApiError("需求不按名调用: %s" % demand_id,
                                        code="not_callable", status=400)
            scope = {"input": inputs or {}, "caller": None}
            results = await _lang.arun(rec.get("do"), scope, self.ctx.api, self.ctx, demand_id)
            last = next((r for r in reversed(results) if r.get("call")), None)
            if last is None:
                return {"ok": False, "error": "没有任何调用", "code": "empty", "demand": demand_id}
            out = last.get("result")
            ok = (bool(out.get("ok", True)) if isinstance(out, dict) else True) \
                and all(r.get("ok") for r in results)
            res = {"ok": ok, "demand": demand_id, "result": out,
                   "calls": [r.get("call") for r in results]}
            bad = next((r for r in results if not r.get("ok")), None)
            if bad is not None:
                res["failed"] = {"call": bad.get("call"),
                                 "result": bad.get("result"),
                                 "error": bad.get("error") or "",
                                 "code": bad.get("code") or ""}
            if "write" in (rec.get("tags") or []):
                # 通知看"写需求有没有跑过"，不看内部异步子任务收口（上游拉起是异步的，
                # 等它成功就永远不发；多发一次最多多重取一块，漏发就是脏页面）
                self.notify_write(demand_id, rec)
            return res
        raise self.ctx.ApiError("需求不存在: %s" % demand_id, code="no_demand", status=404)

    async def _adispatch(self, hook, envelope):
        results = []
        digest = self._event_digest(hook, envelope)
        for rec in self._load():
            if not rec.get("enabled", True) or hook not in rec["on"]:
                continue
            claim = await self.ctx.api.acall("store.claim", {
                "module": IDEM_MODULE, "bucket": IDEM_BUCKET,
                "key": "%s|%s|%s" % (hook, rec["id"], digest),
                "route": rec["id"], "scope": hook,
                "lease_seconds": IDEM_LEASE}, caller="demand_engine")
            if not claim.get("claimed"):
                results.append({"demand": rec["id"], "ok": True, "call": None,
                                "skipped": claim.get("status") or "in_flight",
                                "reused": bool(claim.get("reused"))})
                continue
            scope = {"event": envelope or {}, "hook": hook, "caller": None}
            rows = await _lang.arun(rec.get("do"), scope, self.ctx.api, self.ctx, rec["id"])
            results.extend(rows)
            bad = next((r for r in rows if not r.get("ok")), None)
            try:
                await self.ctx.api.acall("store.settle", {
                    "module": IDEM_MODULE, "bucket": IDEM_BUCKET,
                    "key": "%s|%s|%s" % (hook, rec["id"], digest),
                    "status": "done" if bad is None else "failed",
                    "result_digest": rec["id"] if bad is None else "",
                    "error_code": "" if bad is None else ((bad or {}).get("code") or "failed")},
                    caller="demand_engine")
            except Exception:
                pass
        return results


def _as_hooks(value):
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(v) for v in value]
    return []



def _md(ctx):
    """本模块自己的数据目录：数据跟着模块走，不是全系统一个筐。"""
    return ctx.storage.own(__file__)
