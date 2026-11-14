# 规则覆盖审计（33 条历史需求）

规则目录只记录“模块之间的业务关系”，不把 UI、HTTPS、流式渲染等基础设施需求伪装成跨模块调用。
本表由 `data/rules/catalog.json` 的 `requirements` 字段生成，规则面板的
“跨模块规则覆盖 18/33”与此一致；“对外入口 33/33”是另一个口径，表示 33 条需求都有
UI/API/宿主/设施承载位置，不等于 33 条都有跨模块规则。

## 有显式规则覆盖（18 条）

| 需求 | 规则 |
| --- | --- |
| req-02 空闲/高峰判断 + 排队 | `ticket.judge_capacity`、`ticket.queue`、`ticket.dequeue`、`chat.judge_capacity`、`chat.queue_message`、`event.idle.ticket_dispatch`、`event.idle.dispatch_ack` |
| req-04 工单 tag 双层沉淀 | `ticket.create` |
| req-06 侧栏按项目分层，工单可删 | `project.delete`、`lifecycle.delete`、`event.project.delete_before` |
| req-07 群聊内联模块报文 | `chat.thread` |
| req-11 项目文件系统只读浏览 | `project.create` |
| req-14 工单分支 push/pull/冲突重验 | `ticket.open_workspace`、`ticket.sync_workspace`、`ticket.merge_workspace`、`event.gitflow.conflict` |
| req-15 PM 先了解项目 | `ticket.check_outputs`、`ticket.close` |
| req-18 一个项目一个秘书 | `ticket.bind_project`、`ticket.spawn_session`、`chat.ensure_secretary`、`project.create`、`chat.thread`、`chat.dispatch`、`session.context`、`event.session.result.tickets` |
| req-20 项目可删除 | `project.create`、`project.delete`、`lifecycle.delete`、`event.project.delete_before` |
| req-21 三层交付件归档 | `ticket.archive_outputs`、`project.purge_artifacts`、`ticket.close`、`project.delete`、`lifecycle.delete`、`event.artifacts.written` |
| req-22 结单销毁 PM/角色会话 | `ticket.spawn_session`、`ticket.send_instruction`、`ticket.release_session`、`ticket.create`、`ticket.close` |
| req-23 群聊发言人 | `chat.thread` |
| req-24 系统消息 agent→PM→角色 | `ticket.create`、`chat.thread` |
| req-25 生命周期流程图 | `ticket.close` |
| req-27 流程专家拆提示词/技能/流程 | `ticket.load_card`、`skill.design_role`、`ticket.create` |
| req-30 工单号/派生/知识沉淀 | `ticket.write_learning`、`project.purge_knowledge`、`ticket.create`、`ticket.close` |
| req-31 全链路透明 | `ticket.load_context`、`session.load_context`、`session.context` |
| req-32 健康自检含交付件体积 | `health.artifact_stats`、`ops.snapshot` |

## 非跨模块关系（15 条）

| 需求 | 不建规则的原因 | 承载位置 |
| --- | --- | --- |
| req-01 PC 侧边栏收起 | 纯前端宿主交互，无模块关系 | `web/core/`、状态机 |
| req-03 去掉本地节点展示 | 前端删除动作 | `web/core/`、`docs/requirements-audit-v4.md` |
| req-05 历史工单只做增量 | 工单持久化语义，不产生跨模块调用 | `tickets` 内部实现 |
| req-08 PM 并行/悬浮改点击 | UI 与编排表现 | `webchat/ui.js` |
| req-09 压缩秘书上下文入口 | UI 入口；压缩本身是 `sessions` 能力 | `projects/ui.js`、`sessions` |
| req-10 流程可插拔复核 | 架构门禁本身，不是业务关系 | `hive/archscan.py`、本目录文档 |
| req-12 仓库移到 `E:\AI` | 本地环境路径配置 | `config/` |
| req-13 推 GitHub 并验证 | 仓库运维动作，由 `gitsync` 提供状态/fetch | `hive/modules/gitsync`、`DEPLOY.md` |
| req-16 3×3 并发与冲突演练 | 测试场景，不是运行时关系 | `tests/run_all.py` |
| req-17 HTTPS 加强安全 | 传输层基础设施 | `hive/kernel/http.py`、`web/` |
| req-19 本地层是否必要 | 已移除该层的架构决策 | `docs/architecture/README.md` |
| req-26 Markdown 渲染 | 前端渲染能力 | `webchat/ui.js` |
| req-28 流式显示/打断/不超时 | LLM/ReAct 内核能力 | `hive/kernel/llm.py`、`react.py` |
| req-29 项目/公共交付件与三库页面 | UI 聚合页面，底层由 artifacts/library 提供 | `library/ui.js`、`artifacts/ui.js` |
| req-33 返回键/刷新恢复/状态机 | 前端宿主状态机 | `web/state-machine.json`、`web/core/core.js` |

## 模块 UI 对外契约（12 条）

浏览器是外部客户端，不是服务端模块。模块 UI 调公开 API 属于“对外入口”，不伪造成
服务端 A→B 规则；但每个跨模块 API 前缀必须在 `data/rules/surfaces.json` 显式登记，
`archscan` 会拒绝未登记的暗调用。当前 12 条契约覆盖 `projects`、`webchat`、
`artifacts`、`health`、`library` 五个模块 UI。

| UI 模块 | 公开 API 前缀 | 目标模块 | 说明 |
| --- | --- | --- | --- |
| `projects` | `/api/tickets` | `tickets` | 项目页读取/创建/删除工单 |
| `projects` | `/api/sessions` | `sessions` | 项目页读取会话、压缩秘书上下文 |
| `projects` | `/api/agents` | `agents` | 项目页读取 Agent 配置 |
| `projects` | `/api/ops` | `ops` | 项目页读取文件/配置 |
| `projects` | `/api/web` | `webchat` | 项目页读取群组/时间线 |
| `webchat` | `/api/tickets` | `tickets` | 群聊读取工单流、标签、投递消息 |
| `webchat` | `/api/sessions` | `sessions` | 群聊读取会话、打断当前发言 |
| `artifacts` | `/api/projects` | `projects` | 交付件页浏览项目源码/文件 |
| `artifacts` | `/api/ops` | `ops` | 交付件页浏览运行时文件 |
| `health` | `/api/artifacts` | `artifacts` | 健康页读取交付件统计 |
| `health` | `/api/ops` | `ops` | 健康页读取运行时状态 |
| `library` | `/api/skills` | `skills` | 技能库读取/安装/拆解/移除 |

## 维护规则

- 新增“模块 A 需要模块 B 的能力”时，先加 `data/rules/catalog.json` 关系规则，再在 A 中调
  `ctx.rule(...)`；不得直接 `ctx.api("B.xxx")`。
- 新增事件订阅时，先加 `kind:"event"` 规则（`from/to/topic`），再在订阅模块写
  `self.event(...)`；不得直接 `bus.subscribe`。
- 新增业务流程时，用 `kind:"process"` + `composes` 组合已有关系规则；流程执行
  `rules.process` 支持 `when` 条件、`parallel` 并行和 `compensate` 显式补偿，但不做隐式事务回滚。
- 新增模块 UI 的跨模块公开 API 调用时，先在 `data/rules/surfaces.json` 登记 `ui/target/prefix/methods`，
  再在 UI 中使用；它是对外契约，不是服务端规则关系。
- 纯 UI/基础设施需求继续记录在 `docs/requirement-flows.json`，不要为了凑覆盖率伪造关系。
