# 幂等键与持久化执行：方案

面向 AI_NEW 现状（文件即库、需求顺序编排、hook 派发、多线程 + 协程池）写的落地方案。不引入 Temporal 这类外部引擎，先把"同一件事只生效一次"这件事在本仓做对。

## 一、一句话结论

幂等键不是"防重复的 if 判断"，而是**给每个副作用一个稳定的身份，并把"谁负责执行这次副作用"写成一条可恢复的持久记录**。它的价值有三层：拦住重投、拦住崩溃重放、拦住并发双击；更深一层是让系统在"执行到一半进程死了"之后，知道该继续、该放弃、还是该报警，而不是盲目重来。

## 二、它到底在解决什么问题

重复副作用只有三个来源，方案必须三个都覆盖：

1. **上游重投**：HTTP 客户端超时重试、SSE 断线重连、需求被手动再 run 一次。同一个意图到达两次。
2. **崩溃重放**：`channel.posted` → 需求 A → 建单 → 进程在"建单已落盘、hook 已消费标记未落盘"之间挂了。重启后事件被重新派发，单子建了第二遍。
3. **并发双击**：两个线程/两进程同时处理同一工单同一岗位（`tickets` 里已有"同工单同岗重复触发"的判定，但那是业务启发式，不是通用机制）。

对应的三种语义要分清，混用会写出"看起来幂等其实丢活"的系统：

| 语义 | 含义 | 本仓能不能直接做到 |
|---|---|---|
| at-most-once | 最多一次，失败也不重试 | 能，但会丢活，不适合业务副作用 |
| at-least-once | 至少一次，可能重复 | 现状就是这个（事件重放、重试） |
| effectively-once | 至少一次投递 + 去重 + 结果复用 = 业务上只生效一次 | **目标**，靠幂等键实现 |

## 三、底层原理：五个机制，缺一不可

### 1. 键必须有稳定来源

两种生成方式，最好都支持：

- **显式键**：调用方带 `idempotency_key`（HTTP 头、RPC 字段）。适合外部客户端重试。
- **派生键**：由"业务事实"算哈希，不依赖调用方配合。这是崩溃重放唯一靠得住的方式，因为进程死之前根本没机会把键传到下游。

派生键的组成必须是**事实**，不是随机数、不是时间：

```
key = sha256( route | scope | 业务锚点 )
例：channel.posted 派发 → sha256("channel.posted|tickets|<ticket_id>|<posted_seq>")
    会话 spawn        → sha256("sessions.spawn|<ticket_id>|<role>|<stage>|<attempt_no>")
    工单创建          → sha256("tickets.create|<project>|<demand_id>|<input_digest>")
```

要点：锚点里要带"第几次"（`attempt_no`）而不是时间戳，否则重放算出来的键不一样，去重表形同虚设；反过来，如果是"用户真的想再来一次"，就必须换锚点（比如新的一轮 `round_no`），否则会被正确地去重掉——这是**语义问题**，不是实现问题，必须由业务纯函数决定。

### 2. 占位必须是原子的、独占的

去重的核心动作只有一句：**"插入键"必须能失败**。

- 文件版：`os.open(path, O_CREAT | O_EXCL)` 创建 `<key>.claim`，成功=我拿到了执行权；已存在=别人拿过，去读它的状态。
- SQLite 版：`INSERT ... ON CONFLICT DO NOTHING` + `PRAGMA journal_mode=WAL`，靠唯一约束而不是应用层判重。
- `store.write` 的原子替换（`mkstemp` + `os.replace`）**不能**拿来占位——替换永远成功，覆盖掉别人的记录，去重就没了。所以要么新增 `store.claim`（独占创建）原语，要么在模块里用文件锁 `flock` 包一层。前者更符合"能力收编"的哲学。

### 3. 状态机，而不是布尔值

一条记录至少有五个状态，缺一个就会在崩溃时判错：

```
claimed ──执行中──> running ──成功──> done(result_digest, result)
   │                    │
   │                    └──失败可重试──> failed(attempt, error)  → 可再次 claim（attempt+1）
   └──租约超时无人接──> abandoned                          → 交人工/告警，不自动重跑
```

- `done` 之后再来同一键：**直接返回缓存结果**，不再执行。这是"结果复用"，也是幂等对用户可见的那一半。
- `failed` 且错误被分类为"可重试"（网络超时、上游 5xx、临时锁冲突）：允许再 claim，`attempt+1`，带上限。
- `running` 且租约未过期：后来者**等待或直接返回 in-flight**，不许并行执行。
- `running` 但租约过期（进程死了）：进入恢复扫描。此时要不要重跑，取决于这次副作用是否"已部分生效"——所以执行体必须把"外部可见的写"尽量收敛到一次原子落盘，或者自带可判定的痕迹（如工单里已存在该 stage 的记录）。判不出来就 `abandoned` + 告警，宁可人工看一眼，也不要悄悄跑第二遍。

### 4. 租约（lease）而不是锁

分布式/多进程下，"谁在跑"必须有时限。记录里写 `lease_until = now + lease_seconds`，执行中定期续租（心跳）。进程死了就没人续，租约自然过期，恢复扫描才有依据。纯文件锁（flock）在进程被 kill 时会随 fd 释放，这很好，但它只能保护"同一台机器上的同一时刻"，跨进程重启后的"上次跑到哪了"仍然要靠记录本身。

### 5. 结果要可复用、可校验

`done` 记录里存 `result_digest`（结果的稳定摘要，如建出的 `ticket_id`、消息 `seq`），而不是整份大结果。重放时返回摘要即可满足"我这次调用成功了，产物是这个"；需要完整结果时再按 id 去读原始数据（幂等记录不是第二份数据库）。

## 四、本仓现状盘点（为什么现在做不了）

| 位置 | 现状 | 缺口 |
|---|---|---|
| `store.write` | `mkstemp` + `os.replace`，单文件原子 | 只有"覆盖式原子写"，没有"独占创建"，无法占位 |
| `store.next_seq` | `itertools.count` 进程内自增，baseline 由调用方从磁盘最大号传入 | 跨进程并发会撞号；两个进程各自从同一 baseline 起算 |
| `channel._route_post` | 读全部消息算 `seq` 再 append | 并发投递撞号 + 空洞；这是"没有单一序列分配器"的直接后果 |
| `sessions._route_spawn` | 每次 glob 全部会话判断是否已存在同岗 | 全量扫描当去重，O(n) 且非原子（两个线程同时判"不存在"） |
| `demand_engine` | 派发即执行，无 attempt/无记录 | 崩溃后事件重放 = 全量重跑，没有任何"这次已经做过"的证据 |
| hook 派发 | 内存队列 + 落盘队列（`channel` 已做事件队列持久化） | 队列持久化只保证"不丢"，不保证"不重复" |

一句话：**现在有 at-least-once，没有 effectively-once**。补的部分不在业务判断里，而在"占位 + 状态 + 租约 + 结果"这四件基础设施上。

## 五、设计

### 5.1 数据模型（文件版，先落地）

路径归 `store` 所有，按模块分区：

```
<module>/data/idem/<桶>/<key 前 2 位>/<key>.json
{
  "key": "...", "route": "tickets.create", "scope": "ticket:<id>",
  "status": "claimed|running|done|failed|abandoned",
  "attempt": 1, "lease_until": 1750000000.0,
  "result_digest": "ticket:20261121-0007", "error_code": "",
  "created_at": "...", "updated_at": "..."
}
```

### 5.2 数据模型（SQLite 版，trace 之后做）

```sql
CREATE TABLE idem (
  key TEXT PRIMARY KEY,
  route TEXT NOT NULL, scope TEXT NOT NULL,
  status TEXT NOT NULL, attempt INTEGER NOT NULL DEFAULT 1,
  lease_until REAL, result_digest TEXT, error_code TEXT,
  created_at REAL NOT NULL, updated_at REAL NOT NULL
);
CREATE INDEX idem_status ON idem(status, lease_until);
```

迁移时文件版是"事实来源"，SQLite 只是同一张表的更快实现——这是把数据库排在 trace 之后的原因：**先有可观测，才知道该给哪些表建索引**。

### 5.3 接口（能力面，不做 DSL 扩展）

底层三个原语放 `store`（它是唯一能碰盘的能力模块）：

```
store.claim   {module, bucket, key, route, scope, lease_seconds}
              → {claimed: bool, status, attempt, lease_until, result_digest}
store.lease   {module, bucket, key, lease_seconds}      → {renewed: bool}
store.settle  {module, bucket, key, status, result_digest, error_code}
              → {settled: bool}
store.sweep   {module, bucket, now}                     → {expired: [key...]}
```

上层语义留在各业务模块的纯函数 + 需求顺序编排里：

- 键怎么算 → 该模块的 `_pure.key_for(...)`（纯函数，无 IO，可单测）。
- 什么算"可重试错误" → 该模块的 `_pure.retryable(code)`。
- 谁该被扫描回收 → 该模块的需求（`idem-sweep` 挂 `clock.tick` 或定时由 `runtime` 触发）。

**明确不做的事**：不给需求语言加 `idem:` / `retry:` / `on_error:` 字段。DSL 保持只有 `call` 与 `send` 的顺序流；幂等是"被调能力的内部契约"，不是编排语法。也就是说，需求还是那一行 `{"call": "tickets.create", "with": {...}}`，能力自己在入口完成 claim/settle。这条线必须守住，否则控制流会顺着"重试"两个字重新长回 DSL 里。

### 5.4 执行体的标准姿势

```
claim = store.claim(...)
if claim.status == "done":  return {reused: true, digest: claim.result_digest}
if claim.status in ("running","claimed") and not expired: return {in_flight: true}
# 拿到执行权后：
try:
    out = 真正的副作用（一次原子落盘 / 一次 spawn / 一次 post）
    store.settle(status="done", result_digest=digest_of(out))
    return out
except Retryable as e:
    store.settle(status="failed", error_code=code(e))
    raise            # 由上层决定退避重试，键不变，attempt 自增
except Fatal as e:
    store.settle(status="abandoned", error_code=code(e))
    raise            # 不再自动重跑，进告警
```

三个不变量：**先占位再执行**（否则并发穿透）、**先落结果再回报**（否则崩溃后无法复用）、**失败也要落状态**（否则键永久卡在 running）。

### 5.5 接入顺序（分批，不一次性全铺）

1. **hook 派发（`demand_engine`）**——收益最大：一条事件一条键，重放直接复用。键 = `sha256(hook|source_seq)`，`source_seq` 来自现有事件队列的落盘序号（它已经单调）。
2. **会话 spawn（`sessions`）**——把现在"glob 全量判断"换成 claim，键 = `ticket|role|stage|attempt_no`，顺手消掉 O(n) 扫描。
3. **工单创建 / 阶段推进（`tickets`）**——键 = `ticket|stage|action`，防"回催两次建两张单"。
4. **频道消息（`channel.post`）**——键 = `ticket|role|turn_no|content_digest`；同时把 `seq` 改成 `store.next_seq` 的跨进程版（单一分配器，见路线规划 P1）。

每批的完成标志：崩溃注入测试（在 claim 之后、settle 之前 `os._exit`）重放一次，副作用计数不增。

### 5.6 与业界方案的对应

Temporal 的 Workflow ID + Run ID + Activity 幂等、Kafka 的 producer idempotence + consumer offset、Stripe 的 `Idempotency-Key` 头，本质都是同一套：**稳定键 + 持久去重 + 结果复用 + 租约**。本仓不需要工作流引擎，只需要这四件基础设施；等 trace 和数据库就位，`idem` 表就是 Temporal 那张 `visibility` 表的极小版本。

## 六、边界：它解决不了什么

- **外部不可控副作用**（第三方 `POST` 下单、给客户发短信）：键只能保证"我们这边不重复发起"，如果对方已收到而我们没记录，仍然重复。只能靠"先记录意图（outbox）→ 再调用 → 用对方幂等键"或对账补偿。
- **非确定性执行体**（LLM 调用）：同一键的两次执行结果不同，所以 `done` 必须复用第一次结果，而不是"重跑一次看看"。这也意味着 LLM 调用必须被包在幂等单元里，而不是散落在重试路径上。
- **跨资源事务**：文件系统没有多文件事务。方案用的是"意图记录先行 + 单点原子落盘 + 状态可判定"，不是 ACID。要真事务，得等 SQLite（P1）把关键表收进去。
- **业务语义错误**：键算错（锚点带时间戳）会让去重永远失效；键算太粗（同一工单所有阶段共用一个键）会把该做的活吞掉。这两类错误靠单测钉：同一事实两次算键必须相等；不同阶段必须不等。

## 七、验收与观测

测试（都要能失败）：

- 同一键并发两次 claim：只有一个 `claimed=true`，另一个拿到 `in_flight` 或 `done`。
- claim 后 `os._exit(1)`，重启扫描：记录为 `abandoned`（租约过期且无痕迹）或可安全重跑，副作用计数 = 1。
- `failed` 重试：`attempt` 自增，成功一次后 `done`，重放返回 `reused=true`。
- `done` 重放：不再调用底层副作用（用计数器断言 0 次）。
- 键稳定性：`key_for` 对同一事实两次相等；不同 stage / 不同 round 不等。
- 跨进程：两个 python 进程各投 100 条同键，`done` 计数 = 1。

指标（进 trace 之后自然可查）：重复命中率、`in_flight` 等待时长、`abandoned` 数量、`failed` 重试分布、`idem` 目录体积与 TTL 清理量。

清理：`done` 记录保留到"业务上不再可能重放"为止（事件队列保留期 + 安全余量），按桶 TTL 归档，不无限增长。

## 八、成本

- 写放大：每个副作用多 2–3 次小文件写（claim / settle / 可选 lease 续租）。按当前 QPS 可忽略；SQLite 后合并为一次事务。
- 复杂度：每个接入点都要定义"键锚点"和"错误分类"，这是真正的工作量，也是唯一不能偷懒的部分。
- 风险：键算错比不做幂等更糟（会吞活）。所以每批接入必须配"同键两次副作用计数 = 1"和"不同事实键必须不等"两条测试。
