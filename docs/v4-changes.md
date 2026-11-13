# v4 改造说明（对应 11 条需求）

> 运行版本 0.4.0。v3 的 25164fb 保持可回退；本版只对**新工单**增量生效，历史工单数据不改。

## 1. PC 侧边栏收起
- 统一按钮：`☰` 在 PC 走 `body.rail-collapsed`（整栏隐藏），安卓走抽屉 `rail.open + 遮罩`。
- 点项目/工单会自动收起侧栏，不再遮挡聊天。

## 2. 空闲/高峰判断 + 排队
- 模块：`hive/modules/idle.py`，只暴露 `idle.status / judge / queue / enqueue / dequeue / flush / config`。
- 默认高峰：工作日 `09:00-12:00`、`14:00-18:00`；周末与 `holidays` 视为空闲；`offpeak_discount=0.6`。
- 工单 `tickets.create(when=auto)` 在高峰返回 `status=queued`，不进 git、不拉 PM；`idle` 每 30s 在空闲时调 `tickets.dispatch` 启动。
- 给秘书的消息 `webchat.send(force=false)` 在高峰进队列，空闲时 `sessions.send`。
- 用户勾“立即执行”= `force=true`，绕开排队。UI 顶栏显示 `高峰/空闲 · 排队 N`，点击可查看队列并“立即执行队列”。
- 日历解耦：`holidays` 先配置化；后续日历插件只需改 `idle.judge()` 的数据来源，业务方不用动。

## 3. 去掉本地节点
- 网页删除“本地节点/layer”展示；`webchat.groups` 不再返回 `instance`。
- 多本地层确认无必要：一个部署=一个执行环境，模型/密钥/库均共享；多实例只是多副本。v4 不再有该概念。

## 4. 工单 tag
- 工单新增 `tags` 字段（只对新工单生效）。
- API：`POST /api/tickets/{id}/tags {add:[], remove:[]}`；角色/PM 工具 `ticket_tag`。
- 沉淀：`library.tag_add` 同时写 `data/library/tags/public.json` 与 `.../projects/<p>.json`；库页面可看。
- UI：工单头显示 tag，可点 `×` 删除、`＋tag` 添加；新建工单可填 tag。

## 5. 历史工单
- 无迁移逻辑；旧工单没有 `tags` 字段按空处理，不重写历史记录。

## 6. 侧边栏分层 / 项目页 / 工单删除
- 侧栏只列项目 + 全局秘书；点项目进入项目页：
  - 项目管理（改名）、工单列表、秘书（进入对话/压缩本项目秘书）、新建工单、项目文件、项目层交付件。
- 新工单入口只在项目页（侧栏旧入口已删）。
- 已结单工单可删除：`POST /api/tickets/{id}/delete` 仅允许 `closed`；删记录与工作树，**交付件与知识保留**。
- 项目删除：只清理 `sec-<project>` 会话；工单/交付件/知识保留。

## 7. 群聊里的模块报文
- `webchat.timeline?modules=1` 把 trace 的 `llm.request/response`、`tool.call/result`、`api.call`、`bus.event`、`agent.message` 变成“模块角色”消息（模块·LLM / 工具 / 总线 / 模块 / 通信）。
- 点击任意模块消息弹出**完整 JSON 报文**；不再有独立“链路”页（trace 后端保留，供群聊消费）。
- 交付件侧栏只放交付件，不再塞链路。

## 8. 并行编排 + 点击式详情
- `tickets.flow` 新增 `parallel_stage.branches`（每个角色的状态/任务/字数），前端画“PM 并行编排”分支。
- 阶段节点和角色分支全部**点击**弹详情（PC/安卓一致），不再依赖 hover tooltip。
- “健康”“版本”保持原样；“链路”tab 已删除。

## 9. 压缩秘书上下文
- 从侧栏移入项目页，按钮明确为“压缩本项目秘书上下文”，调用 `/api/sessions/sec-<p>/compact`。

## 10. 流程可插拔（复核 + 示例）
当前实现是**真插拔**，分两层：
1. 角色卡（`data/library/roles/<role>.json`）：身份提示词 + `must_outputs`。
2. 流程插件（`data/library/flows/<role>.json`）：`checks`（glob 路径）+ `max_retry`。

执行链：`role_spawn` 时按角色卡组装提示词 → 角色调 `session_result` 时 `tickets._enforce_flows` 用流程插件检查工作树文件，缺件自动发消息催补（默认 2 次），结单前再兜底检查一遍。

**怎么插一个新流程（架构师示例）**：
```bash
curl -X POST https://<host>/api/library/design -H "X-Auth-Token: <token>" -d '{
  "role": "architect",
  "cn": "架构师",
  "responsibility": "负责架构级设计与技术取舍",
  "must_outputs": ["docs/architecture/*.md", "docs/adr/*.md"],
  "skills": [{"id":"adr","name":"ADR 写作","body":"每个决策一篇 ADR：背景/选项/结论/代价"}]
}'
```
这会同时落角色卡 + 流程插件 + 技能；之后 PM 直接 `role_spawn(role=architect)`，若只交了一个文件，系统会因缺 `docs/adr/*.md` 自动催补，而不是靠上下文“自觉”。

## 11. 文件系统 / git（取舍）
- 项目绑定 `data/projects/<p>/main`，网页提供**只读**文件树与文本预览：`GET /api/projects/{p}/files|file`。
- agent 自身源码/配置只读浏览：`GET /api/ops/files|file`（跳过 `.git`、`data`）。
- **不做网页直接编辑配置**：配置与代码的变更仍走 git（本地改→push→VPS 部署），避免网页写坏运行环境、也保留审计与回退。网页只负责“看得见”。
- git 状态/日志/回退继续由“版本”页承担。

## 测试
`python3 tests/run_all.py`：v3 基线 142 项 + v4 新增 19 项 = **161/161**。
新增覆盖：空闲判断/排队/强制派发、消息排队、tag 增删与双层沉淀、项目改名、项目文件树、源码树、流程图并行结构、模块消息、未结单不可删、无本地层字段。
