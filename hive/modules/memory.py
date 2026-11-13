"""记忆模块：轻量长期记忆（笔记 + 关键词检索）。

刻意不做向量库：这一版要的是“行为可预测 + 零依赖”，
后续要换 embedding/向量检索，只需要替换本模块内部实现，API 不变。
"""
from __future__ import annotations

import os
import time
import uuid

from ..kernel.api import ApiError, Module
from ..kernel.store import JsonDoc
from ..kernel.tools import Tool


class Memory(Module):
    name = "memory"

    def setup(self):
        path = os.path.join(self.cfg["root"], "data", "memory", "notes.json")
        self.doc = JsonDoc(path, {"notes": []})
        self.log.info("memory.ready", path=path)

        self.api.route("POST", "/api/memory/add")(self.add)
        self.api.route("GET", "/api/memory/search")(self.search)
        self.api.route("GET", "/api/memory/list")(self.list_notes)
        self.api.route("DELETE", "/api/memory/{note_id}")(self.delete)

        self.ctx.tools.register(Tool(
            "memory_add", "记住一条事实/结论/偏好，跨会话可检索。",
            {"type": "object", "properties": {
                "text": {"type": "string", "description": "一句话事实"},
                "tags": {"type": "array", "items": {"type": "string"}},
                "importance": {"type": "integer", "description": "1-5，默认 3"},
            }, "required": ["text"]},
            self._tool_add, origin=self.name))

        self.ctx.tools.register(Tool(
            "memory_search", "检索长期记忆。",
            {"type": "object", "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer"},
            }, "required": ["query"]},
            self._tool_search, origin=self.name))

    # ---------------- 存储 ----------------
    def add(self, payload):
        text = (payload.get("text") or "").strip()
        if not text:
            raise ApiError("text 不能为空", code="empty_text")
        note = {
            "id": "m-" + uuid.uuid4().hex[:10],
            "text": text[:4000],
            "tags": [str(t)[:40] for t in (payload.get("tags") or [])][:8],
            "importance": int(payload.get("importance") or 3),
            "source": payload.get("source") or "",
            "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        self.doc.update(lambda d: d["notes"].append(note))
        self.emit("memory.added", {"id": note["id"], "chars": len(text)})
        return {"note": note}

    def search(self, payload):
        query = (payload.get("query") or "").strip()
        if not query:
            raise ApiError("query 必填", code="missing_query")
        limit = min(int(payload.get("limit") or 10), 50)
        data = self.doc.read()
        terms = [t for t in query.lower().split() if t]
        scored = []
        for note in data.get("notes", []):
            text = (note.get("text") or "").lower()
            tags = " ".join(note.get("tags") or []).lower()
            score = sum(2 if t in text else 0 for t in terms) + sum(1 if t in tags else 0 for t in terms)
            if score:
                score += int(note.get("importance") or 3)
                scored.append((score, note))
        scored.sort(key=lambda x: -x[0])
        return {"query": query, "items": [n for _, n in scored[:limit]], "total": len(data.get("notes", []))}

    def list_notes(self, payload):
        data = self.doc.read()
        limit = min(int(payload.get("limit") or 50), 200)
        notes = list(reversed(data.get("notes", [])))[:limit]
        return {"items": notes, "total": len(data.get("notes", []))}

    def delete(self, payload):
        note_id = payload.get("note_id")
        removed = {"n": 0}

        def _drop(d):
            before = len(d["notes"])
            d["notes"] = [n for n in d["notes"] if n.get("id") != note_id]
            removed["n"] = before - len(d["notes"])
        self.doc.update(_drop)
        if not removed["n"]:
            raise ApiError("不存在: %s" % note_id, status=404, code="not_found")
        return {"deleted": note_id}

    # ---------------- 工具 ----------------
    def _tool_add(self, args, tctx):
        res = tctx.api("memory.add", text=args.get("text"), tags=args.get("tags"),
                       importance=args.get("importance"), source=tctx.session_id)
        return "已记住: %s" % res["note"]["id"]

    def _tool_search(self, args, tctx):
        res = tctx.api("memory.search", query=args.get("query"), limit=args.get("limit") or 10)
        if not res["items"]:
            return "没有相关记忆"
        return "\n".join("- (%s) %s" % (n["created"][:10], n["text"]) for n in res["items"])
