"""空闲/高峰判断 + 需求排队（需求：空闲时段便宜，允许堆积）。

设计目标：**只做一个判断模块**，不关心工单/消息怎么执行。
  * 判断：工作日的高峰窗口（可配置）、周末、法定节假日（先用配置列表，后续换日历插件）；
  * 排队：高峰时把“工单/消息”存进队列，空闲时再调用对应模块的 API 执行；
  * 强制：用户对某条需求选择“直接执行”，绕过判断。

对外 API：idle.status / idle.judge / idle.enqueue / idle.queue / idle.flush / idle.config
"""
from __future__ import annotations

import datetime as _dt
import os
import threading
import time
import uuid

from ...kernel.api import ApiError, Module
from ...kernel.config import path_of
from ...kernel.store import Collection, JsonDoc

WEEK = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


class Idle(Module):
    name = "idle"

    def setup(self):
        cfg = self.cfg.get("idle") if isinstance(self.cfg.get("idle"), dict) else {}
        self.enabled = bool(cfg.get("enabled", True))
        self.force_peak = bool(cfg.get("force_peak", False))   # 调试/演练：强制高峰
        self.windows = cfg.get("peak_windows") or ["09:00-12:00", "14:00-18:00"]
        self.peak_days = cfg.get("peak_days") or [0, 1, 2, 3, 4]
        self.offpeak_discount = float(cfg.get("offpeak_discount", 0.6))
        self.holidays = set(cfg.get("holidays") or [])
        self.tick = int(cfg.get("tick_seconds", 30))
        self.tz_offset = float(cfg.get("utc_offset_hours", 8))   # 高峰窗口按本地时间判断
        self.root = path_of(self.cfg, "idle.root", "data/idle")
        self.store = Collection(self.root)
        # 项目级忙闲配置：项目页“本项目空闲队列”保存到这里，不覆盖全局默认
        self.project_store = JsonDoc(os.path.join(self.root, "projects.json"), {"projects": {}})
        self.q_lock = threading.RLock()
        # 工单派发改成事件 + ack：idle 不再同步调 tickets.dispatch，
        # 但只有收到 ack 才把队列项出队，避免派发失败被静默丢掉。
        self._acks = {}
        self._acks_lock = threading.Lock()
        self.bus.subscribe("idle.dispatch.ack", self._on_dispatch_ack,
                           name="idle.dispatch_ack")
        if self.store.get("queue") is None:
            self.store.put("queue", {"items": []})
        self.log.info("idle.ready", windows=self.windows, discounts=self.offpeak_discount)
        self.api.route("GET", "/api/idle/status", name="status")(self.status_api)
        self.api.route("GET", "/api/idle/judge", name="judge")(lambda payload: {"idle": self.judge()})
        self.api.route("GET", "/api/idle/queue", name="queue")(self.queue_api)
        self.api.route("POST", "/api/idle/enqueue", name="enqueue")(self.enqueue_api)
        self.api.route("POST", "/api/idle/flush", name="flush")(self.flush_api)
        self.api.route("POST", "/api/idle/dequeue", name="dequeue")(self.dequeue_api)
        self.api.route("POST", "/api/idle/config", name="config")(self.config_api)
        self._stop = False
        threading.Thread(target=self._loop, name="idle-loop", daemon=True).start()

    # ---------------- 判断 ----------------
    def _defaults(self):
        return {
            "enabled": self.enabled,
            "peak_windows": list(self.windows),
            "peak_days": list(self.peak_days),
            "offpeak_discount": self.offpeak_discount,
            "force_peak": self.force_peak,
            "holidays": sorted(self.holidays),
        }

    def settings(self, project=""):
        """全局配置 + 项目覆盖；项目页保存的值优先。"""
        base = self._defaults()
        if not project:
            return base
        try:
            over = ((self.project_store.read() or {}).get("projects") or {}).get(project) or {}
        except OSError:
            over = {}
        out = dict(base)
        out.update({k: over[k] for k in ("enabled", "peak_windows", "peak_days",
                                         "offpeak_discount", "force_peak", "holidays")
                    if k in over})
        out["project"] = project
        return out

    def _parse(self, text):
        try:
            a, b = text.split("-")
            h1, m1 = [int(x) for x in a.split(":")]
            h2, m2 = [int(x) for x in b.split(":")]
            return h1 * 60 + m1, h2 * 60 + m2
        except Exception:
            return None

    def judge(self, now=None, project=""):
        st = self.settings(project)
        enabled = bool(st.get("enabled"))
        windows = st.get("peak_windows") or ["09:00-12:00", "14:00-18:00"]
        peak_days = st.get("peak_days") or [0, 1, 2, 3, 4]
        discount = float(st.get("offpeak_discount", 0.6))
        holidays = set(st.get("holidays") or [])
        if now is None:
            now = _dt.datetime.now(_dt.timezone(_dt.timedelta(hours=self.tz_offset)))
        date_s = now.strftime("%Y-%m-%d")
        minute = now.hour * 60 + now.minute
        if not enabled:
            return {"peak": False, "reason": "空闲判断已关闭", "date": date_s, "discount": discount,
                    "next_change": "", "holiday": False, "weekend": now.weekday() >= 5,
                    "project": project}
        weekend = now.weekday() >= 5
        if st.get("force_peak"):
            return {"peak": True, "reason": "强制高峰", "date": date_s, "discount": 1.0,
                    "next_change": "", "holiday": False, "weekend": weekend, "project": project}
        holiday = date_s in holidays
        if holiday or weekend:
            return {"peak": False, "reason": "法定节假日" if holiday else "周末",
                    "date": date_s, "discount": discount, "next_change": "",
                    "holiday": holiday, "weekend": weekend, "project": project}
        if now.weekday() not in peak_days:
            return {"peak": False, "reason": "非工作日高峰日", "date": date_s,
                    "discount": discount, "next_change": "", "holiday": False, "weekend": False,
                    "project": project}
        for w in windows:
            rng = self._parse(w)
            if rng and rng[0] <= minute < rng[1]:
                return {"peak": True, "reason": "工作日高峰 %s" % w, "date": date_s,
                        "discount": 1.0, "next_change": "", "holiday": False,
                        "weekend": False, "project": project}
        return {"peak": False, "reason": "工作日非高峰", "date": date_s, "discount": discount,
                "next_change": "", "holiday": False, "weekend": False, "project": project}

    # ---------------- 队列 ----------------
    def _q(self):
        return self.store.get("queue") or {"items": []}

    def _save_q(self, q):
        self.store.put("queue", q)

    def enqueue(self, kind, payload, note="", project=""):
        with self.q_lock:
            q = self._q()
            item = {"id": "q-" + uuid.uuid4().hex[:8], "kind": kind, "payload": payload,
                    "project": project or payload.get("project") or "",
                    "note": note, "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "status": "queued", "attempts": 0}
            q["items"].append(item)
            self._save_q(q)
        self.emit("idle.queued", {"queue_id": item["id"], "kind": kind})
        return item

    def _pop(self, qid):
        with self.q_lock:
            q = self._q()
            keep = [i for i in q["items"] if i["id"] != qid]
            self._save_q({"items": keep})

    def _mark_failed(self, qid, error):
        with self.q_lock:
            q = self._q()
            for it in q["items"]:
                if it["id"] == qid:
                    it["attempts"] = int(it.get("attempts") or 0) + 1
                    it["last_error"] = str(error)[:300]
                    it["last_try"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            self._save_q(q)

    def _on_dispatch_ack(self, ev):
        p = ev.get("payload") or {}
        qid = p.get("queue_id")
        with self._acks_lock:
            slot = self._acks.get(qid)
        if not slot:
            return
        slot["ok"] = bool(p.get("ok"))
        slot["error"] = p.get("error") or ""
        slot["done"].set()

    def _dispatch_ticket(self, item):
        """发事件给 tickets，并等它回 ack；超时/失败都保留队列项。"""
        qid = item["id"]
        slot = {"done": threading.Event(), "ok": False, "error": ""}
        with self._acks_lock:
            self._acks[qid] = slot
        try:
            self.bus.publish("idle.ticket.dispatch",
                             {"queue_id": qid,
                              "ticket_id": (item.get("payload") or {}).get("ticket_id")},
                             source=self.name)
            if not slot["done"].wait(30):
                raise ApiError("工单派发等待 ack 超时", code="dispatch_timeout")
            if not slot["ok"]:
                raise ApiError(slot.get("error") or "工单派发失败", code="dispatch_failed")
        finally:
            with self._acks_lock:
                self._acks.pop(qid, None)

    def _dispatch(self, item):
        p = item.get("payload") or {}
        if item["kind"] == "ticket":
            return self._dispatch_ticket(item)
        if item["kind"] == "message":
            return self.ctx.rule("idle.send_message", session=p["session"], text=p["text"], force=True)
        raise ApiError("未知队列类型: %s" % item["kind"], code="bad_queue_kind")

    def flush(self, limit=20, force=False, project=""):
        if not force and self.judge(project=project)["peak"]:
            return {"ok": True, "skipped": "仍处于高峰，不执行队列", "done": []}
        done = []
        with self.q_lock:
            if project:
                batch = [i for i in self._q()["items"]
                         if i.get("project") == project or
                         (i.get("payload") or {}).get("project") == project][:limit]
            else:
                batch = [i for i in self._q()["items"]
                         if not i.get("project") and not (i.get("payload") or {}).get("project")][:limit]
        for item in batch:
            try:
                self._dispatch(item)
                done.append({"id": item["id"], "kind": item["kind"], "ok": True})
                # 只有成功才出队；失败保留，避免静默丢消息/丢工单
                self._pop(item["id"])
            except Exception as exc:
                self._mark_failed(item["id"], exc)
                done.append({"id": item["id"], "kind": item["kind"], "ok": False, "error": repr(exc)[:200]})
        if done:
            self.emit("idle.flushed", {"count": len(done)})
            self.log.info("idle.flushed", count=len(done))
        return {"ok": True, "done": done}

    def _loop(self):
        while not self._stop:
            time.sleep(self.tick)
            try:
                q = self._q()["items"]
                projects = sorted({i.get("project") or "" for i in q})
                for pid in projects:
                    if pid and not self.judge(project=pid)["peak"]:
                        self.flush(limit=10, project=pid)
                if "" in projects and not self.judge()["peak"]:
                    self.flush(limit=10, project="")
            except Exception as exc:
                self.log.error("idle.loop", error=repr(exc))

    # ---------------- API ----------------
    def status_api(self, payload):
        project = (payload.get("project") or "").strip()
        items = [i for i in self._q()["items"] if not project or i.get("project") == project]
        return {"idle": self.judge(project=project), "queue": len(items),
                "queued": items[-10:], "windows": self.settings(project).get("peak_windows"),
                "discount": self.settings(project).get("offpeak_discount"),
                "holidays": self.settings(project).get("holidays"),
                "project": project, "project_config": self.settings(project)}

    def queue_api(self, payload):
        return {"items": self._q()["items"], "total": len(self._q()["items"])}

    def enqueue_api(self, payload):
        item = self.enqueue(payload.get("kind") or "message", payload.get("payload") or {},
                            payload.get("note") or "", payload.get("project") or "")
        return {"item": item}

    def dequeue_api(self, payload):
        qid = payload.get("queue_id")
        before = len(self._q()["items"])
        if qid:
            self._pop(qid)
        return {"ok": True, "removed": before - len(self._q()["items"])}

    def flush_api(self, payload):
        return self.flush(limit=int(payload.get("limit") or 20), force=bool(payload.get("force")),
                          project=(payload.get("project") or "").strip())

    def config_api(self, payload):
        project = (payload.get("project") or "").strip()
        allowed = {}
        if "enabled" in payload:
            allowed["enabled"] = bool(payload["enabled"])
        if payload.get("peak_windows") is not None:
            windows = [str(x).strip() for x in payload.get("peak_windows") if str(x).strip()]
            if not all(self._parse(w) for w in windows):
                raise ApiError("peak_windows 必须是 HH:MM-HH:MM 列表", code="bad_windows")
            allowed["peak_windows"] = windows
        if payload.get("peak_days") is not None:
            allowed["peak_days"] = sorted({int(x) for x in payload.get("peak_days") if 0 <= int(x) <= 6})
        if payload.get("offpeak_discount") is not None:
            allowed["offpeak_discount"] = max(0.0, min(1.0, float(payload["offpeak_discount"])))
        if "force_peak" in payload:
            allowed["force_peak"] = bool(payload["force_peak"])
        if payload.get("holidays") is not None:
            allowed["holidays"] = sorted({str(x) for x in payload["holidays"]})
        if project:
            def update(doc):
                doc.setdefault("projects", {}).setdefault(project, {}).update(allowed)
                return doc
            self.project_store.update(update)
        else:
            # 全局配置仍保留，兼容 CLI；项目页走 project 分支
            for k, v in allowed.items():
                setattr(self, {"enabled": "enabled", "peak_windows": "windows",
                               "peak_days": "peak_days", "offpeak_discount": "offpeak_discount",
                               "force_peak": "force_peak", "holidays": "holidays"}[k], v)
            if "holidays" in allowed:
                self.holidays = set(allowed["holidays"])
        self.emit("idle.config", {"project": project, "keys": sorted(allowed)})
        return {"idle": self.judge(project=project), "project": project,
                "project_config": self.settings(project)}

