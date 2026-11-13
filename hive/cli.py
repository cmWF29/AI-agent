"""hive CLI —— 网页调它，人也能直接用它。

它就是一条到 daemon 的 HTTP 通道：不持有会话状态，只负责把话带过去、把结果带回来。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import ssl
import urllib.parse
import urllib.request

from .kernel.config import load_config
from .version import __version__


class CliError(Exception):
    pass


class Client:
    def __init__(self, base_url, token, timeout=60):
        self.base = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def _request(self, method, path, payload=None, timeout=None):
        url = self.base + path
        data = None
        headers = {"Accept": "application/json", "X-Auth-Token": self.token or ""}
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        ctx = ssl._create_unverified_context() if url.startswith("https") else None
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout, context=ctx) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", "ignore")
            try:
                parsed = json.loads(raw)
                raise CliError(parsed.get("error") or raw)
            except ValueError:
                raise CliError("HTTP %s: %s" % (e.code, raw[:300]))
        except urllib.error.URLError as e:
            raise CliError("连不上 %s（%s）。agent 是否在跑？" % (self.base, e.reason))
        if isinstance(body, dict) and body.get("ok") is False:
            raise CliError(body.get("error") or "未知错误")
        return body or {}

    def get(self, path, **params):
        if params:
            path = path + "?" + urllib.parse.urlencode(params)
        return self._request("GET", path)

    def post(self, path, payload=None, timeout=None):
        return self._request("POST", path, payload or {}, timeout=timeout)


def _client(args):
    cfg = load_config(args.config)
    scheme = "http"
    tls = (cfg.get("server") or {}).get("tls") or {}
    if tls.get("enabled"):
        cert = tls.get("cert") or "config/tls/server.crt"
        if not os.path.isabs(cert):
            cert = os.path.join(cfg.get("root") or ".", cert)
        if os.path.exists(cert):
            scheme = "https"
    url = args.url or os.environ.get("HIVE_URL") or "%s://127.0.0.1:%d" % (scheme, int(cfg["server"]["port"]))
    token = args.token or os.environ.get("HIVE_TOKEN") or cfg["server"].get("token") or ""
    return Client(url, token, timeout=args.timeout)


def _print(data, as_json=False):
    if as_json:
        print(json.dumps(data, ensure_ascii=False, default=str))
        return
    if isinstance(data, dict):
        for k, v in data.items():
            if isinstance(v, (dict, list)):
                print("%s: %s" % (k, json.dumps(v, ensure_ascii=False, default=str)[:2000]))
            else:
                print("%s: %s" % (k, v))
    else:
        print(data)


# ---------------- 子命令 ----------------
def cmd_version(args):
    print("hive %s" % __version__)


def cmd_ticket_msg(args):
    """在工单群里说一句话（网页群聊走的就是这条命令）。"""
    c = _client(args)
    res = c.post("/api/tickets/%s/message" % args.ticket, {"text": args.text,
                                                          "session": args.session or ""})
    if not args.wait:
        _print(res, True)
        return 0
    sid = res.get("session")
    out = c.post("/api/sessions/wait", {"session": sid, "timeout": args.timeout}, timeout=args.timeout)
    print(json.dumps({"ok": True, "ticket": args.ticket, "session": sid,
                      "status": out.get("status"), "reply": out.get("reply") or ""}, ensure_ascii=False))
    return 0


def cmd_ticket_files(args):
    c = _client(args)
    _print(c.get("/api/tickets/%s/files" % args.ticket, limit=args.limit), args.json)


def cmd_ticket_file(args):
    c = _client(args)
    _print(c.get("/api/tickets/%s/file" % args.ticket, path=args.path), args.json)


def cmd_projects(args):
    c = _client(args)
    _print(c.get("/api/projects/list"), args.json)


def cmd_project_create(args):
    c = _client(args)
    _print(c.post("/api/projects/create", {"name": args.name, "title": args.title or ""}), args.json)


def cmd_groups(args):
    c = _client(args)
    _print(c.get("/api/web/groups"), args.json)


def cmd_timeline(args):
    c = _client(args)
    data = c.get("/api/web/timeline", group=args.group, limit=args.limit)
    if args.json:
        _print(data, True)
        return
    for i in data.get("items", []):
        print("[%s] %s: %s" % (i.get("ts") or "-", i.get("speaker") or "-", (i.get("text") or "")[:300]))


def cmd_health(args):
    c = _client(args)
    _print(c.get("/api/health/self"), args.json)


def cmd_status(args):
    c = _client(args)
    data = c.get("/api/ops/status")
    if args.json:
        _print(data, True)
        return
    print("版本: %s  pid: %s  uptime: %ss" % (data.get("version"), data.get("pid"), data.get("uptime_sec")))
    print("模型: %s (%s) key=%s" % (data["llm"]["model"], data["llm"]["base_url"], data["llm"]["has_key"]))
    wd = data.get("watchdog", {})
    print("watchdog: alive=%s hb_age=%ss" % (wd.get("alive"), wd.get("heartbeat_age_sec")))
    print("会话: %s  工单: %s" % (data.get("sessions"), data.get("tickets")))
    print("tokens: %s" % json.dumps(data["llm"]["usage"], ensure_ascii=False))


def cmd_ask(args):
    c = _client(args)
    payload = {"session": args.session, "text": args.text, "timeout": args.timeout - 5}
    started = time.time()
    try:
        res = c.post("/api/sessions/ask", payload, timeout=args.timeout)
    except CliError as e:
        if args.json:
            print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
        else:
            print("失败: %s" % e)
        return 2
    if args.json:
        print(json.dumps({"ok": True, "status": res.get("status"), "reply": res.get("reply", ""),
                          "ms": int((time.time() - started) * 1000)}, ensure_ascii=False))
    else:
        ts = res.get("status")
        print(res.get("reply") or "(空回复)")
        print("\n[status=%s  %sms]" % (ts, int((time.time() - started) * 1000)), file=sys.stderr)
    return 0


def cmd_sessions(args):
    c = _client(args)
    data = c.get("/api/sessions/list")
    if args.json:
        _print(data, True)
        return
    items = data.get("items", [])
    if not items:
        print("暂无会话")
        return
    for i in items:
        print("%-14s %-9s %-10s %5s条 %7s字 %s" % (
            i["id"], i["kind"], i.get("role") or "-", i["messages"], i["chars"], i.get("state") or i.get("status")))


def cmd_session(args):
    c = _client(args)
    data = c.get("/api/sessions/%s" % args.session_id)
    _print(data, True)


def cmd_send(args):
    c = _client(args)
    res = c.post("/api/sessions/send", {"session": args.session, "text": args.text})
    if args.wait:
        sid = args.session
        out = c.post("/api/sessions/wait", {"session": sid, "timeout": args.timeout}, timeout=args.timeout)
        print(out.get("reply") or out.get("status"))
    else:
        _print(res, args.json)


def cmd_spawn(args):
    c = _client(args)
    res = c.post("/api/sessions/spawn", {"kind": args.kind, "role": args.role, "title": args.title or "",
                                         "system_prompt": args.system_prompt or "", "input": args.task})
    _print(res, args.json)


def cmd_compact(args):
    c = _client(args)
    _print(c.post("/api/sessions/%s/compact" % args.session_id, {}), args.json)


def cmd_tickets(args):
    c = _client(args)
    data = c.get("/api/tickets/list")
    if args.json:
        _print(data, True)
        return
    for t in data.get("items", []):
        print("%-22s %-9s %-20s %s" % (t["id"], t["status"], t["project"], t["title"][:40]))


def cmd_ticket_create(args):
    c = _client(args)
    res = c.post("/api/tickets/create", {"title": args.title or "", "goal": args.goal, "project": args.project})
    _print(res, args.json)


def cmd_ticket_show(args):
    c = _client(args)
    _print(c.get("/api/tickets/%s" % args.ticket_id), args.json)


def cmd_ticket_close(args):
    c = _client(args)
    res = c.post("/api/tickets/%s/close" % args.ticket_id, {"summary": args.summary or "", "block": not args.async_})
    _print(res, args.json)


def cmd_logs(args):
    c = _client(args)
    _print(c.get("/api/obs/logs", limit=args.limit, level=args.level or ""), args.json)


def cmd_events(args):
    c = _client(args)
    _print(c.get("/api/obs/events", limit=args.limit, topic=args.topic or ""), args.json)


def cmd_ops(args):
    c = _client(args)
    if args.action == "status":
        return cmd_status(args)
    payload = {}
    if args.action == "rollback":
        payload["target"] = args.target or "HEAD^"
    _print(c.post("/api/ops/%s" % args.action, payload), args.json)


def cmd_versions(args):
    c = _client(args)
    _print(c.get("/api/ops/versions"), args.json)


def cmd_selftest(args):
    c = _client(args)
    _print(c.post("/api/ops/selftest", {"ping_llm": args.ping}), args.json)


def cmd_serve(args):
    from .server import main as serve_main
    argv = []
    if args.config:
        argv += ["--config", args.config]
    if args.host:
        argv += ["--host", args.host]
    if args.port:
        argv += ["--port", str(args.port)]
    serve_main(argv)


# ---------------- 入口 ----------------
def build_parser():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config", help="config.json 路径")
    common.add_argument("--url", help="daemon 地址，默认 http://127.0.0.1:<port>")
    common.add_argument("--token", help="API token")
    common.add_argument("--timeout", type=int, default=300, help="请求超时秒数")
    common.add_argument("--json", action="store_true", help="输出 JSON")

    p = argparse.ArgumentParser(prog="hive", description="Hive Agent CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("version").set_defaults(func=cmd_version)
    sub.add_parser("status", parents=[common]).set_defaults(func=cmd_status)
    sub.add_parser("health", parents=[common]).set_defaults(func=cmd_health)
    sub.add_parser("versions", parents=[common]).set_defaults(func=cmd_versions)
    st = sub.add_parser("selftest", parents=[common])
    st.add_argument("--ping", action="store_true", help="顺便 ping 一下大模型")
    st.set_defaults(func=cmd_selftest)

    a = sub.add_parser("ask", parents=[common], help="向常驻会话发一句话并等回复")
    a.add_argument("--session", default="secretary")
    a.add_argument("--text", required=True)
    a.set_defaults(func=cmd_ask)

    s = sub.add_parser("send", parents=[common])
    s.add_argument("--session", default="secretary")
    s.add_argument("--text", required=True)
    s.add_argument("--wait", action="store_true")
    s.set_defaults(func=cmd_send)

    sp = sub.add_parser("spawn", parents=[common])
    sp.add_argument("--kind", default="role")
    sp.add_argument("--role", default="")
    sp.add_argument("--title", default="")
    sp.add_argument("--task", default="")
    sp.add_argument("--system-prompt", default="")
    sp.set_defaults(func=cmd_spawn)

    ss = sub.add_parser("sessions", parents=[common])
    ss.set_defaults(func=cmd_sessions)

    sg = sub.add_parser("session", parents=[common])
    sg.add_argument("session_id")
    sg.set_defaults(func=cmd_session)

    cp = sub.add_parser("compact", parents=[common])
    cp.add_argument("session_id", nargs="?", default="secretary")
    cp.set_defaults(func=cmd_compact)

    tk = sub.add_parser("tickets", parents=[common])
    tk.set_defaults(func=cmd_tickets)

    tc = sub.add_parser("ticket-create", parents=[common])
    tc.add_argument("--goal", required=True)
    tc.add_argument("--title", default="")
    tc.add_argument("--project", default="")
    tc.set_defaults(func=cmd_ticket_create)

    ts = sub.add_parser("ticket-show", parents=[common])
    ts.add_argument("ticket_id")
    ts.set_defaults(func=cmd_ticket_show)

    tcl = sub.add_parser("ticket-close", parents=[common])
    tcl.add_argument("ticket_id")
    tcl.add_argument("--summary", default="")
    tcl.add_argument("--async", dest="async_", action="store_true")
    tcl.set_defaults(func=cmd_ticket_close)

    tm = sub.add_parser("ticket-msg", parents=[common], help="在工单群里说一句话")
    tm.add_argument("--ticket", required=True)
    tm.add_argument("--text", required=True)
    tm.add_argument("--session", default="", help="指定某个角色会话，默认发给 PM")
    tm.add_argument("--wait", action="store_true")
    tm.set_defaults(func=cmd_ticket_msg)

    tf = sub.add_parser("ticket-files", parents=[common], help="列工单交付件")
    tf.add_argument("--ticket", required=True)
    tf.add_argument("--limit", type=int, default=200)
    tf.set_defaults(func=cmd_ticket_files)

    tfile = sub.add_parser("ticket-file", parents=[common], help="读一个交付件")
    tfile.add_argument("--ticket", required=True)
    tfile.add_argument("--path", required=True)
    tfile.set_defaults(func=cmd_ticket_file)

    pj = sub.add_parser("projects", parents=[common])
    pj.set_defaults(func=cmd_projects)

    pjc = sub.add_parser("project-create", parents=[common])
    pjc.add_argument("--name", required=True)
    pjc.add_argument("--title", default="")
    pjc.set_defaults(func=cmd_project_create)

    gp = sub.add_parser("groups", parents=[common], help="列网页群聊（秘书 + 各工单）")
    gp.set_defaults(func=cmd_groups)

    tl = sub.add_parser("timeline", parents=[common], help="读某个群的时间线")
    tl.add_argument("--group", default="secretary")
    tl.add_argument("--limit", type=int, default=60)
    tl.set_defaults(func=cmd_timeline)

    lg = sub.add_parser("logs", parents=[common])
    lg.add_argument("--limit", type=int, default=50)
    lg.add_argument("--level", default="")
    lg.set_defaults(func=cmd_logs)

    ev = sub.add_parser("events", parents=[common])
    ev.add_argument("--limit", type=int, default=50)
    ev.add_argument("--topic", default="")
    ev.set_defaults(func=cmd_events)

    op = sub.add_parser("ops", parents=[common])
    op.add_argument("action", choices=["status", "restart", "stop", "rollback"])
    op.add_argument("--target", default="", help="rollback 回退到哪个版本（commit/分支），默认 HEAD^")
    op.set_defaults(func=cmd_ops)

    sv = sub.add_parser("serve", help="前台启动 daemon（生产由 watchdog 托管）")
    sv.add_argument("--config", default=None)
    sv.add_argument("--host", default=None)
    sv.add_argument("--port", type=int, default=None)
    sv.set_defaults(func=cmd_serve)
    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args) or 0
    except CliError as e:
        print("错误: %s" % e, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
