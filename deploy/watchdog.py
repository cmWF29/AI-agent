#!/usr/bin/env python3
"""Hive Watchdog —— 保活 + 健康判定 + 自动版本回退。

设计：
  * systemd 只负责 watchdog（Restart=always + 开机自启）；
  * watchdog 负责拉起/重启 agent（agent 是它的子进程，崩溃立刻拉起）；
  * 连续 N 次健康检查失败 -> git 回退一个版本（回退前把当前改动存到 autosave 分支，绝不丢）；
  * 网页上的“重启/回退/停止”通过 data/control/cmd-*.json 控制文件下发，进程间零耦合。

不依赖任何第三方库。
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import subprocess
import sys
import time
import urllib.error
import ssl
import urllib.request


class Watchdog:
    def __init__(self, repo, config_path=None, interval=10, threshold=3, health_timeout=8,
                 rollback_limit=3, auto_rollback=True):
        self.repo = os.path.abspath(repo)
        self.config_path = config_path or os.path.join(self.repo, "config", "config.json")
        self.interval = interval
        self.threshold = threshold
        self.health_timeout = health_timeout
        self.rollback_limit = rollback_limit
        self.auto_rollback = auto_rollback
        self.port = self._read_port()
        self.data_dir = os.path.join(self.repo, "data")
        self.control_dir = os.path.join(self.data_dir, "control")
        self.log_dir = os.path.join(self.data_dir, "logs")
        self.done_dir = os.path.join(self.control_dir, "done")
        self._ensure_dirs()
        self.log_file = os.path.join(self.log_dir, "watchdog.jsonl")
        self.rollback_log = os.path.join(self.log_dir, "rollback.jsonl")
        self.proc = None
        self.agent_out = None
        self.failures = 0
        self.rollbacks = []
        self.state = "starting"
        self.started_at = time.time()
        self.agent_started_at = None

    def _ensure_dirs(self):
        """回退/重启后数据目录可能被清掉，这里兜底重建（生产 data/ 与 config.json 都在 .gitignore 里）。"""
        for d in (self.control_dir, self.log_dir, self.done_dir, self.data_dir):
            try:
                os.makedirs(d, exist_ok=True)
            except OSError:
                pass
        # 配置被回退掉时，用示例配置兜底，至少让服务能起来（密钥需要人工补）
        cfg = self.config_path
        example = os.path.join(os.path.dirname(cfg), "config.example.json")
        if not os.path.exists(cfg) and os.path.exists(example):
            try:
                import shutil
                shutil.copyfile(example, cfg)
                self.log("config.restored_from_example", path=cfg,
                         warn="API Key / 密码已回到占位值，请重新填写")
            except OSError as exc:
                self.log("config.restore.failed", error=repr(exc))

    # ---------------- 基础 ----------------
    def _read_port(self):
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                return int(json.load(f).get("server", {}).get("port", 8787))
        except (OSError, ValueError, TypeError):
            return 8787

    def log(self, event, **fields):
        rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "t": round(time.time(), 3),
               "event": event, **fields}
        line = json.dumps(rec, ensure_ascii=False, default=str)
        print("[watchdog] " + line, flush=True)
        try:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass

    def _git(self, *args):
        try:
            return subprocess.run(["git", "-C", self.repo] + list(args),
                                  capture_output=True, text=True, timeout=60)
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            self.log("git.error", args=list(args), error=repr(exc))
            return None

    def head(self):
        res = self._git("rev-parse", "--short", "HEAD")
        return (res.stdout.strip() if res and res.returncode == 0 else "?")

    def version(self):
        try:
            with open(os.path.join(self.repo, "VERSION"), "r", encoding="utf-8") as f:
                return f.read().strip()
        except OSError:
            return "?"

    # ---------------- agent 进程 ----------------
    def start_agent(self):
        if self.proc and self.proc.poll() is None:
            return
        self._ensure_dirs()
        env = dict(os.environ)
        env["PYTHONPATH"] = self.repo + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
        env["PYTHONUNBUFFERED"] = "1"
        out_path = os.path.join(self.log_dir, "agent.out")
        self.agent_out = open(out_path, "a", encoding="utf-8")
        self.agent_out.write("\n==== start %s ====\n" % time.strftime("%Y-%m-%d %H:%M:%S"))
        self.agent_out.flush()
        cmd = [sys.executable, "-m", "hive.server", "--config", self.config_path]
        try:
            self.proc = subprocess.Popen(cmd, cwd=self.repo, env=env,
                                         stdout=self.agent_out, stderr=subprocess.STDOUT)
        except Exception as exc:
            self.log("agent.spawn.failed", error=repr(exc), cmd=cmd)
            self.proc = None
            raise
        self.agent_started_at = time.time()
        self.state = "running"
        self.log("agent.started", pid=self.proc.pid, port=self.port, head=self.head(), version=self.version())

    def stop_agent(self, reason="manual"):
        if not self.proc:
            return
        proc = self.proc
        self.proc = None
        try:
            proc.terminate()
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
        except Exception as exc:
            self.log("agent.stop.error", error=repr(exc))
        if self.agent_out:
            try:
                self.agent_out.close()
            except OSError:
                pass
            self.agent_out = None
        self.log("agent.stopped", pid=proc.pid, reason=reason)

    def agent_alive(self):
        return self.proc is not None and self.proc.poll() is None

    # ---------------- 健康 ----------------
    def _scheme(self):
        """TLS 开了就用 https 探活（自签证书不校验）。"""
        try:
            cfg = json.load(open(self.config_path or os.path.join(self.repo, "config", "config.json")))
            tls = (cfg.get("server") or {}).get("tls") or {}
            cert = os.path.join(self.repo, tls.get("cert") or "config/tls/server.crt")
            if tls.get("enabled") and os.path.exists(cert):
                return "https"
        except Exception:
            pass
        return "http"

    def health(self):
        url = "%s://127.0.0.1:%d/api/health/self" % (self._scheme(), self.port)
        try:
            if url.startswith("https"):
                ctx = ssl._create_unverified_context()
                resp = urllib.request.urlopen(url, timeout=self.health_timeout, context=ctx)
            else:
                resp = urllib.request.urlopen(url, timeout=self.health_timeout)
            with resp:
                data = json.loads(resp.read().decode("utf-8"))
            return bool(data.get("healthy")), data
        except urllib.error.HTTPError as e:
            return False, {"error": "HTTP %s" % e.code}
        except Exception as exc:
            return False, {"error": repr(exc)}

    # ---------------- 回退 ----------------
    def rollback(self, reason, target=None):
        now = time.time()
        self.rollbacks = [t for t in self.rollbacks if now - t < 3600]
        if len(self.rollbacks) >= self.rollback_limit:
            self.log("rollback.skipped", reason="一小时内回退次数达到上限", limit=self.rollback_limit)
            return False
        before = self.head()
        dirty = self._git("status", "--porcelain")
        branch = None
        if dirty and dirty.returncode == 0 and dirty.stdout.strip():
            stamp = time.strftime("%Y%m%d-%H%M%S")
            self._git("add", "-A")
            commit = self._git("commit", "-m", "watchdog autosave %s before rollback (%s)" % (stamp, reason))
            branch = "autosave/" + stamp
            self._git("branch", branch, "HEAD")
            # 尽力把存档分支推回裸仓库：机器整块挂了，改动也还在
            pushed = self._git("push", "-q", "origin", branch)
            self.log("rollback.autosave", branch=branch,
                     commit=(commit.stdout.strip() if commit else "?"),
                     pushed=bool(pushed and pushed.returncode == 0))
        ref = target or "HEAD^"
        prev = self._git("rev-parse", ref)
        if not prev or prev.returncode != 0:
            self.log("rollback.no_prev", head=before, target=ref)
            return False
        prev_sha = prev.stdout.strip()
        if before and prev_sha.startswith(before[:7]):
            self.log("rollback.same_version", head=before, target=ref)
            return False
        # 先记账再动工作区：reset 有可能连带删掉被误跟踪的 data/，日志要能留证据
        self.record_rollback({
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "reason": reason,
            "target": ref,
            "from": before,
            "to": prev_sha,
            "autosave_branch": branch,
            "phase": "before_reset",
        })
        res = self._git("reset", "--hard", prev_sha)
        after = self.head()
        ok = res is not None and res.returncode == 0
        self.rollbacks.append(now)
        self._ensure_dirs()
        self.record_rollback({
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "reason": reason,
            "target": ref,
            "from": before,
            "to": after,
            "autosave_branch": branch,
            "ok": ok,
        })
        self.log("rollback.done", ok=ok, before=before, after=after, target=ref, autosave=branch)
        return ok

    def record_rollback(self, rec):
        try:
            with open(self.rollback_log, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except OSError:
            pass
        # 语法自检，坏代码别反复拉起
        chk = subprocess.run([sys.executable, "-m", "compileall", "-q", os.path.join(self.repo, "hive")],
                             capture_output=True, text=True, timeout=60)
        rec["compile_ok"] = chk.returncode == 0
        if chk.returncode != 0:
            self.log("rollback.compile_failed", output=(chk.stdout or "")[-2000:])

    # ---------------- 控制文件 ----------------
    def handle_controls(self):
        for path in sorted(glob.glob(os.path.join(self.control_dir, "cmd-*.json"))):
            cmd = None
            try:
                with open(path, "r", encoding="utf-8") as f:
                    cmd = json.load(f)
            except (OSError, ValueError) as exc:
                self.log("control.bad_file", path=path, error=repr(exc))
            finally:
                try:
                    os.replace(path, os.path.join(self.done_dir, os.path.basename(path)))
                except OSError:
                    pass
            if not cmd:
                continue
            name = cmd.get("cmd")
            self.log("control.received", cmd=name, payload=cmd)
            if name == "restart":
                self.stop_agent("control:restart")
                self.start_agent()
            elif name == "rollback":
                self.stop_agent("control:rollback")
                target = (cmd.get("target") or "").strip() or None
                ok = self.rollback("网页手动回退 %s" % (target or "HEAD^"), target=target)
                self.start_agent()
                self.write_heartbeat("rolled_back" if ok else "running")
            elif name == "stop":
                self.stop_agent("control:stop")
                self.state = "stopped"
                self.write_heartbeat("stopped")
                self.log("watchdog.exit", reason="stop 命令")
                return False
            else:
                self.log("control.unknown", cmd=name)
        return True

    # ---------------- 心跳 ----------------
    def write_heartbeat(self, state=None):
        if state:
            self.state = state
        hb = {
            "ts": round(time.time(), 3),
            "pid": os.getpid(),
            "state": self.state,
            "uptime_sec": int(time.time() - self.started_at),
            "agent_pid": self.proc.pid if self.agent_alive() else 0,
            "agent_uptime_sec": int(time.time() - self.agent_started_at) if self.agent_started_at else 0,
            "failures": self.failures,
            "head": self.head(),
            "version": self.version(),
            "port": self.port,
        }
        tmp = os.path.join(self.control_dir, "watchdog.json.tmp")
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(hb, f, ensure_ascii=False)
            os.replace(tmp, os.path.join(self.control_dir, "watchdog.json"))
        except OSError as exc:
            self.log("heartbeat.failed", error=repr(exc))
        return hb

    # ---------------- 主循环 ----------------
    def run(self):
        self.log("watchdog.start", repo=self.repo, port=self.port, interval=self.interval,
                 threshold=self.threshold, pid=os.getpid())
        if not self.agent_alive():
            try:
                self.start_agent()
            except Exception:
                pass
        self.write_heartbeat("running")
        while True:
            time.sleep(self.interval)
            if not self.handle_controls():
                break
            if not self.agent_alive():
                code = self.proc.returncode if self.proc else None
                self.log("agent.died", exit_code=code)
                try:
                    self.start_agent()
                except Exception as exc:
                    self.log("agent.restart.failed", error=repr(exc))
                    self.failures += 1
                self.write_heartbeat("restarting")
                continue

            ok, detail = self.health()
            if ok:
                if self.failures:
                    self.log("health.recovered", failed_checks=self.failures)
                self.failures = 0
                self.write_heartbeat("running")
                continue

            self.failures += 1
            self.log("health.failed", count=self.failures, detail=str(detail)[:300])
            if self.failures >= self.threshold:
                self.log("health.threshold_reached", count=self.failures)
                if self.auto_rollback:
                    self.stop_agent("health:rollback")
                    self.rollback("连续 %d 次健康检查失败: %s" % (self.failures, str(detail)[:200]))
                    self.start_agent()
                else:
                    self.stop_agent("health:restart")
                    self.start_agent()
                self.failures = 0
                self.write_heartbeat("recovered")
            else:
                self.write_heartbeat("degraded")

        return 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog="watchdog")
    parser.add_argument("--repo", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                        , help="仓库根目录（默认 watchdog.py 的上级）")
    parser.add_argument("--config", default=None)
    parser.add_argument("--interval", type=int, default=10)
    parser.add_argument("--threshold", type=int, default=3)
    parser.add_argument("--health-timeout", type=int, default=8)
    parser.add_argument("--rollback-limit", type=int, default=3)
    parser.add_argument("--no-auto-rollback", action="store_true")
    args = parser.parse_args(argv)

    hb = Watchdog(
        repo=args.repo,
        config_path=args.config,
        interval=args.interval,
        threshold=args.threshold,
        health_timeout=args.health_timeout,
        rollback_limit=args.rollback_limit,
        auto_rollback=not args.no_auto_rollback,
    )
    try:
        return hb.run()
    finally:
        hb.stop_agent("watchdog.exit")


if __name__ == "__main__":
    sys.exit(main())
