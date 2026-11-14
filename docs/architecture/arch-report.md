# 架构静态扫描报告

生成时间：2026-11-14T13:17:18Z

## 结论

- 门禁：**通过**
- 模块数：21；API 调用边：0；API 环：0；import 环：0
- 流程数：50；流程 DAG 环：0
- 网页状态：一致（状态 12 / 事件 15 / DOM id 110 / 按钮 57 / 控件 27）

## 模块唯一出口与对外 API

| 模块 | 唯一出口 | 路由 | 工具 | 跨模块 import |
| --- | --- | --- | --- | --- |
| agents | `hive/modules/agents/__init__.py` | 2 | 0 | 无 |
| archgate | `hive/modules/archgate/__init__.py` | 1 | 0 | 无 |
| artifacts | `hive/modules/artifacts/__init__.py` | 7 | 0 | 无 |
| gitflow | `hive/modules/gitflow/__init__.py` | 8 | 3 | 无 |
| gitsync | `hive/modules/gitsync/__init__.py` | 2 | 0 | 无 |
| health | `hive/modules/health/__init__.py` | 4 | 0 | 无 |
| idle | `hive/modules/idle/__init__.py` | 7 | 0 | 无 |
| knowledge | `hive/modules/knowledge/__init__.py` | 7 | 0 | 无 |
| library | `hive/modules/library/__init__.py` | 10 | 3 | 无 |
| lifecycle | `hive/modules/lifecycle/__init__.py` | 3 | 1 | 无 |
| memory | `hive/modules/memory/__init__.py` | 4 | 0 | 无 |
| obs | `hive/modules/observability/__init__.py` | 5 | 0 | 无 |
| ops | `hive/modules/ops/__init__.py` | 11 | 0 | 无 |
| projects | `hive/modules/projects/__init__.py` | 14 | 2 | 无 |
| rules | `hive/modules/rules/__init__.py` | 5 | 0 | 无 |
| sessions | `hive/modules/sessions/__init__.py` | 12 | 0 | 无 |
| skills | `hive/modules/skills/__init__.py` | 6 | 0 | 无 |
| testrunner | `hive/modules/testrunner/__init__.py` | 2 | 0 | 无 |
| tickets | `hive/modules/tickets/__init__.py` | 15 | 0 | 无 |
| toolpack | `hive/modules/toolpack/__init__.py` | 0 | 5 | 无 |
| webchat | `hive/modules/webchat/__init__.py` | 9 | 0 | 无 |

## 模块 API 依赖（同步调用）


### API 环

- 无

## 规则层（模块关系的唯一来源）

- 关系规则：58；业务流程：9；事件订阅：9；活跃：58/9；跨模块规则覆盖：18/33；对外入口：33/33；对外契约：12；冲突：无
- 业务模块直接跨模块 API：0；直接 bus.subscribe：0；模块直接 UI 函数跨调：0；未登记 UI API 契约：0

### 规则层 -> 能力模块

- `rules` -> `artifacts`, `gitflow`, `health`, `idle`, `knowledge`, `library`, `obs`, `projects`, `sessions`, `tickets`

### 模块 -> 规则

- `health`: `health.artifact_stats`, `health.probe_artifacts`, `health.probe_knowledge`, `health.probe_library`, `health.probe_projects`, `health.probe_sessions`, `health.probe_tickets`
- `idle`: `idle.send_message`
- `lifecycle`: `lifecycle.default_project`, `lifecycle.delete_project`, `lifecycle.delete_ticket`, `lifecycle.list_tickets`, `lifecycle.preview_delete`, `lifecycle.project_snapshot`
- `ops`: `ops.knowledge_snapshot`, `ops.session_snapshot`, `ops.ticket_snapshot`
- `projects`: `project.init_workspace`, `project.purge_artifacts`, `project.purge_knowledge`
- `sessions`: `session.load_context`, `session.project_directory`
- `skills`: `skill.design_role`, `skill.store`
- `tickets`: `ticket.apply_tag`, `ticket.archive_outputs`, `ticket.bind_project`, `ticket.check_outputs`, `ticket.dequeue`, `ticket.judge_capacity`, `ticket.list_changes`, `ticket.list_sessions`, `ticket.load_card`, `ticket.load_context`, `ticket.merge_workspace`, `ticket.open_workspace`, `ticket.queue`, `ticket.release_session`, `ticket.remove_workspace`, `ticket.send_instruction`, `ticket.session_messages`, `ticket.session_status`, `ticket.spawn_session`, `ticket.sync_workspace`, `ticket.wait_session`, `ticket.write_learning`
- `webchat`: `chat.ensure_secretary`, `chat.judge_capacity`, `chat.project_directory`, `chat.queue_message`, `chat.route_ticket_message`, `chat.send_message`, `chat.session_context`, `chat.session_directory`, `chat.session_messages`, `chat.session_state`, `chat.ticket_context`, `chat.ticket_directory`

### 模块 -> 事件规则

- `health`: `event.health.heartbeat`
- `idle`: `event.idle.dispatch_ack`
- `obs`: `event.obs.stream`
- `sessions`: `event.project.delete_before`, `event.session.result.sessions`
- `tickets`: `event.artifacts.written`, `event.gitflow.conflict`, `event.idle.ticket_dispatch`, `event.session.result.tickets`

## 流程 DAG

| 流程 | 节点 | 边 | DAG 字段 | 环 |
| --- | --- | --- | --- | --- |
| agent-skill-demo | 1 | 0 | 无（仅 role/checks） | 无 |
| architect | 1 | 0 | 无（仅 role/checks） | 无 |
| architecture-gate | 8 | 8 | 有 | 无 |
| developer | 1 | 0 | 无（仅 role/checks） | 无 |
| developer-docs | 1 | 0 | 无（仅 role/checks） | 无 |
| ops | 1 | 0 | 无（仅 role/checks） | 无 |
| process | 1 | 0 | 无（仅 role/checks） | 无 |
| project-idle | 5 | 4 | 有 | 无 |
| project-lifecycle | 6 | 6 | 有 | 无 |
| req-01 | 4 | 3 | 有 | 无 |
| req-02 | 4 | 3 | 有 | 无 |
| req-03 | 4 | 3 | 有 | 无 |
| req-04 | 4 | 3 | 有 | 无 |
| req-05 | 4 | 3 | 有 | 无 |
| req-06 | 4 | 3 | 有 | 无 |
| req-07 | 4 | 3 | 有 | 无 |
| req-08 | 4 | 3 | 有 | 无 |
| req-09 | 4 | 3 | 有 | 无 |
| req-10 | 4 | 3 | 有 | 无 |
| req-11 | 4 | 3 | 有 | 无 |
| req-12 | 4 | 3 | 有 | 无 |
| req-13 | 4 | 3 | 有 | 无 |
| req-14 | 4 | 3 | 有 | 无 |
| req-15 | 4 | 3 | 有 | 无 |
| req-16 | 4 | 3 | 有 | 无 |
| req-17 | 4 | 3 | 有 | 无 |
| req-18 | 4 | 3 | 有 | 无 |
| req-19 | 4 | 3 | 有 | 无 |
| req-20 | 4 | 3 | 有 | 无 |
| req-21 | 4 | 3 | 有 | 无 |
| req-22 | 4 | 3 | 有 | 无 |
| req-23 | 4 | 3 | 有 | 无 |
| req-24 | 4 | 3 | 有 | 无 |
| req-25 | 4 | 3 | 有 | 无 |
| req-26 | 4 | 3 | 有 | 无 |
| req-27 | 4 | 3 | 有 | 无 |
| req-28 | 4 | 3 | 有 | 无 |
| req-29 | 4 | 3 | 有 | 无 |
| req-30 | 4 | 3 | 有 | 无 |
| req-31 | 4 | 3 | 有 | 无 |
| req-32 | 4 | 3 | 有 | 无 |
| req-33 | 4 | 3 | 有 | 无 |
| requirement-to-flow | 5 | 4 | 有 | 无 |
| researcher | 1 | 0 | 无（仅 role/checks） | 无 |
| reviewer | 1 | 0 | 无（仅 role/checks） | 无 |
| skill-decomposer | 1 | 0 | 无（仅 role/checks） | 无 |
| system-timeline | 4 | 3 | 有 | 无 |
| tester | 1 | 0 | 无（仅 role/checks） | 无 |
| web-state-contract | 5 | 4 | 有 | 无 |
| writer | 1 | 0 | 无（仅 role/checks） | 无 |

## 网页状态机

- 状态机校验：通过

## 门禁错误

- 无

## 已知债务（不阻塞当前门禁）

- 无
