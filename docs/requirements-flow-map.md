# 需求到流程库映射

| # | 需求 | 流程 id | 状态 | 证据 |
|---|---|---|---|---|
| 1 | PC 侧边栏可收起，与安卓统一 | `req-01` | 已实现 | `web/app.js` `toggleRail`、`body.rail-collapsed`；收起状态写入 `localStorage` |
| 2 | 空闲/高峰判断 + 排队 + 强制立即执行 | `req-02` | 已实现 | `hive/modules/idle.py`；工单/消息两条队列；`force` 绕过 |
| 3 | 去掉“本地节点/本地层”展示与代码 | `req-03` | 已实现 | `webchat.groups` 不再返回 instance；前端无 layer pill |
| 4 | 工单 tag，角色/用户可增删，双层沉淀 | `req-04` | 已实现 | `tickets.tags`、`ticket_tag` 工具、`library.tag_add` |
| 5 | 历史工单不动，只做增量 | `req-05` | 已实现 | 无迁移逻辑；旧单 `tags=[]` |
| 6 | 侧栏按项目分层；工单可删且保留知识/交付件 | `req-06` | 已实现 | 项目页、`tickets.delete` 仅 closed；`gitflow.ticket_remove` |
| 7 | 工单群聊内联模块报文，删除“链路”页 | `req-07` | 已实现 | `webchat._module_timeline`；`details.modgroup` 折叠；无 trace tab |
| 8 | PM 编排支持并行；悬浮改点击 | `req-08` | 已实现 | `flow.parallel_stage.branches`；节点/分支点击弹详情 |
| 9 | 压缩秘书上下文移到项目面板并标明对象 | `req-09` | 已实现 | 项目页“压缩本项目秘书上下文”；`sec-<p>` |
| 10 | 复核流程是否真可插拔并给示例 | `req-10` | 已实现 | 角色卡 + 流程插件 + 技能；`library.design`；文档示例 |
| 11 | 项目/agent 文件系统只读浏览；git 取舍 | `req-11` | 已实现 | `/api/projects/{p}/files`、`/api/ops/files`；只读 |
| 12 | 本机仓库移到 `E:\AI` | `req-12` | 已实现 | Windows `E:\AI\hive-agent` |
| 13 | 推送 GitHub 远端并验证 | `req-13` | 已实现 | `git@github.com:cmWF29/AI-agent.git`，main `b268899` |
| 14 | 工单分支 push/pull；冲突由 git 解决，冲突后必须重验 | `req-14` | 已实现 | `gitflow.sync/merge`；冲突置 `conflict`；`ticket_verify` 硬门禁 |
| 15 | PM 先了解项目，简单活自己干 | `req-15` | 已实现 | `PM_TOOLS` 含 shell/read/write；PM 提示词 |
| 16 | 3 项目 × 3 工单并发 + 冲突演练 | `req-16` | 已实现 | v3 实测数据；`test_three_by_three` |
| 17 | HTTPS 加强安全 | `req-17` | 已实现 | 自签 TLS；CSP/HSTS/X-Frame-Options/nosniff；登录限流 |
| 18 | 秘书架构：一个项目一个秘书 | `req-18` | 已实现 | `sec-<project>`；全局 `secretary` |
| 19 | 三层架构中“本地层”是否必要 | `req-19` | 已决策 | 结论：单部署=单本地层，不展示；见架构审查 |
| 20 | 项目可删除，后处理只清秘书会话 | `req-20` | 已实现 | `projects.delete`；保留工单/交付件/知识 |
| 21 | 交付件按三层归档且路径带工单号 | `req-21` | 已实现 | `artifacts/projects/<p>/tickets/<T>/...` |
| 22 | 结单后销毁 PM/角色会话，群聊只读 | `req-22` | 已实现 | `_do_close` destroy；`message` 410；`readonly` |
| 23 | 群聊发言人：用户=“我”，角色=角色名，头像 | `req-23` | 已实现（v4.1 修正） | `user_messages` 标记；`_session_chat` 区分我/秘书/PM→角色；首字母头像 |
| 24 | 群聊顶层“系统”消息是什么，应 agent→PM→角色 | `req-24` | 已实现（v4.1 修正） | 系统注入消息以“（系统）”开头，群聊过滤；kickoff 显示秘书→PM |
| 25 | 工单生命周期流程图与群聊分离 | `req-25` | 已实现 | `flow` 独立条；节点含冲突/复验/归档/合并 |
| 26 | Markdown 渲染 | `req-26` | 已实现 | `web/app.js md()`：标题/列表/表格/代码/引用/链接 |
| 27 | “流程专家”角色拆提示词/技能/流程插件 | `req-27` | 已实现 | `process` 内置角色；`flow_design`；`library.design` |
| 28 | 流式显示，可判断卡住/死循环并打断；不要超时 | `req-28` | 已实现 | `live` 轮询 partial；`interrupt`；LLM 无总超时 |
| 29 | 项目/公共交付件、角色库/流程库/技能库 | `req-29` | 已实现 | 交付件侧栏三层；库页面三个 tab + 标签库 |
| 30 | 工单号可复制、可基于老单新开、知识沉淀因果 | `req-30` | 已实现 | `btn-copy-ticket`；`btn-fork-ticket`；`parent` 写知识摘要 |
| 31 | 全链路透明：LLM 请求/响应、tool、模块 API、总线、角色通信 | `req-31` | 已实现 | trace → 模块报文；群聊可点完整 JSON |
| 32 | 健康自检含交付件体积；压缩存储 | `req-32` | 已实现 | `/api/health/self`、`artifacts.stats/compress` |
| 33 | 前端返回键、刷新恢复、完整状态转移图 | `req-33` | 已实现（v4.1 新增） | hash 路由 + `popstate` + `←` + Esc；`docs/ui-state-machine.md` |
