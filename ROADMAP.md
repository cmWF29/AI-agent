# 后续迭代路线：先 trace，再数据库

前置口径（本文件按此写死，不再讨论）：**需求 DSL 只允许顺序流**，只有 `call` 与 `send`；分支、循环、等待、重试、补偿全部放在模块功能函数内部。控制的扩展方式不是"加原语"，而是"加静态禁令闸 + 把控制流赶回模块"。因此本轮不做任何 DSL 语法扩展。

## 一、顺序与依赖

```
P0 trace（可观测）  ──►  P1 数据库（存储与并发）  ──►  P2 安全/评测/生态/部署
        │                       │
        └── 先知道慢在哪、错在哪，才知道该给哪些表建索引、哪些路径要批量化
```

顺序不能反。数据库先上，等于在没有观测的情况下猜索引和事务边界；trace 先上，才能用真实链路回答"哪些写该合并成一次事务、哪些读该走索引"。

## 二、P0：trace（2–3 周量级，按商用最小可用做）

**目标**：任何一次用户可见的动作（一次 HTTP 请求、一条 hook 派发、一次会话回合、一次工具调用）都能顺着一条 `trace_id` 查出完整调用树、每步耗时、token/成本、错误与重试。

**最小设计**

- **身份传播**：`trace_id`（一次外部请求/一条事件源）+ `span_id`（一次调用）+ `parent_span_id`。入口生成：HTTP 中间件、`demand_engine.run`、hook dispatch、`runtime` 定时扫描。传播靠 `contextvars`（与 `_SCOPE` 同法），跨通道时随报文带上（`_wire` 报文已有 `v` 字段，加 `trace` 字段即一次兼容升级）。
- **埋点位置**（只在这些地方打，不散落）：`api` 的 `call/acall`（路由、耗时、payload 摘要、错误码）、`demand_engine`（需求 id、语句序号）、`react`（回合、工具轮）、`llm`（模型、token 用量、首字节延迟、流式总时长）、`net`（出站请求）、`sessions`（spawn/finish）、`tickets`（阶段推进）。全仓目前 trace 埋点是 0，这七个点覆盖主要链路。
- **存储**：`ops` 模块管（日志已归它）。`data/logs/trace/<date>/<trace_id>.jsonl`，一行一个 span（`{span, parent, name, start, dur_ms, attrs, err}`）。与 `app.jsonl` 分开，避免把审计日志和性能数据搅在一起。
- **采样与开销**：默认全采（当前量级撑得住），加 `trace.sample` 配置按比例降采样；单 span 只允许标量属性，大对象只存摘要（复用 `codec.sha`）。
- **查询与呈现**：`trace.list` / `trace.get` / `trace.slow` 三个能力路由；控制台加一个 `view-trace` 规格（时间线 + 瀑布图 + 慢查询榜），**由视图规格驱动，前端不写死任何 trace 业务词**。

**验收闸**

- 一次 HTTP → 需求 → 会话 → 工具 → LLM 的链路，`trace.get` 能还原完整树，层级和耗时自洽（子 span 总时长 ≤ 父）。
- 跨通道（unix/tcp/shm）调用不丢 `trace_id`。
- 关闭 trace 时零额外文件写（开关可验证）；开启时 p99 延迟增幅 < 5%。
- 慢查询：能列出 top-N 最慢路由与最慢需求，字段可下钻到 span。

**为什么它是 P1 的前置**：数据库要建哪些索引，只能由 `trace.slow` 的真实热点决定。

## 三、P1：数据库（SQLite 起步，不直接上 Postgres）

**目标**：把"并发正确性"和"全量扫描"两件事从业务代码里拿掉，而不是换个存储。

**先收四张表，别多想**

| 表 | 解决什么 | 迁自 |
|---|---|---|
| `idem` | 幂等占位与结果复用（见幂等键方案） | 文件 `idem/` |
| `seq` | 单一序列分配器（`channel` 撞号、`sessions` 无号） | `store.next_seq` 进程内计数 |
| `messages` | 频道消息按 `(ticket, seq)` 索引，消灭 `since` 全量读 | 频道消息 yaml |
| `sessions` | 会话按 `(ticket, role, state)` 索引，消灭 spawn 前的 glob 扫描 | 会话目录 |

**实现约束**

- WAL 模式 + `busy_timeout`；写走单连接队列（一写多读），避免 SQLite 写锁抖动。
- 数据库仍然是 `store` 的能力（`store.db_*` 或独立 `sqlite` 能力模块），业务模块不许 `import sqlite3`——沿用现有"stdlib 收编"闸。
- **文件仍是事实来源**：先双写（文件 + 表），读路径按开关切表，校验一致后停写文件。回滚只需切开关。
- 需求 DSL 不变：`call store.xxx` 还是那一条顺序语句；事务边界由能力内部封装（`store.tx` 只保证单次调用内的多写原子）。

**验收闸**

- 两个进程各投 1000 条消息：`seq` 无重复、无空洞、无丢失。
- spawn 判断从 O(n) 变 O(1)，1000 会话下延迟 p99 下降一个量级。
- 双写期间文件与表逐条比对一致（抽样 + 全量各一次）。
- `PRAGMA integrity_check` 通过；进程 kill -9 后重启数据可读。

## 四、P2：数据库之后的事（按收益排序）

1. **安全**：HTTP 入口限流（按 token/IP）、写路由 CSRF 防护、审计记录带上 `trace_id`（P0 已给出现成字段）、`tcp` 通道绑定可配（现在只绑回环）。
2. **评测**：`expect` 现在只到契约层（调了谁、传了什么）。补两层——任务层（golden set：输入 → 期望产物结构）、质量层（judge：用固定 prompt + 固定模型给产物打分，结果入库可对比）。评测必须能进 CI，否则会腐化。
3. **规模**：全仓 12 处 `store.glob` 全量扫，P1 后逐个换成索引查询；`knowledge` / `logs` 的检索加倒排或向量（先倒排，够用再说向量）。
4. **生态**：MCP 客户端（把外部工具当 `tools.register` 的一种来源），以及把现有路由暴露成 MCP server。这是"能力外接"的自然延伸，但要等 trace 能看见外部调用的耗时。
5. **部署**：CI（跑现有 6 组验收）、lint/类型检查（先 `ruff` + `mypy --ignore-missing-imports` 的窄集）、容器化（Dockerfile + 健康检查）、灰度（两个端口并行跑，按 trace 对比错误率）。

## 五、遗产清理（与主线并行的低成本项）

- **跨模块直调台账回收**：`internal-calls.yaml` 现在登记 14 个业务 caller，是"合法化"不是"修好"。方向是把这些直调逐条迁成"能力产 effect + 需求 apply"，台账只减不增；每减一条，`enforce` 就是一次证明。
- **平台匿名身份**：`platform:anonymous` 是装配期唯一没名字的调用方。给它一个具体组件名（`platform:boot`），让"匿名"从系统里消失。
- **文档闸**：已加（`test_architecture.TestDocsMatchImplementation`），文档里出现已下线概念或模块清单与目录不符即红。以后每次改架构，文档和代码一起过闸。

## 六、里程碑与判定

| 阶段 | 完成标志 | 判定方式 |
|---|---|---|
| P0 完成 | 一条链路端到端可查，慢查询榜可用，跨通道不丢 trace | `trace.get` 树自洽 + 延迟增幅 < 5% |
| P1 完成 | `idem/seq/messages/sessions` 四表接管，glob 热点消失，并发无撞号 | 双进程压测 + 一致性比对 + integrity_check |
| P2 起步 | 限流/CSRF 上线，golden set 进 CI，首批 glob 换索引 | 安全用例 + CI 红灯能拦住回归 |

下一步动作只有一个：先落地 trace 的身份传播与七个埋点，把"看得见"这件事做完，再谈表。
