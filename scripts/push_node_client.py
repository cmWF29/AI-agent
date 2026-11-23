"""节点主动连云控面（push）出站客户端。

节点侧只做出站 HTTP：注册与能力上报、周期心跳续租、断线指数退避重连；控制面不必
能反向连到节点（NAT 后/内网均可）。协调状态全部在控制面，本客户端不持有台账，
也不实现调度决策。

通道口径：
- 注册路由 ``nodes.push_register``：上报 id/endpoint/transport/role/区域/容量/租约 TTL；
- 心跳路由 ``nodes.push_heartbeat``：上报在跑负载，刷新最后见活时间（租约续期信号）；
- 鉴权：共享密钥经请求体 ``node_token`` 带给控制面；密钥来自配置/环境变量，不在代码写死；
- 重连：连接/ RPC 失败按指数退避（``backoff_base * 2^(n-1)``，封顶 ``backoff_max``），
  恢复后先重新注册再继续心跳——控制面可能已按 TTL 把失联节点判出表。
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request


class PushError(Exception):
    """出站 RPC 失败：网络不通或控制面业务拒绝。``code`` 取控制面错误码。"""

    def __init__(self, code, detail=None):
        super().__init__(str(code))
        self.code = code
        self.detail = detail


class PushNodeClient:
    """单节点出站客户端；线程内单连接串行调用，不并发打控制面。"""

    def __init__(self, base, node_id, secret="", *, endpoint="", transport="http",
                 role="executor", public_exposed=False, region="", capacity=None,
                 lease_ttl=30.0, interval=1.0, backoff_base=0.2, backoff_max=4.0,
                 timeout=5.0, clock=time.time, opener=None):
        self.base = str(base or "").rstrip("/")
        self.node_id = str(node_id or "").strip()
        self.secret = str(secret or "")
        self.endpoint = str(endpoint or "")
        self.transport = str(transport or "http")
        self.role = str(role or "executor")
        self.public_exposed = bool(public_exposed)
        self.region = str(region or "")
        self.capacity = dict(capacity or {})
        self.lease_ttl = float(lease_ttl)
        self.interval = float(interval)
        self.backoff_base = float(backoff_base)
        self.backoff_max = float(backoff_max)
        self.timeout = float(timeout)
        self._clock = clock
        self._opener = opener or urllib.request.build_opener()
        self._failures = 0
        self.registered = False
        self.load: dict = {}

    # ------------------------------------------------------------------ 传输

    def _url(self, route):
        return self.base + "/api/rpc/" + route.replace(".", "/")

    def _post(self, route, payload):
        body = json.dumps(payload or {}).encode("utf-8")
        req = urllib.request.Request(
            self._url(route), data=body, method="POST",
            headers={"Content-Type": "application/json",
                     "X-Node-Token": self.secret})
        try:
            with self._opener.open(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8")
            data = json.loads(raw) if raw else {}
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise PushError("network", str(exc)) from exc
        except ValueError as exc:
            raise PushError("bad_payload", str(exc)) from exc
        if not data.get("ok"):
            raise PushError(data.get("code") or data.get("error") or "rpc_failed",
                            data)
        return data.get("result") or {}

    # ------------------------------------------------------------------ 动作

    def register(self):
        """上报节点身份、归属与容量；重复注册由控制面幂等去重。"""
        payload = {
            "id": self.node_id,
            "endpoint": self.endpoint,
            "transport": self.transport,
            "role": self.role,
            "public_exposed": self.public_exposed,
            "region": self.region,
            "capacity": self.capacity,
            "lease_ttl": self.lease_ttl,
            "node_token": self.secret,
        }
        try:
            res = self._post("nodes.push_register", payload)
        except PushError:
            self.mark_failure()
            raise
        self.registered = True
        self._failures = 0
        return res

    def heartbeat(self, load=None):
        """周期心跳：刷新负载与最后见活时间；失败计入退避计数。"""
        self.load = dict(load or self.load or {})
        try:
            res = self._post("nodes.push_heartbeat", {
                "node": self.node_id, "load": self.load,
                "node_token": self.secret})
        except PushError:
            self.mark_failure()
            raise
        self._failures = 0
        return res

    def ensure_registered(self):
        """断线恢复后先补注册；已注册过不重复打注册路由。"""
        if not self.registered:
            return self.register()
        return None

    # ------------------------------------------------------------------ 退避

    def mark_failure(self):
        """记一次失败，失败次数参与指数退避计算。"""
        self._failures += 1

    def backoff_delay(self):
        """本次失败后的退避秒数：2^(n-1) 倍 base，封顶 max；无失败返回 0。"""
        if self._failures <= 0:
            return 0.0
        step = self.backoff_base * (2 ** (self._failures - 1))
        return min(self.backoff_max, step)

    # ------------------------------------------------------------------ 主循环

    def run(self, command_file=None, stopped=None, beat_hook=None):
        """心跳主循环。

        ``command_file`` 内容：``run`` 正常发心跳；``pause`` 停心跳保活进程（假死）；
        ``stop`` 退出。``stopped`` 为可调用短路退出条件；``beat_hook`` 每次成功心跳后
        回调（演练用来落时间线证据）。
        """
        while True:
            if stopped is not None and stopped():
                return
            cmd = "run"
            if command_file is not None and command_file.exists():
                cmd = command_file.read_text(encoding="utf-8").strip() or "run"
            if cmd == "stop":
                return
            if cmd == "pause":
                time.sleep(self.interval)
                continue
            try:
                self.ensure_registered()
                self.heartbeat(self.load)
                if beat_hook is not None:
                    beat_hook()
            except PushError:
                # 失败计数已在 register/heartbeat 内记；这里只按退避值等待再重试
                time.sleep(self.backoff_delay())
                continue
            time.sleep(self.interval)
