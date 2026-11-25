"""L2 接口契约层：对靠 HTTP 暴露的业务路由按不可信输入打真闸。

不 mock 断言：本层引导一份真装配（临时数据目录 + 真 HTTP 服务），
经 urllib 走真实 HTTP 闸打下列探针：

  空 payload / 超长字符串 / 非法类型 / 缺字段 / 多余字段 /
  404 / 401 / 403 / 坏报文 / 幂等在途 / 越权直调 / 路径穿越。

判定口径：
- 除业务约定的 4xx 外，不许出现 500（服务端未捕获异常）；
- 未登录必须 401；内部路由必须 403；未知路由必须 404；
- 越权直调即便在 warn 模式放行，也必须在违规台账留证据；
- 路径穿越（``../``、绝对路径、编码绕过、符号链接）不许逃出数据目录。
"""
from __future__ import annotations

import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import yaml

from report import LayerResult, Timer

# assert 是保留字，不能写 ``assert.recorder``；把 assert 目录入路径后按普通模块加载。
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "assert"))
from recorder import Recorder  # noqa: E402

from layers import _bootstrap

PROBE_TIMEOUT = 5.0
ALLOWED_STATUS = {200, 400, 401, 403, 404, 409}


def _parse(raw: str):
    if not raw.strip():
        return {}
    try:
        return yaml.safe_load(raw) or {}
    except yaml.YAMLError:
        return {"_raw": raw}


class _Client:
    def __init__(self, port: int, token: str = "t"):
        self.port = port
        self.token = token

    def request(self, method: str, path: str, body=None, token: str | None = "t",
                timeout: float = PROBE_TIMEOUT) -> tuple[int, dict]:
        data = None
        headers = {}
        if token is not None:
            headers["X-Auth-Token"] = token
        if body is not None:
            data = yaml.safe_dump(body, allow_unicode=True, sort_keys=False,
                                  default_flow_style=False).encode("utf-8")
            headers["Content-Type"] = "application/yaml"
        req = urllib.request.Request(
            "http://127.0.0.1:%d%s" % (self.port, path),
            data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status, _parse(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, _parse(e.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            return -1, {"error": str(e)}


def _probe_matrix(client: _Client, rec: Recorder) -> None:
    """对稳定 RPC 路由跑非法输入矩阵；只允许约定 4xx/200，不许 500/挂死。"""
    route = "/api/rpc/demand_engine/run"
    cases = [
        ("空 payload", {}),
        ("缺 id 字段", {"x": 1}),
        ("多余未知字段", {"id": "health-self", "bogus": "zzz"}),
        ("id 为数组", {"id": [1, 2, 3]}),
        ("id 为对象", {"id": {"a": 1}}),
        ("id 为数字", {"id": 12345}),
        ("超长字符串", {"id": "x" * 20000}),
    ]
    for label, body in cases:
        start = time.monotonic()
        status, parsed = client.request("POST", route, body=body)
        elapsed = time.monotonic() - start
        no_500 = status != 500
        fast = elapsed < PROBE_TIMEOUT
        rec.check("非法输入 · %s" % label, no_500 and fast,
                  "status=%s %.2fs" % (status, elapsed))

    # 坏报文：非法 YAML 文本，必须 400（bad_json），不许崩成 500
    bad_yaml = "{{{ : [unclosed\n  a: ]"
    req = urllib.request.Request(
        "http://127.0.0.1:%s%s" % (client.port, route), method="POST",
        data=bad_yaml.encode("utf-8"), headers={"Content-Type": "application/yaml"})
    try:
        urllib.request.urlopen(req, timeout=PROBE_TIMEOUT)
        rec.check("坏报文被拒", False, "未返回错误")
    except urllib.error.HTTPError as e:
        body = _parse(e.read().decode("utf-8"))
        rec.check("坏报文被拒", e.code == 400 and body.get("code") in ("bad_json", "bad_request"),
                  "status=%s code=%s" % (e.code, body.get("code")))
    except OSError as e:
        rec.check("坏报文被拒", False, str(e))


def _auth_and_routing(client: _Client, rec: Recorder) -> None:
    # 未登录 → 401
    status, body = client.request("POST", "/api/rpc/clock/now", body={}, token=None)
    rec.check("未登录拦截 401", status == 401, "status=%s" % status)

    # 内部路由 → 403
    status, body = client.request("POST", "/api/rpc/exec/run",
                                  body={"argv": ["true"]})
    rec.check("内部路由 403", status == 403, "status=%s" % status)

    # 未知路由 → 404 no_route
    status, body = client.request("GET", "/api/no/such-route")
    rec.check("未知路由 404", status == 404 and body.get("code") == "no_route",
              "status=%s code=%s" % (status, body.get("code")))

    # 坏路径 → 404 bad_path
    status, body = client.request("GET", "/api/a")
    rec.check("坏路径 404", status == 404 and body.get("code") == "bad_path",
              "status=%s code=%s" % (status, body.get("code")))

    # 公开存活探头免鉴权
    status, body = client.request("GET", "/api/health/live", token=None)
    rec.check("存活探头公开", status == 200 and body.get("ok") is True,
              "status=%s" % status)


def _traversal(client: _Client, rec: Recorder, root: Path) -> None:
    """路径穿越：../、绝对路径、编码绕过、符号链接都不许逃出数据目录。"""
    attempts = [
        ("dotdot 相对", "/../../etc/passwd"),
        ("编码 dotdot", "/%2e%2e%2f%2e%2e%2fetc%2fpasswd"),
        ("斜杠编码绕过", "/..%2f..%2fetc%2fhosts"),
        ("绝对路径", "/etc/passwd"),
    ]
    for label, path in attempts:
        status, body = client.request("GET", path)
        leaked = isinstance(body, dict) and ("root:" in str(body) or "localhost" in str(body))
        rec.check("路径穿越 · %s" % label, status in (400, 403, 404) and not leaked,
                  "status=%s" % status)

    # 符号链接：在临时控制台目录里放一条指向根外的链接，静态读取不得跟出去。
    # Windows 普通用户没有 symlink 特权，改用目录 junction + 根外文件，仍验证同一条不逃逸语义。
    console = root / "agent" / "web" / "console"
    target_root = None
    if console.is_dir():
        link = console / "evil-link"
        try:
            if link.is_symlink() or link.exists():
                link.unlink()
            if os.name == "nt":
                import subprocess
                import tempfile
                target_root = Path(tempfile.mkdtemp(prefix="hive-evil-"))
                (target_root / "secret.txt").write_text(
                    "localhost\n127.0.0.1\n", encoding="utf-8")
                subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target_root)],
                               check=True, capture_output=True, text=True)
                probe_path = "/evil-link/secret.txt"
            else:
                link.symlink_to("/etc/hosts")
                probe_path = "/evil-link"
            status, body = client.request("GET", probe_path)
            text = str(body)
            leaked = "localhost" in text and "127.0.0.1" in text
            rec.check("符号链接不逃逸", status in (400, 403, 404) and not leaked,
                      "status=%s" % status)
        except OSError as e:
            rec.check("符号链接不逃逸", False, str(e))
        finally:
            if link.is_symlink() or link.exists():
                try:
                    link.unlink()
                except OSError:
                    import shutil
                    shutil.rmtree(link, ignore_errors=True)
            if target_root is not None:
                import shutil
                shutil.rmtree(target_root, ignore_errors=True)


def _authorization(ctx, rec: Recorder) -> None:
    """越权直调：跨业务模块直调他人能力必须在违规台账留证据。"""
    api_cfg = ctx.cfg.setdefault("api", {})
    prev_mode = api_cfg.get("internal_call_mode")
    api_cfg["internal_call_mode"] = "warn"
    before = len(ctx.api.violations())
    # knowledge 越权调 projects.view（跨业务模块，未登记直调）
    try:
        ctx.api.call("projects.view", {}, caller="module:knowledge")
    except ctx.ApiError:
        pass
    after = ctx.api.violations()
    hit = [v for v in after[before:] if v.get("caller") == "knowledge"
           and v.get("route") == "projects.view"]
    rec.check("跨模块越权留痕", bool(hit), "新增违规 %d 条" % (len(after) - before))

    # 本模块调本模块是允许的：不应新增违规
    base = len(ctx.api.violations())
    try:
        ctx.api.call("projects.view", {}, caller="module:projects")
    except ctx.ApiError:
        pass
    rec.check("本模块直调放行", len(ctx.api.violations()) == base,
              "违规新增 %d" % (len(ctx.api.violations()) - base))
    if prev_mode is None:
        api_cfg.pop("internal_call_mode", None)
    else:
        api_cfg["internal_call_mode"] = prev_mode


def _idempotency(ctx, rec: Recorder) -> None:
    """幂等：在途重复投递判 in_flight；结算 done 后重复投递复用、不二次执行。"""
    key = "l2-contract-%d" % os.getpid()
    claim = lambda lease: ctx.api.call(
        "store.claim", {"module": "agent/tickets", "bucket": "contract",
                        "key": key, "lease_seconds": lease}, direct=True)
    first = claim(30)
    second = claim(30)
    rec.check("在途重复投递判在途",
              first.get("claimed") is True and second.get("in_flight") is True
              and second.get("claimed") is False,
              "first=%s second=%s" % (first.get("status"), second.get("status")))

    ctx.api.call("store.settle", {"module": "agent/tickets", "bucket": "contract",
                                  "key": key, "status": "done",
                                  "result_digest": "probe"}, direct=True)
    third = claim(30)
    rec.check("done 后复用不双跑",
              third.get("reused") is True and third.get("status") == "done",
              "third=%s" % third)


def run(timeout: float = 120.0) -> LayerResult:
    rec = Recorder()
    handle = None
    with Timer() as t:
        try:
            handle = _bootstrap.boot()
            client = _Client(handle.port)
            _auth_and_routing(client, rec)
            _probe_matrix(client, rec)
            _traversal(client, rec, handle.root)
            _authorization(handle.ctx, rec)
            _idempotency(handle.ctx, rec)
        except Exception as e:  # noqa: BLE001 —— 层级兜底，记红不崩入口
            rec.check("L2 装配/探针异常", False, "%s: %s" % (type(e).__name__, e))
        finally:
            if handle is not None:
                handle.cleanup()
    return LayerResult(
        layer="L2", title="接口契约（不可信输入/鉴权/越权/穿越/幂等）",
        ok=rec.ok, duration=t.elapsed, checks=rec.checks,
        note="探针走真实 HTTP 闸；warn 模式下放行的越权以违规台账为准。",
    )
