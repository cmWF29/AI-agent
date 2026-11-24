# 技术细节

本文是《技术方案原理》的实现说明：模块边界、数据形状、调用顺序、状态迁移、并发与失败处理、门禁口径、配置和已知限制。只写问题与约束，不复制源码；需要定位时写文件/模块/符号名。

## 1. 模块边界

| 层 | 目录 | 职责 | 不做什么 |
| --- | --- | --- | --- |
| 公共能力 | `ai_new/modules/agent_common` | store、api、runtime、react、react 循环、archive、codec、host、net、exec | 不认项目/工单业务 |
| 业务能力 | `ai_new/modules/agent` | sessions、tickets、projects、todos、library、cloud、nodes、web、logs、artifacts | 不互相 import 私有实现 |
| 装配与需求 | `agent_common/demand_engine` | 需求 YAML、顺序调用、效果清单 | 不写业务判定 |
| 验收 | `ai_new/modules/agent_test` | 单元、契约、系统用例 | 不复制业务实现 |
| 门禁 | `scripts/gate_*.py`、`scripts/verify_*.py` | 静态、浏览器、覆盖率 | 不放行业务代码 |

约束：能力模块只通过 `ctx.api.call/acall` 暴露的路由协作；纯函数不读盘、不取时钟；有副作用的动作由需求层收口成 effect，再由 runtime 落地。

## 2. 关键数据模型

### 2.1 会话记录

会话记录包含 id、kind、role、project、ticket、status、messages、summary、meta、todos、steps、result。

- `messages` 是存档全量，前端回溯和原文回查都靠它；
- `summary` 是跨轮滚动摘要，发模型时替代历史原始往返；
- `meta.machine` 是流程契约快照，`meta.active` 是并行活跃集合，`meta.stage` 是当前阶段；
- `meta.checklist` 保存本轮已交项和违规项，`meta.gate_alert` 保存被拦下的缺项/红线；
- `meta.last_error` 保存后端未答复、启动中断等失败痕迹。

状态迁移：`idle → queued → running → idle`，异常时 `running → stalled/idle`。`running` 残留由启动续跑或停滞扫描回收；回收只复位状态并留错误码，是否重跑由编排决定。

### 2.2 流程契约

契约包含 `initial`、`by_id`、`states`、`terminals`、`checks`。每个状态可有 `cn`、`desc`、`next`、`terminal`、`tools`、`gate.must`、`gate.forbid`、`checks`。

状态路径支持嵌套子流程展开；`by_id` 的键是展开后的路径，邻接表也按路径连接。项目覆盖层只覆盖允许的动态节点，内置保护节点不允许删除。

### 2.3 清单条目

条目形状：`id`、`text`、`status`、`note`。`status` 归一为 pending/doing/done；未知值按 pending。`todos.max_items` 是硬上限，配置缺失或为 0 时清单必须为空，不能“先塞一条再判断超限”；查询、只带 id 的 update、内容相同的 replace 都不产生会话补丁，只有真实字段变化才落盘。

### 2.4 协调台账

节点台账包含节点注册、角色/项目归属、租约、迁移记录。租约字段至少包含 holder、epoch、expires_at；节点心跳只续租，不直接改归属。所有变更走 CAS，读到旧版本后重算再提交。

### 2.5 云端 manifest

manifest 是远端权威清单，形状为版本、profile、更新时间、entries。每个 entry 至少包含摘要、大小、类别、修改时间。manifest 不含自身前缀对象，避免自我引用。上传对象键由 profile 与相对路径决定。

## 3. 关键数据流

### 3.1 一轮会话

1. 读会话记录、流程契约、阶段工具白名单、待办上下文；
2. 刷新流程约束消息、注入已分派岗位，标记 running 并落盘；
3. 调 ReAct：构造上下文视图（system + 滚动摘要 + 最后用户指令 + 待办注记）；
4. 模型返回工具调用则并发执行工具，按原顺序回填；工具输出超限先落日志只回路径；
5. 收口步解析 reply/summary/stage/checklist/violations；
6. 校验状态迁移：目标存在、边可达、must 交齐、无违规、源状态交付件达标；
7. 写回会话与状态机，触发 finished 钩子做校验/回催/复盘。

失败处理：后端未答复不写半截消息；工具报错作为观察结果回给模型；检查点失败不掀翻整轮；收尾仍整段落盘。

### 3.2 前端渲染与点击

1. 后端 `views-list` 给出页面、参数、区块、表单、动作、状态机；
2. 渲染层按原语生成 DOM，动作按钮统一带 `data-clk`、`data-act`、`data-ctl`、`data-ctl-state`；
3. 点击进入页面级 click machine，合法则执行动作；控件状态走 idle→busy→done→idle；
4. 动作可打开弹窗、跳视图、提交需求或只改本页显示；浮层必须有取消/遮罩关闭路径；
5. 可点实例清单由真实 DOM 扫描生成，源码签名变化后必须重扫，否则门禁红。

### 3.3 云端同步

1. 读远端 manifest；不可达/损坏时回退本地缓存并标记来源，不把缓存冒充权威；
2. 本地扫描（含 archive 压缩索引）与上次推送、远端现状做三方差分；
3. 上传新增/变更对象，失败按指数退避重试，断点状态原子落盘；
4. 全部成功后写 manifest；写失败不更新本机已同步缓存，下一轮只补 manifest；
5. 本地删除形成待删清单；未显式 prune 时返回 prune_required 并阻止 manifest 更新；
6. 显式 prune 才删除远端对象，删除失败单独记账，不把部分成功当全部成功。

### 3.4 隔离执行

1. store 计算当前 workload 的 sandbox 描述：根、工作目录、bind 白名单；
2. exec 校验 bind 源和目标都在允许范围，拒绝根 `/` 和跨工单路径；
3. 用独立 mount namespace 启动进程：只读挂载系统目录、tmpfs 临时目录、bind 白名单、设置工作目录；
4. 进程退出 namespace 销毁；bwrap 缺失或描述不完整时显式 sandbox_unavailable，不静默降级。

### 3.5 HTTP 入口与静态资源

1. 方法闸：GET 只放行 `/api/health*`、`/api/modules`、`/api/auth/status`、`/api/auth/verify` 和 `/api/sse/*`；其余 `/api/` 写路由必须 POST，GET 对已知写路由回 405 `method_not_allowed`，未知路由回 404 `no_route`，形状不对回 404 `bad_path`，避免带 Cookie 的链接/图片触发删除或归档。
2. 匿名 allowlist：仅存活探针、登录状态、登录换票/校验，以及 `demand_engine.run` 的 `auth-login`、`console-chrome` 两个壳需求；新增 auth 前缀路由不会自动公开。
3. 请求体：先拒绝 `Transfer-Encoding`（400 `bad_framing`，并关闭连接），再校验 `Content-Length` 为正整数且不超过 `server.max_body_bytes`（默认 8 MiB），超限 413 `payload_too_large`；不把超限正文读进内存。需求入口要求 `id` 为非空字符串、`input` 为对象，否则 400 `bad_id`/`bad_input`，不让数组/对象进入路由表查找。
4. 静态资源：`web.gate` 只匿名放行 `login.html` 与 css/js/svg/图片/字体；json/yaml/md 等可能含配置或正文，和页面一样要求登录，未登录 302 到登录页。
5. 所有响应统一带 `X-Content-Type-Options: nosniff`、`X-Frame-Options: DENY`、`Referrer-Policy: no-referrer`。

## 4. 状态迁移表

### 4.1 流程

| 当前 | 事件 | 条件 | 结果 |
| --- | --- | --- | --- |
| 空 | 上报初始态 | 等于契约 initial | 进入初始态 |
| 空 | 上报非初始态 | 任意 | illegal_start，保持空 |
| A | 上报 A | 任意 | 原地停留，活跃集合不变 |
| A | 上报 B | B 在 A.next，must 交齐，无违规，A 交付件达标 | 离开 A，B 并入活跃集合 |
| A | 上报 B | 边不存在 | illegal_edge，保持 A |
| A | 上报未知态 | 任意 | unknown_stage，保持 A |
| A | 上报 B | must 缺项 | checklist_unmet，保持 A，返回缺项 |
| A | 上报 B | 有 forbid 命中 | forbidden_hit，保持 A，返回违规 |
| [A,B] | 上报 C | C 由 A 或 B 可达 | 当前态离开，兄弟保留，C 并入 |
| 终态 | 未上报 | 任意 | unset，活跃集合保留，等待收口 |

### 4.2 控件

| 状态 | 触发 | 结果 |
| --- | --- | --- |
| idle | 合法点击 | busy |
| busy | 动作完成/失败 | done |
| done | 240ms 后 | idle |
| disabled | 任意 | 无出边，终态 |

页面级状态另有 idle/busy/modal/swallow；被吞掉的重复点击只吞一次，不永久禁用页面。

### 4.3 会话

`idle → queued → running → idle`；running 超时或进程重启进入 stalled/idle，带 interrupted_on_boot 或 stuck_missing_task。归档/结单后只读，composer 与结单控件一起 disabled。

会话令牌只允许 `[A-Za-z0-9_-]`（1–128 字符），令牌拼进 `sessions/{token}.yaml` 前先校验；缺少 `expires`、`expires` 非数字或已过期一律按无效处理。空用户名/空摘要/空期望哈希也按凭据失败处理，摘要比较用常量时间。令牌来源按入口分开：请求头、Cookie 全局可用；query 参数只给 `/api/sse/` 用——EventSource 不能设请求头，普通 API 收 query token 一律当未登录，避免令牌写进访问日志、Referer 和浏览器历史。


## 5. 并发与一致性

### 5.1 CAS

- 读当前值 → 深拷贝 → 回收过期租约 → 纯函数变更 → 比较期望值后提交；
- 冲突重读重算，最多 8 次；超过返回 conflict_exhausted，不覆盖；
- 首次创建用 create=true，期望旧值不存在时允许写入；
- 冲突返回当前值，调用方可决定重试或放弃。

### 5.2 租约与 fencing

- 租约到期即使节点 alive 也释放；
- 接手时 epoch+1；旧 epoch 的写请求拒绝；
- 只读视图不暴露 token；
- 迁移记录随状态一起 CAS，进程重启不丢。

### 5.3 幂等

- 重复投递按业务键 claim，处理中拒绝双跑，完成后 settle；
- 会话同工单同岗已有在途时复用，不新建；
- 云端对象按摘要比对，相同内容跳过上传；
- 工具输出落盘失败回退全文，不把假路径交给模型。

### 5.4 边界 fail-closed

- 鉴权：非法令牌不进入路径拼接；会话过期/缺过期字段直接拒绝；摘要空值不放行；登录 ttl 非正回落 86400，不发“出生即过期”的会话；改密要求期望摘要与旧摘要都非空且常量时间相等。
- 沙箱：bwrap 的 cwd 与 bind 目的地按 POSIX 归一化并拒绝 `..`，bind 源先校验在项目根内再创建目录；
- ASR：分块采样点数必须为正整数，配置缺失/为 0 返回 `bad_chunk_config`，不允许进入不前进的循环；
- 静态资源：只有 `login.html` 与无数据壳资源公开，json/yaml/md 等数据文件和其他 HTML 页面必须登录。
- HTTP：GET 只读、匿名 allowlist、请求体上限、chunked 拒绝，细节见 3.5；GET 写路由只对“存在但只收 POST”的路由回 405，未知路由回 `no_route`、形状不对回 `bad_path`，不把拼错路径误导成换动词。

## 6. 压缩与上下文

发模型上下文只保留：

1. 全部 system 消息（人设、流程约束、阶段、待办）；
2. 一条滚动摘要（assistant 角色，kind=summary）；
3. 最后一条 user 指令；
4. 本轮 ReAct 新增的 assistant/tool 往返。

不在上下文里的历史原文仍保留在存档 messages 里，供前端回溯和原文回查。滚动摘要来源：

- 模型交 summary：直接采用，`summary_by_model=true`；
- 模型未交：系统按 `sessions.summary_fallback_chars` 把本轮工具调用与结果压成兜底摘要；
- 拼完旧摘要与兜底正文后仍超上限：整段截断并加省略号；
- 没有工具往返也没有模型摘要：保留旧摘要，不清空。

## 7. 前端信息架构

- 网格卡：标题、状态徽标、工单统计、最多两行 meta、动作；路径/创建时间/最近详情进项目详情。
- 堆叠卡：一屏一张，展开后铺平；每张卡保留配置字段，但长说明进详情。
- 区块说明：一行，只讲数量或当前状态，不复述标题。
- 帮助：长说明、示例、原理放说明按钮、浮窗、抽屉或详情页；入口必须可打开、可关闭、可返回。
- 品牌：纯色标识，不用渐变、发光、装饰阴影。

## 8. 门禁与测试矩阵

| 层 | 门禁/用例 | 证据 |
| --- | --- | --- |
| L0 静态 | controls、screens、inventory、views、card_size、copy、frontend、wiring、docsync、levels、ops、deadcode | 规格与源码双向闭合、活 DOM 清单、文案长度、信息预算、文档哈希 |
| L1 单元 | 核心、架构、需求、装配、传输、幂等、桩、隔离、节点、分布式、归档、秘书、定时、角色门禁、技能拆解、React 机制、边界 fail-closed、HTTP 入口 | 纯函数断言、状态迁移、并发、边界、GET/匿名/请求体/静态资源闸 |
| L2 契约 | 非法输入、鉴权、越权、穿越、幂等 | 真装配 + 真 HTTP |
| L3 E2E | verify_ui、verify_e2e、verify_pages、verify_controls | 真浏览器 + 真后端；业务闭环、全页可达、全表单可开、安全控件真点击 |
| 覆盖率 | gate_coverage / gate_diff_coverage | coverage data + 行 ≥80.0%/分支 ≥67.0%/关键模块 80.0%·65.0%；base..HEAD 新增产品代码行单独 ≥90% |
| L4 韧性 | 中断恢复、租约、重复投递、恢复不双跑 | 真实子进程 SIGKILL + 真实文件锁台账 |

新增测试放置：纯函数/状态机进 `agent_test/private/test_*.py`；契约探针进 `scripts/lib/layers/l2_contract.py`；浏览器用例进 `scripts/verify_*.py`；静态规则进 `scripts/gate_*.py` 并登记 L0。新增测试必须登记 check 与模块，否则需求↔用例映射门禁红。

## 9. 配置与错误码

关键配置：`server.max_body_bytes`、`sessions.max_steps`、`sessions.result_chars`、`sessions.summary_fallback_chars`、`sessions.summary_keep`、`sessions.context.tool_output_chars`、`sessions.react_cap`。

常见错误码：`illegal_start`、`unknown_stage`、`illegal_edge`、`checklist_unmet`、`forbidden_hit`、`condition_unmet`、`conflict_exhausted`、`lease_expired`、`sandbox_unavailable`、`crypto_unavailable`、`manifest_unreachable`、`prune_required`、`write_failed`、`no_route`、`bad_path`、`bad_id`、`bad_input`、`method_not_allowed`、`payload_too_large`、`bad_framing`、`bad_old_password`。

错误码要能被前端或调用方分支处理；不允许只给自然语言 error 而没有 code。

## 10. 运维与观测

- 健康检查：live/self，模块数、需求数、hook 点闭合；
- 日志：按项目/工单分层，工具大输出落 ticket 层，事件与审计分开；
- 指标：压缩量、解压分位、缓存命中、节点归属、租约剩余；
- CI：静态门禁 → 全量用例（coverage）→ 覆盖率门禁 → 改动行覆盖率门禁 → L2/L4 契约与韧性 → 真浏览器回归；
- 失败日志写 job summary，保留尾部便于定位环境差异。

## 11. 已知限制

- Windows 强隔离未落地，只有路径档；
- 跨 VPS 协调台账需要共享文件系统或远端协调服务，当前未验；
- 对象存储没有条件写，计划到上传之间有竞态；
- 云端删除要显式 prune，默认不删共享远端对象；
- node_worker 仍是命令式桩执行体，不是实际任务工作进程；
- bwrap 没有 seccomp/cgroup，保留共享网络，未挂 `/proc`；
- 覆盖率已按 base..HEAD 强制改动行 ≥90%；只对产品 Python 新增行计数，测试与文案改动不虚增分母；
- 登录失败尚无跨进程速率限制/账号锁定；在线撞库防护是下一层，当前只有令牌随机性与会话过期；
- 客户端在响应写完前断开时，HTTP handler 仍可能把 `BrokenPipeError` 打到 stderr；连接已关闭、无数据风险，但日志噪声要在下一轮收口；
- 前端视觉回归覆盖页面可达和关键交互，不等于像素级设计稿比对。

这些限制必须在发布说明里保留，不能因为门禁绿了就当成能力已经完整。
