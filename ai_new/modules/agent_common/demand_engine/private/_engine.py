"""需求引擎实现：把 data/demands/*.json 读成"可执行的需求"，在 hook 触发时跑它们。

引擎不知道任何业务名词。它只会三件事：
    1. 装载需求（一个文件 = 一个需求 = 一段可插拔的业务）
    2. 按 `on` 找到该跑哪些需求
    3. 用 _lang 跑它们的语句树（顺序、守卫、循环、变量都是数据）

需求是运行时的东西，但它的**语法是结构的**：所有服务调用都在语句树的 `call` 字段里，
静态扫描能读全，所以"业务"既跑得起来，又不必靠运行时日志才能看懂。
"""
from __future__ import annotations

from . import _lang


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
        names = _md(self.ctx).list_dir("demands")
        items = []
        for name in names:
            if not name.endswith(".yaml"):
                continue
            rec = _md(self.ctx).yaml_read("demands/%s" % name, {}) or {}
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
                "demand": r["id"],
            })
        menus.sort(key=lambda m: (m["group_order"], m["order"], m["key"]))
        shell["menus"] = menus
        return shell

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
