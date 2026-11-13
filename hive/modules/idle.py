"""空闲/高峰判断 + 需求排队（需求：空闲时段便宜，允许堆积）。

设计目标：**只做一个判断模块**，不关心工单/消息怎么执行。
  * 判断：工作日的高峰窗口（可配置）、周末、法定节假日（先用配置列表，后续换日历插件）；
  * 排队：高峰时把“工单/消息”存进队列，空闲时再调用对应模块的 API 执行；
  * 强制：用户对某条需求选择“直接执行”，绕过判断。

对外 API：idle.status / idle.judge / idle.enqueue / idle.queue / idle.flush / idle.config
"""
from __future__ import annotations

import datetime as _dt
import threading
import time
import uuid

from ..kernel.api import ApiError, Module
from ..kernel.config import path_of
from ..kernel.store import Collection

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
        self.q_lock = threading.RLock()
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
    def _parse(self, text):
        try:
            a, b = text.split("-")
            h1, m1 = [int(x) for x in a.split(":")]
            h2, m2 = [int(x) for x in b.split(":")]
            return h1 * 60 + m1, h2 * 60 + m2
        except Exception:
            return None

    def judge(self, now=None):
        if now is None:
            now = _dt.datetime.now(_dt.timezone(_dt.timedelta(hours=self.tz_offset)))
        date_s = now.strftime("%Y-%m-%d")
        minute = now.hour * 60 + now.minute
        if not self.enabled:
            return {"peak": False, "reason": "空闲判断已关闭", "date": date_s, "discount": self.offpeak_discount,
                    "next_change": "", "holiday": False, "weekend": now.weekday() >= 5}
        weekend = now.weekday() >= 5
        if self.force_peak:
            return {"peak": True, "reason": "强制高峰", "date": date_s, "discount": 1.0,
                    "next_change": "", "holiday": False, "weekend": weekend}
        holiday = date_s in self.holidays
        if holiday or weekend:
            return {"peak": False, "reason": "法定节假日" if holiday else "周末",
                    "date": date_s, "discount": self.offpeak_discount, "next_change": "",
                    "holiday": holiday, "weekend": weekend}
        if now.weekday() not in self.peak_days:
            return {"peak": False, "reason": "非工作日高峰日", "date": date_s,
                    "discount": self.offpeak_discount, "next_change": "", "holiday": False, "weekend": False}
        for w in self.windows:
            rng = self._parse(w)
            if rng and rng[0] <= minute < rng[1]:
                return {"peak": True, "reason": "工作日高峰 %s" % w, "date": date_s,
                        "discount": 1.0, "next_change": "", "holiday": False, "weekend": False}
        return {"peak": False, "reason": "工作日非高峰", "date": date_s, "discount": self.offpeak_discount,
                "next_change": "", "holiday": False, "weekend": False}

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

    def _dispatch(self, item):
        p = item.get("payload") or {}
        if item["kind"] == "ticket":
            return self.ctx.api("tickets.dispatch", ticket_id=p["ticket_id"], force=True)
        if item["kind"] == "message":
            return self.ctx.api("sessions.send", session=p["session"], text=p["text"], force=True)
        raise ApiError("未知队列类型: %s" % item["kind"], code="bad_queue_kind")

    def flush(self, limit=20, force=False, project=""):
        if not force and self.judge()["peak"]:
            return {"ok": True, "skipped": "仍处于高峰，不执行队列", "done": []}
        done = []
        with self.q_lock:
            batch = [i for i in self._q()["items"]
                     if not project or i.get("project") == project or
                     (i.get("payload") or {}).get("project") == project][:limit]
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
                if self.judge()["peak"]:
                    continue
                if self._q()["items"]:
                    self.flush(limit=10)
            except Exception as exc:
                self.log.error("idle.loop", error=repr(exc))

    # ---------------- API ----------------
    def status_api(self, payload):
        project = (payload.get("project") or "").strip()
        items = [i for i in self._q()["items"] if not project or i.get("project") == project]
        return {"idle": self.judge(), "queue": len(items),
                "queued": items[-10:], "windows": self.windows,
                "discount": self.offpeak_discount, "holidays": sorted(self.holidays),
                "project": project}

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
        if "enabled" in payload:
            self.enabled = bool(payload["enabled"])
        if payload.get("holidays"):
            self.holidays = set(payload["holidays"])
        return {"idle": self.judge(), "enabled": self.enabled, "holidays": sorted(self.holidays)}
