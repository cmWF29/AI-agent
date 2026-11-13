# 需求落地审计（v4.1）

审计基准：用户先后两批共 30 条需求（第一批 11 条，第二批 19 条）。结论按“已实现 / 部分实现 / 明确不做”标注，并给出代码位置、验证方式与剩余缺口。当前代码 `0.4.1-dev`，测试 **185/185**。

## 总览

| # | 需求 | 状态 | 证据 | 剩余 |
|---|---|---|---|---|
| 1 | PC 侧边栏可收起，与安卓统一 | 已实现 | `web/app.js` `toggleRail`、`body.rail-collapsed`；收起状态写入 `localStorage` | — |
| 2 | 空闲/高峰判断 + 排队 + 强制立即执行 | 已实现 | `hive/modules/idle.py`；工单/消息两条队列；`force` 绕过 | 日历未接，预留 `holidays` 配置 |
| 3 | 去掉“本地节点/本地层”展示与代码 | 已实现 | `webchat.groups` 不再返回 instance；前端无 layer pill | — |
| 4 | 工单 tag，角色/用户可增删，双层沉淀 | 已实现 | `tickets.tags`、`ticket_tag` 工具、`library.tag_add` | 历史工单无 tag（按需求不动） |
| 5 | 历史工单不动，只做增量 | 已实现 | 无迁移逻辑；旧单 `tags=[]` | 旧单 transcript 缺失见缺口 |
| 6 | 侧栏按项目分层；工单可删且保留知识/交付件 | 已实现 | 项目页、`tickets.delete` 仅 closed；`gitflow.ticket_remove` | — |
| 7 | 工单群聊内联模块报文，删除“链路”页 | 已实现 | `webchat._module_timeline`；`details.modgroup` 折叠；无 trace tab | 只保留最近 60 条，无“更早”入口 |
| 8 | PM 编排支持并行；悬浮改点击 | 已实现 | `flow.parallel_stage.branches`；节点/分支点击弹详情 | — |
| 9 | 压缩秘书上下文移到项目面板并标明对象 | 已实现 | 项目页“压缩本项目秘书上下文”；`sec-<p>` | — |
| 10 | 复核流程是否真可插拔并给示例 | 已实现 | 角色卡 + 流程插件 + 技能；`library.design`；文档示例 | 校验规则已增强，仍以 glob/内容为主 |
| 11 | 项目/agent 文件系统只读浏览；git 取舍 | 已实现 | `/api/projects/{p}/files`、`/api/ops/files`；只读 | 不做网页直接改配置 |
| 12 | 本机仓库移到 `E:\AI` | 已实现 | Windows `E:\AI\hive-agent` | — |
| 13 | 推送 GitHub 远端并验证 | 已实现 | `git@github.com:cmWF29/AI-agent.git`，main `b268899` | 后续提交需再同步 |
| 14 | 工单分支 push/pull；冲突由 git 解决，冲突后必须重验 | 已实现 | `gitflow.sync/merge`；冲突置 `conflict`；`ticket_verify` 硬门禁 | 复验命令由 PM 执行，非自动跑测试 |
| 15 | PM 先了解项目，简单活自己干 | 已实现 | `PM_TOOLS` 含 shell/read/write；PM 提示词 | — |
| 16 | 3 项目 × 3 工单并发 + 冲突演练 | 已实现 | v3 实测数据；`test_three_by_three` | 未做持续压测 |
| 17 | HTTPS 加强安全 | 已实现 | 自签 TLS；CSP/HSTS/X-Frame-Options/nosniff；登录限流 | 证书仍自签；单用户无 RBAC |
| 18 | 秘书架构：一个项目一个秘书 | 已实现 | `sec-<project>`；全局 `secretary` | — |
| 19 | 三层架构中“本地层”是否必要 | 已决策 | 结论：单部署=单本地层，不展示；见架构审查 | 多节点部署未做 |
| 20 | 项目可删除，后处理只清秘书会话 | 已实现 | `projects.delete`；保留工单/交付件/知识 | — |
| 21 | 交付件按三层归档且路径带工单号 | 已实现 | `artifacts/projects/<p>/tickets/<T>/...` | 归档会把工作树已有文件一起带入 |
| 22 | 结单后销毁 PM/角色会话，群聊只读 | 已实现 | `_do_close` destroy；`message` 410；`readonly` | 历史单会话早已销毁，只能回放 transcript |
| 23 | 群聊发言人：用户=“我”，角色=角色名，头像 | 已实现（v4.1 修正） | `user_messages` 标记；`_session_chat` 区分我/秘书/PM→角色；首字母头像 | 头像是字母+稳定色，不是真人/随机图片 |
| 24 | 群聊顶层“系统”消息是什么，应 agent→PM→角色 | 已实现（v4.1 修正） | 系统注入消息以“（系统）”开头，群聊过滤；kickoff 显示秘书→PM | 历史 transcript 中旧系统消息无法追溯过滤 |
| 25 | 工单生命周期流程图与群聊分离 | 已实现 | `flow` 独立条；节点含冲突/复验/归档/合并 | — |
| 26 | Markdown 渲染 | 已实现 | `web/app.js md()`：标题/列表/表格/代码/引用/链接 | 非完整 CommonMark（嵌套列表、HTML 不支持） |
| 27 | “流程专家”角色拆提示词/技能/流程插件 | 已实现 | `process` 内置角色；`flow_design`；`library.design` | 无独立“流程专家”会话 UI，由 PM 调工具 |
| 28 | 流式显示，可判断卡住/死循环并打断；不要超时 | 已实现 | `live` 轮询 partial；`interrupt`；LLM 无总超时 | 是轮询不是 SSE/WebSocket |
| 29 | 项目/公共交付件、角色库/流程库/技能库 | 已实现 | 交付件侧栏三层；库页面三个 tab + 标签库 | 库是弹窗，不是独立页面 |
| 30 | 工单号可复制、可基于老单新开、知识沉淀因果 | 已实现 | `btn-copy-ticket`；`btn-fork-ticket`；`parent` 写知识摘要 | — |
| 31 | 全链路透明：LLM 请求/响应、tool、模块 API、总线、角色通信 | 已实现 | trace → 模块报文；群聊可点完整 JSON | 60 条上限；完整 trace 需 SSH/文件 |
| 32 | 健康自检含交付件体积；压缩存储 | 已实现 | `/api/health/self`、`artifacts.stats/compress` | 压缩是归档压缩，不是在线去重 |
| 33 | 前端返回键、刷新恢复、完整状态转移图 | 已实现（v4.1 新增） | hash 路由 + `popstate` + `←` + Esc；`docs/ui-state-machine.md` | 侧栏/临时弹窗不占历史（有意） |

## 第一批 11 条的补充说明

1. **PC 收起**：`body.rail-collapsed` 隐藏整栏，PC 折叠状态持久化；安卓是 `rail.open` 抽屉 + 遮罩。点项目/工单会自动关抽屉，不再遮挡聊天。
2. **空闲排队**：`peak_windows`、`peak_days`、`holidays`、`utc_offset_hours` 可配；VPS 是 UTC，判断用东八区，避免错 8 小时。工单与消息分别入队，空闲线程消费。
3. **本地层**：行业上“本地层”通常指部署边界/设备侧执行环境；本系统只有一个部署（VPS）+ 一个浏览器，多本地层没有第二个执行体，所以不做展示与多实例。
4. **tag**：用户 UI 可增删；PM/角色用 `ticket_tag`；沉淀到 `public.json` 与 `projects/<p>.json`。
5. **历史单**：不迁移、不回写；旧单只读展示。
6. **侧栏**：只保留项目 + 全局秘书；项目内再分管理/工单/秘书/新建/文件/交付件。删除工单只允许 closed，删记录+工作树+临时分支，保留 artifacts/knowledge。
7. **模块报文**：LLM/工具/模块 API/总线/agent 通信都进群聊，按连续段折叠；点开看完整 JSON。独立“链路”页删除，后端 trace 保留。
8. **并行**：`parallel_stage.branches` 显示角色并行 lane；节点、分支、模块消息全部点击，无 hover 依赖。
9. **压缩**：按钮在项目页，明确压缩 `sec-<project>`。
10. **流程插件**：角色卡 + flows `checks` + `max_retry`；`session_result` 与结单前双校验；缺件自动催。示例见 `docs/v4-changes.md`。
11. **文件系统**：项目 main 树 + agent 源码/配置只读；配置修改仍走 git，保留审计与回退。

## 第二批 19 条的补充说明

- **GitHub**：Windows 本机 `E:\AI\hive-agent` 为镜像，remote `github` 指向 `cmWF29/AI-agent`；VPS 是部署权威，vm 是开发权威。
- **冲突机制（v4.1 强化）**：push 或 merge 冲突时工单进入 `conflict`，写入 `reverify.required=true`；PM 必须解决冲突、重跑测试并调用 `ticket_verify(summary, commands, result)`，否则 `ticket_close` 返回 409 `reverify_required`。这比“发消息提醒”更硬。
- **群聊口径（v4.1 修正）**：用户本人发言显示“我”；PM 收到的用户消息不再伪装成“秘书→PM”；`（系统）` 开头的续跑/催补/冲突提示不进入群聊；PM 派活显示“项目经理→角色”。
- **流程校验（v4.1 强化）**：除 glob 外支持 `min_bytes` 与 `contains`，空文件/占位文件不能骗过“架构师必须输出架构文档”。
- **返回键（v4.1 新增）**：hash 路由 `#/project/<p>`、`#/chat/<id>`、`#/library/...`、`#/health` 等；刷新恢复；`←`/Esc/浏览器返回统一优先级；深链不存在时提示回根。

## 测试证据

`python3 tests/run_all.py` → **185/185**，覆盖：

- 内核/总线/输出策略/ReAct/打断/秘书压缩
- 工单生命周期、结单只读、交付件三层、删除保留证据
- 多项目并发、3×3、冲突状态
- 空闲排队、tag 双层沉淀、项目文件树、模块报文、并行流程
- 安全：越界路径、CSP/X-Frame/nosniff、登录 5 次限流
- 群聊发言人/系统消息过滤
- 流程插件空文件拦截、复验硬门禁
- HTTPS 自签与业务接口
- 前端契约：返回按钮、hash 路由、popstate、无链路 tab、状态机文档存在

## 未完成/明确不做

| 项 | 说明 | 计划 |
|---|---|---|
| 日历接入 | 当前 `holidays` 手工配置；法定调休未自动拉取 | P1，接日历后只改 idle 模块 |
| 模块报文 60 条上限 | 避免淹没角色发言；完整记录在 trace 文件 | P2，可加“查看更早”分页 |
| 历史 transcript 为空 | 早期工单关闭时未冻结，只能靠 trace 模块报文兜底 | 按“历史不动”不迁移 |
| 群聊真实流式 | 当前 900ms 轮询 partial，不是 SSE | P1，如需更低延迟可换 SSE |
| 网页直接改配置 | 明确不做，配置走 git | 保持 |
| 头像图片 | 当前首字母+稳定色，不依赖外网 | P2，可换本地随机头像集 |
| RBAC | 单用户密码 + token，没有多用户权限 | 明确不做（个人系统） |
| 多本地层 | 单部署无第二执行体，不做 | 保持 |

## 验收建议（早上按这个点）

1. 打开 `https://104.168.148.112:8787/`，确认顶栏有 `←`，进项目/工单后出现，回根后消失。
2. 在工单页刷新，确认仍在同一工单；分享 `#/chat/<T-id>` 链接能直接打开。
3. 安卓按物理返回：先关弹窗/侧栏/抽屉，再回项目页，再回根。
4. 新开一张带 tag 的工单，群里发一句“我”的话，确认发言人显示“我”，系统提示不混入。
5. 打开库/健康/版本/源码，确认关闭后回到原页面。
