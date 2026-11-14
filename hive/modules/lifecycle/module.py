"""项目生命周期编排（lifecycle）。

projects 只负责“项目记录 + 项目自有数据”，tickets 只负责工单；
两边不再互相调用。这个模块是唯一把两边拼起来的地方：

* 项目详情 = projects.get + tickets.list（工单统计）
* 删除预览 = projects.delete_preview + 工单统计
* 删除 = 先校验未结单 / 按 cascade 删已结单工单，再调 projects.delete 清理项目自有数据

依赖方向：lifecycle -> projects / tickets，单向；projects 不再指向 tickets。
"""
from __future__ import annotations

from ...kernel.api import ApiError, Module
from ...kernel.tools import Tool


class Lifecycle(Module):
    name = "lifecycle"

    def setup(self):
        self.api.route("GET", "/api/projects/{project_id}", name="get_project")(self.get_project_api)
        self.api.route("GET", "/api/projects/{project_id}/delete-preview",
                       name="delete_preview")(self.delete_preview_api)
        self.api.route("POST", "/api/projects/{project_id}/delete",
                       name="delete_project")(self.delete_project_api)
        self._register_tools()
        self.log.info("lifecycle.ready")

    def _register_tools(self):
        def status_tool(args, tctx):
            pid = (args.get("project") or tctx.session.get("project")
                   or self.ctx.rule("lifecycle.default_project")["default"])
            p = self.get_project_api({"project_id": pid})["project"]
            lines = ["%s (%s) 工单 %d 个，未结单 %d 个" % (
                p["id"], p.get("title") or "-", p["ticket_count"], p["open_tickets"])]
            for t in p.get("tickets") or []:
                lines.append("- %s [%s] %s" % (t["id"], t["status"], t["title"]))
            return "\n".join(lines)

        self.ctx.tools.register(Tool("project_status", "查看某项目下的工单。",
                                     {"type": "object", "properties": {"project": {"type": "string"}}},
                                     status_tool, origin=self.name))

    def _tickets_of(self, pid):
        try:
            return self.ctx.rule("lifecycle.list_tickets", project=pid).get("items", [])
        except ApiError:
            return []

    def get_project_api(self, payload):
        """项目详情 + 工单统计；网页/CLI 都走这个公开入口。"""
        out = self.ctx.rule("lifecycle.project_snapshot", project_id=payload["project_id"])["project"]
        tickets = self._tickets_of(out["id"])
        out["tickets"] = [{"id": t["id"], "title": t["title"], "status": t["status"],
                           "tags": t.get("tags") or []} for t in tickets]
        out["ticket_count"] = len(tickets)
        out["open_tickets"] = len([t for t in tickets if t["status"] not in ("closed",)])
        return {"project": out}

    def delete_preview_api(self, payload):
        """删除预览 = 项目存储统计 + 工单统计。"""
        base = self.ctx.rule("lifecycle.preview_delete", project_id=payload["project_id"])
        tickets = self._tickets_of(base["project"]["id"])
        open_tickets = [t["id"] for t in tickets if t.get("status") != "closed"]
        base["tickets"] = len(tickets)
        base["closed_tickets"] = len(tickets) - len(open_tickets)
        base["open_tickets"] = open_tickets
        return base

    def delete_project_api(self, payload):
        """项目归档/删除的唯一公开入口。

        mode=archive 直接转给 projects；mode=delete 时先做工单校验与已结单级联，
        再让 projects 清理项目记录/交付件/知识/main 树/源码绑定。
        """
        if (payload.get("mode") or "delete") == "archive":
            return self.ctx.rule("lifecycle.delete_project", project_id=payload["project_id"],
                                mode="archive", archived=payload.get("archived", True))

        project = self.ctx.rule("lifecycle.project_snapshot", project_id=payload["project_id"])["project"]
        pid = project["id"]
        cascade = payload.get("cascade") if isinstance(payload.get("cascade"), dict) else {}
        tickets = self._tickets_of(pid)
        open_tickets = [t["id"] for t in tickets if t.get("status") != "closed"]
        if open_tickets and not bool(payload.get("force")):
            raise ApiError("还有未结单工单，不能删除项目；先结单或显式 force",
                           status=409, code="open_tickets",
                           extra={"open_tickets": open_tickets})

        deleted_tickets = []
        if cascade.get("tickets"):
            for t in tickets:
                if t.get("status") != "closed":
                    continue
                try:
                    self.ctx.rule("lifecycle.delete_ticket", ticket_id=t["id"])
                    deleted_tickets.append(t["id"])
                except ApiError as exc:
                    self.log.warn("lifecycle.delete.ticket_failed", project=pid,
                                  ticket=t["id"], error=exc.message)

        result = self.ctx.rule("lifecycle.delete_project", project_id=pid, mode="delete",
                              cascade=cascade, force=payload.get("force"))
        result["deleted_tickets"] = deleted_tickets
        return result
