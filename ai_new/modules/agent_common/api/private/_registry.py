"""API 注册表实现。

- 路由名约定 "module.fn"；
- 跨模块调用只对需求开放（caller 为 None 或 "demand_engine"），模块自己不伸手；
- handler 统一签名 fn(ctx, payload)；
- **调用走哪条通道不在这里定**：交给 Transport（直连 / 内存 / 网络，绑定由编译生成）；
- **消息结构是数据**：每条路由的入参/出参契约写在模块自己的 `data/api.yaml`，
  本表只负责装载、校验、露出（`routes()` 带契约键清单）。
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import contextvars
import inspect
import threading

from . import _transport

# 调用方身份：handler 执行期间由注册表写入，供模块内部欠声明 caller 的调用自动补齐。
# 这样"模块直调他人能力"从"不传 caller 就放行"变成"身份可判定、必须登记"。
_SCOPE = contextvars.ContextVar("api_caller_scope", default="")

# 公共能力件：任何模块都可用（配置、时钟、编解码、存储、路由表、主机读数…）。
# 台账只管"业务模块之间"的直调，平台件不该让台账变成一锅粥。
PLATFORM_UTILS = frozenset((
    "config", "clock", "codec", "store", "api", "host", "net", "exec", "react",
    "llm", "runtime", "hooks", "demand_engine", "tools", "ops"))


class Registry:
    def __init__(self, ctx):
        self.ctx = ctx
        self._routes = {}
        self._contracts = None      # 懒加载，见 _load_contracts()
        self._contracts_seen = -1   # 缓存对应的已装模块数
        self._warned = []           # 契约告警（warn 模式不失败，只留证据）
        self._calls = None          # 跨模块直调台账（internal-calls.yaml）
        self._calls_seen = -1
        self._violations = []       # 未登记的直调证据（warn 模式收集）
        self.transport = _transport.Transport(ctx)
        self._loop = None
        self._loop_lock = threading.Lock()

    def _cfg_int(self, key, default):
        cfg = getattr(self.ctx, "cfg", None) or {}
        rt = cfg.get("runtime") or {}
        try:
            return int(rt.get(key) or default)
        except (TypeError, ValueError):
            return default

    def _cfg_str(self, section, key, default):
        cfg = getattr(self.ctx, "cfg", None) or {}
        sec = cfg.get(section) or {}
        value = sec.get(key)
        return str(value) if value not in (None, "") else default

    def _ensure_loop(self):
        """进程级事件循环：惰性建在专属守护线程上，供同步壳桥接异步路由。

        桥接同步路由的执行器用有界池，容量由 config.runtime.api_workers 显性声明；
        避免默认池线程被并发建单占满、嵌套协程回投 loop 时无人跑同步子能力形成循环等待。
        """
        if self._loop is None:
            with self._loop_lock:
                if self._loop is None:
                    loop = asyncio.new_event_loop()
                    workers = self._cfg_int("api_workers", 32)
                    loop.set_default_executor(concurrent.futures.ThreadPoolExecutor(
                        max_workers=workers, thread_name_prefix="api"))
                    t = threading.Thread(target=loop.run_forever, daemon=True,
                                         name="api-loop")
                    t.start()
                    self._loop = loop
        return self._loop

    def _adapt(self, fn):
        """传输层统一以 handler(ctx, payload) 调用；单参新签名在这里包成两参。"""
        import inspect
        params = [p for p in inspect.signature(fn).parameters.values()
                  if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD, p.VAR_POSITIONAL)]
        required = [p for p in params if p.default is inspect.Parameter.empty]
        if len(required) >= 2:
            return fn
        return lambda ctx, payload: fn(payload)

    def register(self, name, fn, doc="", module=None, stream=False, internal=False):
        """注册路由。

        stream=True 表示"返回 {items, cursor}"，可以被 http 当 SSE 长流读。
        internal=True 表示只给进程内调用，HTTP 通道一律不放行（起进程这类能力不能远程可调）。
        """
        if name in self._routes:
            raise ValueError("route already registered: " + name)
        if name == "trace.open":
            self._trace_open = self._adapt(fn)
        elif name == "trace.close":
            self._trace_close = self._adapt(fn)
        self._routes[name] = {"fn": self._adapt(fn),
                              "owner": module or name.split(".")[0],
                              "is_async": asyncio.iscoroutinefunction(fn),
                              "doc": doc, "module": module or name.split(".")[0],
                              "stream": bool(stream), "internal": bool(internal)}
        return name

    def substitute(self, name, fn):
        """替换同一条路由的实现（契约不变）：通信方式可换，调用方无感。"""
        if name not in self._routes:
            raise ValueError("route not registered: " + name)
        self._routes[name]["fn"] = self._adapt(fn)
        self._routes[name]["is_async"] = asyncio.iscoroutinefunction(fn)
        return name

    def routes(self):
        contracts = self._load_contracts()
        items = []
        for name, r in sorted(self._routes.items()):
            if r.get("internal"):
                continue
            spec = contracts.get(name) or {}
            items.append({"name": name, "doc": r["doc"], "module": r["module"],
                          "stream": r["stream"],
                          "in": sorted((spec.get("in") or {}).keys()),
                          "out": sorted((spec.get("out") or {}).keys())})
        return items

    def route(self, name):
        """按名取一条路由（不存在返回 None）。"""
        return self._routes.get(name)

    # ---- 契约（消息结构是数据，不是代码里的零散字段）----
    def _load_contracts(self):
        """逐模块读 `data/api.yaml`：谁提供能力，谁声明它收发什么。"""
        loaded = getattr(self.ctx, "loaded", None) or {}
        # 装配是逐步进行的：早期调用只能看到已装好的一部分模块，缓存会残缺。
        # 所以缓存的"有效期"绑在已装模块数上，装配完成后再读一次就补齐。
        if self._contracts is not None and self._contracts_seen == len(loaded):
            return self._contracts
        found = {}
        if True:
            for name, mod in sorted(loaded.items()):
                try:
                    md = self.ctx.storage.own(mod.__file__)
                except Exception:  # noqa: BLE001 —— 装配早期 storage 可能还没装填
                    continue
                try:
                    if not md.exists("api.yaml"):
                        continue
                    raw = md.read_text("api.yaml")
                except Exception:  # noqa: BLE001
                    continue
                rec = self.ctx.codec.yaml_decode(raw or "{}")["value"] or {}
                for route, spec in (rec.get("routes") or {}).items():
                    found[route] = spec or {}
            # 装配早期 storage/codec 可能还没装填，读不到就当没读，不缓存空表
            if found or not loaded:
                self._contracts = found
                self._contracts_seen = len(loaded)
        return self._contracts or {}

    def reload_contracts(self):
        self._contracts = None
        self._contracts_seen = -1

    def contract(self, name):
        return self._load_contracts().get(name) or {}

    def warn_log(self):
        return list(self._warned)

    def _check(self, name, payload):
        """按契约校验入参。warn 模式只留证据，enforce 模式缺必填直接拒。"""
        spec = self.contract(name).get("in") or {}
        if not spec:
            return
        got = set((payload or {}).keys())
        missing = sorted([k for k, v in spec.items()
                          if isinstance(v, dict) and v.get("req") and k not in got])
        if not missing:
            return
        if self._cfg_str("api", "contract_mode", "enforce") == "enforce":
            raise self.ctx.ApiError(
                "路由 %s 缺少必填字段: %s" % (name, ", ".join(missing)),
                code="bad_payload", status=400)
        if len(self._warned) < 200:
            self._warned.append({"route": name, "missing": missing})

    # ---- 调用方身份与授权 ----
    def _group_of(self, owner):
        """模块属于哪个组：agent_common 是平台件，其余组是业务件。"""
        mod = (getattr(self.ctx, "loaded", None) or {}).get(owner)
        segs = str(getattr(mod, "__file__", "") or "").replace("\\", "/").split("/")
        if "modules" in segs:
            i = segs.index("modules")
            if len(segs) > i + 2:
                return segs[i + 1]
        return ""

    def _implicit_caller(self):
        """没显式传 caller 时：按当前 handler 的所属模块判定。

        平台件（agent_common）归 platform:*，业务件归 module:*，装配期归 platform:boot。
        """
        owner = _SCOPE.get()
        if not owner:
            return "platform:boot"
        return ("platform:" + owner) if self._group_of(owner) == "agent_common" else ("module:" + owner)

    def _internal_calls(self):
        """跨模块直调台账：caller 模块 -> 允许的目标模块集合（intenal-calls.yaml）。"""
        loaded = len(getattr(self.ctx, "loaded", None) or {})
        if self._calls is not None and self._calls_seen == loaded:
            return self._calls
        found = {}
        try:
            md = self.ctx.storage.own(__file__)
            raw = md.read_text("internal-calls.yaml") if md.exists("internal-calls.yaml") else ""
            rec = self.ctx.codec.yaml_decode(raw or "{}")["value"] or {}
            for row in rec.get("calls") or []:
                found[row.get("caller") or ""] = tuple(row.get("targets") or ())
        except Exception:  # noqa: BLE001 —— 装配早期读不到台账，按空表收口
            found = {}
        if found or not loaded:
            self._calls = found
            self._calls_seen = loaded
        return self._calls or {}

    def violations(self):
        """warn 模式下收集到的未登记直调证据（caller 模块 + 目标路由）。"""
        return list(self._violations)

    def _authorize(self, name, caller):
        """身份规则：需求引擎与平台件放行；模块只能调自己或在台账里登记的目标。"""
        caller = caller or self._implicit_caller()
        if caller in ("demand_engine", "boot"):
            return
        if caller.startswith("platform:"):
            return
        if caller.startswith("module:"):
            owner = caller.split(":", 1)[1]
            if owner == "agent_test":
                return
            target = name.split(".", 1)[0]
            if owner == target:
                return
            if target in PLATFORM_UTILS:
                return
            if target in self._internal_calls().get(owner, ()):
                return
            if self._cfg_str("api", "internal_call_mode", "warn") == "enforce":
                raise self.ctx.ApiError(
                    "模块 %s 直调他人能力未登记: %s（先在 internal-calls.yaml 登记，或改写成需求编排）"
                    % (owner, name), code="internal_call_unregistered", status=403)
            if len(self._violations) < 400:
                self._violations.append({"caller": owner, "route": name})
            return
        raise self.ctx.ApiError(
            "能力只能由需求调用: %s -> %s" % (caller, name),
            code="module_call_forbidden", status=403)

    def _route(self, name, caller):
        if name not in self._routes:
            raise self.ctx.ApiError("API 不存在: %s" % name, code="no_route", status=404)
        self._authorize(name, caller)
        return self._routes[name]

    # ---- 作用域包装：handler 执行期间把"谁在调"写进 contextvar ----

    # ---- 链路埋点：一次路由调用 = 一个 span（trace 自己的两条原语不埋，避免递归）----
    def _span_open(self, name, caller=""):
        fn = getattr(self, "_trace_open", None)
        if fn is None:
            return ""
        try:
            return str(fn(self.ctx, {"name": name, "caller": caller}).get("span") or "")
        except Exception:
            return ""

    def _span_close(self, span, status="ok", code="", attrs=None):
        if not span:
            return
        fn = getattr(self, "_trace_close", None)
        if fn is None:
            return
        try:
            fn(self.ctx, {"span": span, "status": status, "code": code,
                          "attrs": attrs or {}})
        except Exception:
            pass

    def _scoped(self, route, ctx, payload, name=""):
        token = _SCOPE.set(route["owner"])
        traced = route.get("module") != "trace"
        span = self._span_open("call:" + (name or route.get("module") or ""),
                               str(route.get("module") or "")) if traced else ""
        try:
            out = route["fn"](ctx, payload)
            if traced:
                self._span_close(span, "ok")
            return out
        except Exception as exc:
            if traced:
                self._span_close(span, "error", code=type(exc).__name__)
            raise
        finally:
            _SCOPE.reset(token)

    async def _ascoped(self, route, ctx, payload, name=""):
        token = _SCOPE.set(route["owner"])
        traced = route.get("module") != "trace"
        span = self._span_open("call:" + (name or route.get("module") or ""),
                               str(route.get("module") or "")) if traced else ""
        try:
            out = route["fn"](ctx, payload)
            if inspect.isawaitable(out):
                out = await out
            if traced:
                self._span_close(span, "ok")
            return out
        except Exception as exc:
            if traced:
                self._span_close(span, "error", code=type(exc).__name__)
            raise
        finally:
            _SCOPE.reset(token)

    def call(self, name, payload=None, caller=None, direct=False):
        """同步入口：先服从通道绑定，再按"同步/异步"决定怎么执行。

        direct=True 只用于"外部请求已经落到本进程的边界"（HTTP / SSE / 远端服务端）：
        报文已经在这台机器上，再按绑定往外发就是绕回自己，边界必须就地执行。
        异步路由不再无条件本地跑——绑了 unix/tcp/shm 时同样要发出去。
        """
        self._check(name, payload)
        route = self._route(name, caller)
        handler = route["fn"]
        if route["is_async"]:
            kind, _addr = ("direct", None) if direct else self.transport.kind_for(name)
            if kind != "direct":
                return self.transport.send(name, payload, handler, caller=caller)
            fut = asyncio.run_coroutine_threadsafe(
                self._ascoped(route, self.ctx, payload or {}, name), self._ensure_loop())
            return fut.result()
        if direct:
            return self._scoped(route, self.ctx, payload or {}, name)
        return self.transport.send(name, payload, handler, caller=caller)

    async def acall(self, name, payload=None, caller=None, direct=False):
        """异步入口：与 call 同一套通道判定，异步路由直接 await。"""
        self._check(name, payload)
        route = self._route(name, caller)
        handler = route["fn"]
        if route["is_async"]:
            kind, _addr = ("direct", None) if direct else self.transport.kind_for(name)
            if kind != "direct":
                return await self._ensure_loop().run_in_executor(
                    None, self.transport.send, name, payload or {}, handler, caller)
            return await self._ascoped(route, self.ctx, payload or {}, name)
        if direct:
            return self._scoped(route, self.ctx, payload or {}, name)
        return await self._ensure_loop().run_in_executor(
            None, self.transport.send, name, payload or {}, handler, caller)

    def notify(self, name, payload=None, caller=None):
        """单向投递：不取返回值。本机直连时立刻执行，跨机时只承诺"已发出"。"""
        self._check(name, payload)
        route = self._route(name, caller)
        kind, _addr = self.transport.kind_for(name)
        if kind == "direct":
            self._scoped(route, self.ctx, payload or {}, name)
            return {"transport": "direct", "sent": name}
        return self.transport.notify(name, payload, route["fn"], caller=caller)
