# AI_NEW 架构契约

三条根规则，其余全是它们的推论：

1. **能力在模块里，业务在数据里。**
2. **模块没有特权**：不属于自己的事（写日志、发通知、决定"要不要做"）它一律不做。
3. **结构性的事情都能静态读出来**：装配顺序、业务接线、通信通道，不靠约定和记忆。

## 一、目录：两个入口、三个组

```
agent_start.py          跑系统
test_start.py           跑验收（静态检查 + 可选 --smoke 真的执行 agent_start.py）
ai_new/modules/
  agent_common/         公共能力：配置、存储、通信、日志、需求引擎
  agent/                业务能力：知识、交付件、岗位库、会话、工单…
  agent_test/           评审者：验什么、怎么验（和系统同构的模块）
```

每个模块**自带 `data/`**：config 的 data 是配置，ops 的 data 是日志，demand_engine 的
data 是需求，library 的 data 是岗位库和角色提示词，tickets 的 data 是工单和消息模板，
web 的 data 是控制台页面，agent_test 的 data 是验收清单 —— 语义由拥有它的模块定义。


- 根目录**只有两个脚本**，没有第三个特殊目录：没有 kernel、没有 `tools/`、没有 `data/`、
  没有 `web/`、没有垃圾桶。
- **组不是层级特权**：组只是"装配单位"，同一个扫描器、同一套规则；`data/profiles.yaml`
  决定哪个入口装哪些组（`agent` 只装 common + agent，`agent_test` 只在验收时跑）。
- `agent_test` 是模块，不是"外部测试目录"：它有自己的清单（`data/checks.yaml`）、
  自己的私有实现，和别的模块同构；它不在 `agent` 的装配里，只是因为 profile 里没写它。

## 二、一个模块 = 一个公开文件 + 一个 private 目录

```
modules/<组>/<模块>/
  __init__.py            对外：setup(ctx) / 可选 start(ctx) / 少量公共函数
  private/...            实现；文件名随便取（私有由目录表达，不靠 _ 前缀）
```

- **模块之间不 import**：运行时唯一通道是 `ctx.api.call("module.fn", payload, caller=...)`。
  调用方身份由注册表判定：需求引擎（`caller="demand_engine"`）、平台件（`platform:<组件>`）、
  模块（`module:<模块>`，只能调自己模块，或 `api/data/internal-calls.yaml` 登记过的目标模块）。
  未登记的跨模块直调在 `api.internal_call_mode=enforce` 下直接拒。
  资源面（`ctx.api / ctx.hooks / ctx.demand_engine / ctx.tools / ctx.cfg / ctx.storage /
  ctx.http / ctx.llm / ctx.react`）由装配器注入后直连。
- **单向可见**：审计者可以看被审计对象，反过来不行。所以 `agent_test` 可以 import 运行时模块，
  运行时模块却连自己的兄弟都不许 import。
- **模块不做有政策含义的事**：不写日志、不发通知、不直接订阅回调。它只在功能前后预留
  hook 点；谁要在那个点做事，写在需求里。

## 二·补、注册表三分类：需求编排 / 平台入口 / 模块私有

`ctx.api.register(...)` 挂上去的名字就是对外 API。一个函数能不能进注册表，只看它被谁调，
分三类，**不许有第四类**：

| 分类 | 谁在调 | 登记方式 | 例子 |
|---|---|---|---|
| **需求编排的业务能力** | 某条需求 `do` 语句树里的 `call` | 出现在需求语句树中，由 `demands` 契约钉住 | `store.write`、`tickets.create`、`llm-chat` 各步 |
| **平台入口** | HTTP 闸 / SSE / 需求引擎 / 装配期直接调用（`caller=None` 或引擎内部） | 必须在 `api/data/platform-routes.yaml` 登记 `caller` 与 `reason` | `auth.verify`、`auth.status`、`channel.watch`、`clock.sleep`、`hooks.points` |
| **模块私有，不注册** | 只在模块内部进程内直调的纯函数/面板方法 | 留在 `private/` 或模块面板，**不进注册表** | 内部形状变换、纯计算助手、仅供测试直调的面板方法 |

铁律：

- **只被模块内部进程内直接调用的纯函数不是 API**，不得注册到注册表；保留为模块私有函数即可。
- **任何对外暴露的已注册 API 都必须对应至少一条需求编排**；不属于需求编排的，只能是清单里
  登记过的平台入口。运行时闸 `test_registered_routes_are_demand_bound_or_platform` 闭合：
  注册路由 ∈ 需求 do 树 ∪ 平台清单，多出一条即红。
- 新增平台路由必须先在 `platform-routes.yaml` 写明调用方与原因；想把一个内部能力重新挂成 API，
  要么补一条需求编排，要么登记为平台件，不许直接 `register`。

## 二·补二、落盘是业务动作，必须受需求或平台管辖

运行期写盘（存什么、存哪里、怎么存）是有副作用的业务动作，**不允许模块/注册表隐式写盘**：

- 业务写盘一律走 `store.*` 写路由，由需求 `do` 树显式编排；存到哪个模块自己的数据目录、
  文件名、文本/字节/追加/归档，都由需求的参数决定。
- 注册表、工具执行器、能力助手不得在“输出过大/触发某条件”时自动落盘；大输出要不要留存、
  存到哪、怎么存，由需求显式调 `store` 能力决定。
- 平台件的写盘（装配/编译产物、引擎内部状态回写）属于平台职责，登记在清单或能力层面板，
  不经过业务注册表。
- 运行时闸 `test_write_routes_are_governed` 闭合：写能力路由 ∈ 需求 do 树 ∪ 平台清单。

## 三、装配不是清单，是推导 + 剖面

- 扫描器 `boot/private/_graph.py` 读每个模块 setup 阶段**真正执行的代码**：
  谁写了 `ctx.X = ...` 就是提供方，谁读了 `ctx.X` 就依赖它，据此建 DAG 并拓扑排序。
- 组合根 = 没有 `setup` 的模块（`boot`）；启动阶段 = 导出 `start(ctx)` 的模块（`http`、`tickets`）。
- 两段生命周期：`setup` 只装填自己的面、注册路由、声明 hook 点；
  `start` 才产生外部效果（开始收请求、拉起线程）。
- 装配哪些组由 `data/profiles.yaml` 决定，入口不写清单：
  `python agent_start.py`（agent）· `python test_start.py`（agent_test）。

## 四、通信是抽象，绑定是产物

模块里永远只写逻辑调用，它走哪条通道由编译产物决定：

| 通道 | 语义 | 适合 |
|---|---|---|
| `direct` | 同进程同步调用，返回值就是服务返回值 | 默认，单进程 |
| `unix` | 本地 socket（AF_UNIX 文件路径，权限 0600） | 同机跨进程，权限收得最紧 |
| `tcp` | 网络 socket（AF_INET，只绑回环） | 同机跨进程/预演多机 |
| `shm` | 共享内存信箱（mmap + flock，请求/应答各一份） | 大报文、低延迟 |

四条通道共用一份报文协议（`api/private/_wire.py`）：4 字节长度前缀 + UTF-8 flow 报文，
带协议版本 `v`；请求 `{v, token, route, payload}`，应答 `{ok, result}` 或 `{ok, error, code}`。
`send` 一定等回包，`notify` 不取返回值。异步路由同样服从绑定：绑了非直连通道时同样发出去。

- 意图写在 `data/deploy.yaml`（可选），产物是 `data/gen/bindings.yaml`。
- 编译是 **api 模块的能力**，不是根目录脚本：装配之前 `python agent_start.py --compile-transport`
  或调 `api.compile_transport` 模块函数；编译产物是装配/CLI 工具件，不挂业务注册表。
- 没有 `deploy.yaml` 就是全直连，等于单进程跑，行为与以前完全一致。

## 五、业务是结构化语言，引擎负责让它跑

- 模块 = 能力（服务 + 预留扩展点）。**需求 = 一段可插拔的业务**，写在
  `modules/agent_common/demand_engine/data/demands/*.yaml`（当前 113 条）：

```json
{
  "id": "<需求 id>",
  "on": ["sessions.done", "knowledge.written"],
  "do": [
    {"call": "ops.record", "with": {"hook": {"get": "event.hook"},
                                    "data": {"get": "event.data"}}}
  ],
  "expect": {
    "given": {"on": "knowledge.written",
              "event": {"hook": "knowledge.written", "data": {"name": "样例条目"}}},
    "calls": ["ops.record"],
    "payload": {"ops.record": {"hook": {"get": "event.hook"}}},
    "promise": "任何一个点上发生的事，都要在 data/logs/app.jsonl 留一条"
  }
}
```

- 语法（`demand_engine/private/_lang.py`）：表达式只有 `get`（点号路径）与 `lit`（字面量）；
  语句只有 `call`（可带 `with` 映射参数、`as` 存结果）与 `send`（单向通知）。
  **没有 `let` / `fail` / 运算符 / 分支 / 循环**——路径拼接、命名、比较、遍历全部下沉模块纯函数。
- **需求树只允许顺序执行**：分支、遍历、循环、等待都在模块功能函数内部完成。
  需求里出现 `when / each / until / wait` 由静态禁令闸直接判失败（`test_demands`）。
- 引擎 `demand_engine` 只做装载、路由、解释执行，不认识任何业务名词。
- **先有需求，才有扩展点**：没有需求订阅的 hook 点会被扫描器点名"可以连同 emit 一起删掉"。
- 可插拔：加需求 = 加文件；停需求 = 引擎面板 `set_enabled(id, false)` 或挪走文件；
  需求下线后它订阅的点失去消费者，扫描器立刻指出来 —— 点跟着需求下线。
- 同一个点可以被多个需求各自订阅，互不影响。

### 两种需求：挂点的与按名的

- **挂点需求**：`on: ["channel.posted"]`，模块 emit → 引擎 dispatch。被动，事件驱动。
- **按名需求**：`"callable": true`、`on: []`，由 `demand_engine.run(id, input)` 主动调用。
  它是"一条业务编排"：把若干纯能力按顺序拼起来（例如 `llm-chat` 六个步骤）。

两种都受同一套契约约束（`expect`、用例点名、路由必须真注册）；区别只在于"谁先开口"。
模块不会被业务反过来指挥：业务想编排，只能通过需求调用它暴露的纯函数。

### 需求自带预期：需求 ↔ 用例双向绑定

需求本来就隐含四件事：在哪个点、拿到什么输入、调哪些服务、结果长什么样。
不写出来，这四件事就只存在于作者脑子里 —— 那就是运行时糊浆。所以每条需求必须带 `expect`：

| 字段 | 含义 | 谁能验 |
|---|---|---|
| `given.on` / `given.event` | 预期输入：哪个点、什么样的载荷 | 静态（必须在自己的 `on` 里）+ 运行时真投一次 |
| `calls` | 预期动作：要调哪些服务，顺序如何 | 静态（必须出现在 `do` 的语句树里）+ 运行时核对调用顺序 |
| `payload` | 预期输出：传给服务的参数（`get`/`lit` 表达式） | 运行时核对实际载荷 |
| `promise` | 一句话说明这条需求保证什么 | 人读 |

规则是**双向闭合**的，由 `test_start.py` 强制：

- 没有 `expect` 的需求 → `demands` 组失败；
- 没有验收用例点名的需求 → `structure` 组失败（`data/checks.yaml` 里没有 `demands` 覆盖它）；
- 用例点名了不存在的需求 → `structure` 组失败（需求下线后清单必须跟着改）；
- 预期里的调用不在语句树里、或者运行时多出没人预期的调用 → `demands` 组失败。

这样需求的"上线/下线"就是原子的：需求文件、它的预期、它的用例，三者一起走。

## 六、标准库能力也收编

模块只提供能力，不自己跟外界打交道。四个能力各管一段，其余模块只能调它们：

| 能力 | 覆盖的 stdlib | 谁在用 |
| --- | --- | --- |
| `store` | pathlib / os / shutil / zipfile / tempfile | 所有模块的 data；`ctx.storage.own(__file__)`；JSON 交 codec、时间交 clock |
| `net` | urllib / socket / ssl（出站） | 编排需求 `llm-chat` 发请求 |
| `host` | /proc、磁盘、负载、环境变量 | `health.self` 概览 |
| `clock` | time / datetime | 全系统唯一的"现在"：uptime、消息时间戳、停滞判定、等待超时 |
| `http` | socket / ssl / urllib.parse（入站） | 浏览器、SSE、静态 |

装配期例外只有三个，且是职责而非特权：`boot`（组合根，装配前读 profiles 与源码）、
`api`（绑定生成）、`config`（任何模块之前就要知道配置）。

由 `test_modules_touch_no_stdlib_io_directly` 钉住：除此之外的模块一旦
`import pathlib/os/shutil/urllib/socket` 或直接 `open(...)`，验收即红。换通道（代理、网关、
本地桩、共享内存）只换能力模块的实现模板，业务侧一行不动。

## 六、模块职责

**agent_common（公共能力）**

| 模块 | 只负责 |
|---|---|
| boot | 组合根：扫描装配图、按剖面动态装配（唯一没有 setup 的模块） |
| config | 配置合并/读取/落盘/脱敏（含环境变量部署覆盖）；`get(key)` 给真值，不带 key 才返回脱敏视图 |
| store | 运行时文件系统：目录/原子 JSON/文本/字节/glob/walk/打包/safe_id/时间（`ctx.storage`） |
| api | 路由注册与调用方身份判定（需求/平台/模块台账）、通信通道编译（`ctx.api`） |
| hooks | 扩展点：声明点、触发点；不装订阅者，派发给需求引擎 |
| demand_engine | 需求装载与解释执行（`ctx.demand_engine`） |
| tools | 工具注册/执行；不隐式落盘，留存由需求编排 |
| llm | **纯语义**：`encode`（对话→载荷）、`decode` / `decode_sse`（响应→对话结果）；无网络/无 JSON/不读配置 |
| codec | **纯计算**：JSON 编解码、SSE 帧解析、base64/hex、摘要 |
| net | 出站网络：`net.request`（运行时唯一 import urllib 的模块） |
| host | 主机资源：`host.info`（内存/磁盘/负载，health 概览读数） |
| react | ReAct 循环（无业务） |
| http | 入站传输：HTTP/SSE、静态资源、鉴权、RPC 入口（入站的 urllib/ssl 归它） |
| ops | 记录（`data/logs/app.jsonl` 归它所有）/总览/日志/导出 |

**agent（业务能力）**

| 模块 | 只负责 |
|---|---|
| knowledge | public/project/ticket 三层知识 |
| artifacts | 交付件落盘/读取 |
| library | 角色/流程/技能库 + 产出校验 |
| sessions | 会话生命周期、并发闸门、执行 |
| projects | 项目档案 |
| tickets | 工单、分单、PM 工具、通知、停滞审计 |
| health | 存活与自检 |
| web | 控制台与消息面板：自己的静态资源（`data/console/`），通过 `web.asset` 供给 http |
| channel | 消息收发：`post/tail/watch/list`；`watch` 标 `stream`，被 http 当 SSE 读 |

**agent_test（评审者）**

| 模块 | 只负责 |
|---|---|
| agent_test | 按 `data/checks.yaml` 跑验收：结构契约、装配图、需求语言、通信通道、运行时行为 |

## 七、数据布局：跟着模块走

没有公共 `data/`。每个模块的数据就在它自己旁边，谁的数据归谁，语义不会被一个筐搅浑：

```
modules/agent_common/config/data/        config.default.yaml · config.yaml
modules/agent_common/boot/data/          profiles.yaml（装配剖面）
modules/agent_common/api/data/           deploy.yaml · platform-routes.yaml（平台入口清单）· internal-calls.yaml（跨模块直调台账）· gen/bindings.yaml
modules/agent_common/demand_engine/data/ demands/*.yaml（一段业务一个文件）
modules/agent_common/ops/data/           logs/app.jsonl · exports/
modules/agent/library/data/              seed.yaml · roles.yaml · prompts/roles/*.md
modules/agent/sessions/data/             sessions/ · prompts/{pm,secretary}.md · session-tools.yaml
modules/agent/tickets/data/              tickets/<id>/ticket.yaml · messages.yaml
modules/agent/knowledge/data/            public/ · projects/ · tickets/
modules/agent/artifacts/data/            public/ · projects/
modules/agent/projects/data/             <id>.yaml
modules/agent/logs/data/                 日志与工具输出的归类索引
modules/agent/asr/data/                  语音转写模型目录（运行时填充）
modules/agent/decompose/data/            拆分规则与样例
modules/agent/auth/data/                 令牌与登录态
modules/agent/todos/data/                待办
modules/agent/channel/data/              频道消息与游标
modules/agent/web/data/console/          manage.html · login.html · *.js
modules/agent_test/data/                 checks.yaml
```

- 模块只认 `ctx.storage.own(__file__)`：它拿到的就是**自己的**数据目录，碰不到别人的。
  `structure` 组会断言没人再用旧的全局存储接口（`data_dir/json_read(paths.data…)`）。
- 跨模块的数据要经由能力：工单不翻岗位库的目录（调 `library.check`），会话不翻岗位库的
  提示词（调 `library.role_prompt`），项目 purge 不删别人的目录（调 `knowledge.remove-project`
  与 `artifacts.remove-project`）。
- 部署搬迁：`AI_NEW_DATA=E:\ai_new_data`，布局镜像 modules/（`<根>/<组>/<模块>/`，
  `agent_test` 这种"组即模块"的就是 `<根>/agent_test/`）。"数据在哪"是部署问题，
  不是每个模块各自拍脑袋的问题。

### 控制台不认识业务，只认规格

`web` 是模块，`data/console/manage.html` + `app.js / spec.js / render.js / recorder.js /
actions.js / boot.js` 是**规格驱动的通用渲染器**：

- 视图清单来自需求 `views-list`（`demand_engine.list` 里带 `view` 的条目），`boot()` 把
  `view.key / params / nav / parent / default / labels / forms / data` 装进 `VIEWS / FORMS`；
- URL 只由规格 `params` 生成，旧链接按"参数匹配最全的视图"推导，不写死视图名；
- 渲染只认 12 种原语（`call / cards / chat / composer / doc / kv / m / note / table / tool /
  tree / demand`），不认识"工单/知识/会话"这些名词；
- 事件词表（如工单历程的中文标签）由视图规格的 `labels` 提供，页面自身没有业务词表。
- 静态字节由 `http` 通过 `web.asset` 取（`http` 不知道页面放在哪）。

## 八、验收

`python test_start.py`（清单在 `data/checks.yaml`）：

1. structure —— 模块根只有 `__init__.py`、实现在 `private/`、运行时无跨模块 import、
   运行时无 `ctx.log`/`ctx.bus`、平台模块无业务词、代码无提示词、
   注册路由 ∈ 需求 do 树 ∪ 平台清单、写路由受管辖、根目录只有两个脚本；
   没有公共 data 桶（每个模块只用 `own(__file__)`）。
2. assembly —— DAG 无环、覆盖全部模块、顺序满足每条边、可复现、监听只在 start 阶段、
   hook 点与需求闭合（触发必声明、声明必有用、需求调的服务必存在）。
3. language —— 需求语言求值、顺序编排、插拔、失败不外溢。
4. transport —— 绑定编译可复现、直连/本地 socket/网络 socket/共享内存四种通道、编译产物路径。
5. behaviour —— 临时数据目录真实装配 + 真 HTTP：知识/交付件/工单/会话/矩阵/鉴权/RPC，
   以及"没有需求就什么也不发生"（到点无动作、不自动写日志）。
6. demands —— 需求契约：每条需求都有预期（given/calls/payload）、预期与语句树一致、
   被清单点名、真投一次调出预期顺序与载荷、没有无主动作、下线后沉默。

`python test_start.py --smoke` 额外**真的执行 `agent_start.py`**：临时数据目录、空闲端口，
等它自己报到，核对模块数 / 需求 / hook 点 / 启动日志，然后收掉。

## 九、数据层：文本为真，暂不引入数据库与 RAG

知识与业务信息只以文本文件（markdown / yaml）存在，语义选择交给 LLM 现场阅读，
不做向量化、不做检索增强。理由是这套系统的查询对象是"少量、长文、强结构"的：

- 每条需求、每个岗位、每张工单都是可读的 yaml，字段即契约，人和模型都能直接读；
- 规模在千级文件内时，`store.walk / glob` 的全目录扫描是线性且可预测的，
  一次首屏几十毫秒，比维护索引更便宜；
- RAG 会把"读哪一段"变成检索器决定，命中错误时模型无从复核；直接给全文，
  模型可以按需回溯，错了也能指出原文。

引入数据库的触发条件写死在这里，避免凭感觉改架构：

1. 单次 `store.walk` 超过 20 万文件或稳定超过 300ms；
2. 需要跨文件的原子事务（当前写入都是"单文件原子替换 + effects 顺序执行"）；
3. 需要按时间窗口做聚合统计，且扫描成本压不进前端首屏预算。

届时也只加 SQLite 做**索引/幂等台账**，正文仍留文本：索引可重建，文本是唯一真源。


---

## 十、状态机归属岗位：一处定义，不再同名镜像

**原来的错**：`flows.yaml` 里 9 条流程的 key 与岗位 id 完全同名，岗位再用 `flow: <自身 id>` 指回自己。绑定零信息量，等于一个岗位被切成两半存两个文件；改一处忘一处就会漂移。

**现在的口径**：

- 岗位记录（`roles.yaml` / `seed.yaml` 的 roles）自己持有 `checks`（交付检查项）、`states`（状态机：id/cn/desc/tools/next/terminal）、`kind`。删除 `flow` 字段。
- `flows.yaml` 只保留**被多个岗位复用的子流程**：目前只有 `requirement-owner`（PM 的首状态以 `ref` 指向它）和 `ticket-health`（巡检岗复用）。它们不是岗位镜像，是真正的共享流程。
- 需求层读 `roles.yaml` 一次，把岗位记录整体交给模块；不再读两份库、再做一次 `library.get kind: flows`。
- 拆解入库产出的岗位直接带 `checks`/`states`，不再额外生成同名流程记录；`skills.yaml` 里删掉 `flow` 字段。
- 统计口径随之收敛：`library.summary` 的"流程数"= 带状态机的岗位数。

**判断规则**（下次遇到同类拆分时用）：流程与岗位 1:1 且 key 同名 → 内联进岗位；流程被 ≥2 个岗位引用、或有独立生命周期 → 单独成实体，用 `ref` 显式引用。判据是"是否有第二个使用者"，不是"概念上像不像两个东西"。

**前端**：架构页的"岗位状态机"由文字链改为按转移关系分层的有向图——横向是层级，同层并列表示可并行，箭头是允许迁移，绿框是终态；节点悬停显示该状态的职责说明。
