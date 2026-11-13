# v3 需求对照表（20 条）与测试用例

> 每条都写清：**要什么 → 怎么实现 → 怎么验（哪条测试）**。
> 测试一律只打对外 API（`python3 tests/run_all.py`，自带 mock LLM，不花钱）。

## 0. 总原则（不可违背）

- 模块完全解耦：模块之间只走 `ctx.api("<module>.<route>")` 与事件总线，互相不 import。
- 可插拔：流程不写死在代码里，而是落在「角色库 / 流程库 / 技能库」的数据里。
- 秘书只发作业：秘书工具白名单没有 shell/文件/网页工具；收作业由 PM 干。
- 知识三层 `public / project / ticket` 是**并列**关系，不是包含关系（将来要多机分布式）。

---

## 1. 本机仓库搬到 `/E/AI`

- 实现：Windows 本机仓库从豆包工作目录 `Move-Item` 到 `E:\AI\hive-agent`，并留 `.git`。
- 验证：`git -C E:\AI\hive-agent log` 可用、`python tests\run_all.py` 在本地仍 94+/137 通过。
- 测试：`test_versions`（依赖真实 git 仓库形状）；本机手工验（不在 CI 里跑，因为路径是本机的）。

## 2. 工单级 git：临时分支 → 推远端 → 结单自己 pull；冲突后必须重审/重测

- 实现：
  - 每个项目一份裸仓库 `data/projects/<p>/repo.git`，一个 `main` 工作树 `data/projects/<p>/main`；
  - 每个工单 clone 出 `data/tickets/<T>/repo`，分支 `ticket/<T>`（`hive/modules/gitflow.py`）；
  - 收尾 `git_sync`：add → commit → fetch → **rebase 到最新 main** → push；
  - 结单时 `git_merge --no-ff` 合回 main；**冲突不硬来**：abort，返回冲突文件清单，
    工单状态置 `conflict`，系统给 PM 发“解决冲突 + 重跑测试 + 再结单”的指令；
  - 并行工单各写各的分支，天然不互相踩；只有同一处代码才会冲突，冲突必进上面这条重测流程。
- 测试：`test_gitflow`（建仓/分支/推送/合并/构造同文件冲突/冲突时工单不结单）。

## 3. PM 不只会编排：能读项目、小活自己干

- 实现：`PM_TOOLS` 增加 `shell / read_file / write_file / grep`；PM 提示词明确“先了解项目，
  小活自己做，大活才拉角色，不许编造”。
- 测试：`test_secretary_policy`（秘书仍无执行权）+ `test_tickets`（PM 能收作业/结单）；
  PM 工具的断言由 `test_secretary_policy` 反向保证权限模型没串。

## 4. 3 个项目 × 每项目 3 个工单并发；项目内构造冲突

- 实现：并发闸门 `BoundedSemaphore(sessions.max_concurrent)`，超出的排队；工单/项目按 `project` 隔离。
- 测试：`test_three_by_three`（9 单并发、3 个项目、PM 会话数、批量结单）；
  `test_gitflow`（同项目两单改同一文件 → 冲突被识别）。

## 5. 网页 HTTPS

- 实现：`server.tls{enabled,cert,key}`；`HttpService` 在 accept 后包 TLS（`TLSHTTPServer.get_request`），
  没有证书自动退回 HTTP；`/api/auth/status` 返回 `scheme`；健康自检返回 `tls: true`。
- 部署：`deploy/provision.sh` 用 openssl 生成自签证书（SAN 带 IP），权限 600。
- 测试：`test_https`（自签证书 → https 访问 → 自检 tls=true → 业务接口可用）。

## 6. 秘书架构：一个项目一个秘书

- 实现：本地层一个总秘书 `secretary`；每个项目一个项目秘书 `sec-<project>`（懒创建、按需重建）；
  `sessions.ensure{project}` 幂等；工单一律由秘书 `ticket_create` 派出。
- 测试：`test_project_secretary_delete`（`sec-gamma` 独立存在、群列表出现、删除项目时清理）。

## 7. 三层架构（本地层 / 项目层 / 工单层）与“多个本地层是否有必要”

- 结论（已写进 README）：**本地层 = 一次部署实例**（一台 VPS 一个节点），承载入口网页、
  总秘书、公共库；项目层挂项目秘书/项目仓/项目交付件；工单层挂 PM/角色/工单分支/工单交付件。
  多个本地层在业务上没有必要（模型是同一个、运维成本翻倍）；但架构保留 `instance.id`、
  知识三层并列、每工单独立 git 分支——将来要扩成多 VPS 时，把 `instance` 换成节点注册表即可。
- 实现：`config.instance{id,title,layer}`、`/api/web/groups` 返回 `instance`、群列表区分
  `layer: local|project`；交付件三层目录 `data/artifacts/{public,projects/<p>,projects/<p>/tickets/<T>}`。
- 测试：`test_project_secretary_delete`（groups.instance.layer=local）、`test_close_readonly_artifacts`（三层路径）。

## 8. 网页“删除项目”按钮 + 删除后处理

- 实现：`POST /api/projects/{id}/delete`；只销毁该项目秘书会话，保留工单/交付件/知识（证据不能删）。
- 测试：`test_project_secretary_delete`。

## 9. 交付件按三层归档，路径带工单号

- 实现：工单结单 → `artifacts.archive` 把工作目录复制到
  `data/artifacts/projects/<p>/tickets/<T>/`，并写 `index.json`（清单+大小）；
  角色共用工作目录，归档时去掉 `workspace/` 前缀，路径干净。
- 测试：`test_close_readonly_artifacts`（归档路径存在、`artifacts.list` 可浏览）。

## 10. 结单后会话销毁、群只读；要改就新开工单引用旧单号

- 实现：`_do_close` 依次：校验流程插件 → git 同步/合并 → 归档 → 通知角色沉淀知识 →
  `sessions.destroy` 掉 PM 与全部角色；`tickets.message` 对 `closed` 返回 410；
  `ticket_create` 支持 `parent` 字段，网页“基于此单新开”一键带过去。
- 测试：`test_close_readonly_artifacts`（410 + readonly + 会话销毁在 `test_tickets`）。

## 11. 群聊发言人身份 + 头像

- 实现：`sessions.display`（项目经理 / 开发A / 研发B / 核验者 / 流程专家…）；
  重名自动加 A/B 后缀；前端用名字哈希生成 SVG 头像（不依赖外网）。
- 测试：`test_group_chat`（时间线发言人 = 项目经理 / 撰写…）、`test_tickets`（display 字段）。

## 12. 系统消息分层：事件不进群聊

- 实现：时间线只取 `user/assistant` 两类消息；角色会话里的 `user` 消息渲染成
  「项目经理 → 开发A」的任务卡；结单/冲突/派活等事件走 `/api/tickets/{id}/flow` 与 `/api/web/events`。
- 测试：`test_group_chat`（时间线不含 event 角色、flow 有节点）。

## 13. 工单生命周期流程图（与群聊分开）

- 实现：`ticket.stages[]` + `GET /api/tickets/{id}/flow` 返回节点（立项/建分支/派 PM/拉角色/冲突/验收/归档/合并/结单）、
  当前状态、角色进度；网页顶部横向流程图。
- 测试：`test_group_chat`（flow.nodes 有已完成的立项节点）；`test_gitflow`（冲突阶段）。

## 14. 网页 Markdown 渲染

- 实现：前端内置 ~60 行轻量渲染器（标题/列表/代码块/行内代码/粗斜体/链接/表格/引用），
  不引入外部 CDN（VPS 上外网不可靠）。
- 测试：前端行为用浏览器验收（DOM 断言）；后端不涉及。

## 15. 流程专家 + 可插拔流程插件（必交产物自动校验）

- 实现：`library.design(role, responsibility, must_outputs, prompt, skills)` 一次生成
  角色卡（提示词）+ 流程插件（glob 校验项）+ 技能；
  角色 `session_result` 上报或结单时，`tickets._enforce_flows` 用插件校验产物，
  缺件自动发消息让角色补（最多 `max_retry` 次），不依赖模型自觉。
- 测试：`test_library_flow`（内置库、设计产出、缺件识别、齐件通过）。

## 16. 流式输出 + 打断，不设超时

- 实现：`LLMClient.chat(stream=True, on_delta)` 解析 SSE；ReAct 每段增量发 `llm.delta`；
  会话记录 `partial`；`/api/web/live` 返回“谁正在说 + 增量 + 步骤”；
  网页每 700ms 轮询显示打字机；角色消息旁“打断”按钮 → `sessions.interrupt`；
  `sessions.ask/wait` 默认 `timeout=0`（无限等）。
- 测试：`test_stream_trace`（llm.delta 事件、增量拼回正文）；`test_react_interrupt`（打断仍有效）。

## 17. 项目级/公共级交付件 + 角色库/流程库/技能库页面

- 实现：`/api/artifacts/list?layer=`、`/api/library/list?kind=`；网页右侧三层交付件切换 +
  顶部「库」页签（角色/流程/技能三栏，可点开看提示词与校验项）。
- 测试：`test_close_readonly_artifacts`（三层）、`test_library_flow`（三库）。

## 18. 工单号可复制；前因后果沉淀到项目知识

- 实现：群聊标题旁“复制”按钮；`ticket_create.parent` 把前序工单写进工单记录与 summary；
  `knowledge.write(ticket)` 的 00-summary 带上“前序工单”一行。
- 测试：`test_tickets`（知识归档）、`test_close_readonly_artifacts`（parent 透传）。

## 19. 全链路透明：LLM 请求 / 工具 / 总线 / 模块间 API / 角色间消息

- 实现：`kernel/trace.py` 落 `data/traces/<session>.jsonl`：
  `llm.request`（完整 messages+tools+参数，key 永不落盘）、`llm.response`（content/tool_calls/usage）、
  `tool.call` / `tool.result`、`api.call`（谁→哪条路由→入参出参）、`bus.event`、`agent.message`；
  网页「链路」抽屉按 session / ticket 过滤，点开看原文。
- 测试：`test_stream_trace`（含 messages/tools、不含 key、落盘存在）。

## 20. 健康自检含交付件体积 + 压缩存储

- 实现：`artifacts.stats`（三层总量、最大的工单、已压缩数）；`artifacts.compress` 把工单层打成
  `T-xxx.tar.gz`（保留 index），`compress_after_days` 可自动扫；健康自检新增
  `artifacts_size / artifacts_disk_headroom / trace` 三项。
- 测试：`test_close_readonly_artifacts`（stats>0、压缩产出 tar）、`test_http_auth`（自检项齐全）。

---

## 测试矩阵（138 条断言）

| # | 用例 | 覆盖需求 |
|---|---|---|
| 1 | test_bus | 0 总线 |
| 2 | test_output_policy | 原 1 输出策略 |
| 3 | test_react_offload | 原 1 落盘 |
| 4 | test_react_interrupt | 16 打断 |
| 5 | test_sessions_compact | 秘书压缩 |
| 6 | test_tickets | 2/3/10/11/18 |
| 7 | test_http_auth | 5/19/20 |
| 8 | test_cli_and_webchat | 4/6 入口 |
| 9 | test_ops | 版本/固定命令 |
| 10 | test_secretary_policy | 0 权限铁律 |
| 11 | test_projects_and_concurrency | 4/7 |
| 12 | test_group_chat | 11/12/13 |
| 13 | test_versions | 回退 |
| 14 | test_stream_trace | 16/19 |
| 15 | test_library_flow | 15/17 |
| 16 | test_project_secretary_delete | 6/7/8 |
| 17 | test_close_readonly_artifacts | 9/10/17/20 |
| 18 | test_gitflow | 2/4 |
| 19 | test_three_by_three | 4 |
| 20 | test_https | 5 |
