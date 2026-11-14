# Hive Agent 设计哲学与落地评估（修复后）

> 评估时间：2026-11-14  
> 评估对象：`main` 工作树（基于生产 HEAD `9d69955`，架构实现提交 `b661972`，版本 `0.5.0`；本次修复尚未提交/部署）  
> 评估方式：代码/规则目录/静态门禁/全量回归/浏览器实测/生产健康检查  
> 相关证据：`docs/architecture/arch-report.md`、`docs/architecture/rule-coverage.md`、`data/rules/catalog.json`

## 0. 结论摘要

核心方向已经落地：模块只提供能力，跨模块关系由 `rules` 模块的规则/流程/事件目录统一执行；后端已做到 0 条直接跨模块 `ctx.api`、0 条直接 `bus.subscribe`，并有静态门禁和 277 条回归兜底。

本次修复后，设计哲学的三个边界已经收口：

1. **模块 UI 的跨模块公开 API 调用已纳入对外契约门禁**。`data/rules/surfaces.json` 显式登记 12 条 `ui → target` 契约；`archscan` 会拒绝未登记的 UI API 前缀。浏览器是外部客户端，这些是“对外入口”，不是服务端模块之间的规则关系，因此没有伪造成 `web -> web` 规则。
2. **流程运行时补上了条件/并行/补偿能力**。`rules.process` 支持 `when`（truthy/falsy/eq/ne/contains/in 等）、`parallel` 并行执行、`compensate` 失败补偿；9 条现有流程仍以 `composes` 顺序组合为主，但不再只有“顺序”这一种表达能力。
3. **需求口径与文档已校正**。规则面板改为“跨模块规则覆盖 18/33 · 对外入口 33/33 · 对外契约 12”；`docs/requirements-flow-map.md` 的旧路径已更新。

仍然保留的边界：`rules.process` 没有隐式事务回滚，补偿必须显式声明；静态分析还不是完整 BPM 语义检查；规则数据在 `.gitignore` 的 `data/` 下，靠 `git add -f` 跟踪。这些属于后续增强，不再是报告中的 P0/P1/P2 阻塞项。

如果用一句话概括：**服务端“能力/关系分离”已经闭环；模块 UI 的对外 API 消费也已从“暗调用”变成可审计契约。**

---

## 1. 你的设计哲学（从对话和代码约束中提炼）

以下是我理解的版本；如果某条不符合你的本意，以你的定义为准。

### 1.1 模块只提供能力，不定义自己在关系中的位置

- `tickets` 只提供“创建工单、开工单、结单”等能力，不知道 `projects` 是它的上层；
- `projects` 只提供“确保项目存在、读取项目、删除项目”等能力，不知道谁在调用它；
- “工单必须归属项目”不是 `tickets` 或 `projects` 的属性，而是规则 `ticket.bind_project` 的定义；
- 关系变了，只改规则/流程，不改两个模块的能力实现。

### 1.2 跨模块关系必须有唯一归属

- 服务端模块之间不得 `import`、不得直接 `ctx.api`、不得直接持有对方对象；
- 所有跨模块同步调用走 `ctx.rule(rule_id, ...)`，由 `rules` 模块翻译成目标模块 API；
- 事件订阅也不得在业务模块里写死 topic，统一登记为 `self.event(event_rule_id, handler)`，由规则层绑定；
- 规则层是“关系的唯一执行者”，不是某个业务模块的私有编排。

### 1.3 规则必须可见、可解释、可静态检查冲突

- 规则要有 id、中文名、来源/目标、实体/谓词、基数、意图和实际 `steps[].call`；
- 规则目录要能在网页上看到，也要有 `rules.graph` 这种结构化输出；
- 静态分析要能发现：未知实体/谓词、未知模块/路由、非法基数、排他谓词冲突、同一三元组基数冲突、流程引用错误、事件发布者/topic 不匹配、规则 id 重复。

### 1.4 用户需求先整理成结构化流程语言，再映射到规则和模块

- 不是拿到需求就直接改模块代码；
- 先写需求流程（`docs/requirement-flows.json` 的 `req-01` … `req-33`），明确目标、节点、边界和验收；
- 再把其中“涉及两个及以上模块”的部分映射为规则/流程；
- 单模块/宿主/基础设施需求保留为能力或验收项，不伪造跨模块关系。

### 1.5 前端是模块的延伸，宿主只做壳

- `web/` 只保留宿主：HTML、`web/core/`、状态机；
- 不允许在 `web/` 下再建一套与业务模块重名的假模块目录；
- 每个业务模块的 UI 放在自己的目录，例如 `hive/modules/projects/ui.js`、`hive/modules/webchat/ui.js`；
- 模块之间不直接调用 UI 函数；跨模块交互用事实事件，例如 `project:open`、`chat:open`、`side:open`、`panel:open`；
- 宿主不集中渲染其他模块的业务内容，只提供挂载点、路由、弹窗壳和全局状态。

### 1.6 事件也是关系，不是绕过规则的后门

- 事件发布/订阅同样要能被审计；
- 发布者、订阅者、topic 由规则目录声明；
- 业务模块只登记“我要订阅哪条事件规则”，不关心实际 topic 字符串；
- 规则层统一 `bus.subscribe`，静态门禁禁止业务模块直接 `bus.subscribe`。

### 1.7 对外入口不等于跨模块关系

这是上一轮讨论后需要明确补进哲学的一条：

- **对外入口**：用户、CLI、HTTP、网页能不能使用这个功能。任何功能都必须有入口或承载位置；
- **跨模块关系**：服务端模块 A 是否必须调用模块 B 的能力；
- 单模块功能由该模块自己的 API/UI 对外提供，不需要 A→B 规则；
- 多模块协作才需要规则，不能为了覆盖率给单模块功能造 `web -> web` 自环。

### 1.8 不偷懒：交付必须可测试、可回退、可部署

- 不能只改后端、把前端留到下一轮；
- 每个阶段都要有静态门禁、全量回归和真机验收；
- 生产部署要可回退、watchdog 保活、版本可见；
- 结论要写进文档和产物，而不是只在对话里说“已完成”。

---

## 2. 落地证据

### 2.1 能力/关系分离

| 证据 | 当前结果 |
| --- | --- |
| 模块数 | 21 个 |
| 对外路由 | 134 条 |
| Agent 工具 | 14 个 |
| 规则目录 | 58 条关系规则、9 条业务流程、9 条事件订阅、12 条对外契约 |
| 业务模块直接跨模块 `ctx.api` | 0 条 |
| 业务模块直接 `bus.subscribe` | 0 条 |
| 模块 import 环 / API 环 | 0 / 0 |
| 规则/流程/事件静态错误 | 0 条，0 条 warning |

`hive/modules/rules/module.py` 是唯一关系执行者：`RuleBook` 负责加载和校验，`Rules.run_api` 负责执行关系规则，`Rules.process_api` 负责按 `composes` 或 `steps` 流程计划执行（支持条件/并行/补偿），`Rules._bind_events` 负责把订阅绑定到总线。业务模块通过 `Context.rule()` / `Context.event()` 接入，代码里不再出现目标模块的名字。

典型链路：

```text
tickets.create
  -> ctx.rule("ticket.bind_project", name=...)
  -> rules.run
  -> steps[0].call = "projects.ensure"
  -> projects 只执行 ensure
```

### 2.2 规则的可见性与静态分析

已落地：

- `GET /api/rules/catalog`：关系、流程、事件、对外契约、活跃状态、覆盖口径；
- `GET /api/rules/graph`：113 个节点、368 条边；
- `POST /api/rules/validate`：返回冲突/错误；
- `POST /api/rules/run` / `POST /api/rules/process`：关系与流程执行；
- 规则面板显示按来源模块分组的关系卡、流程组合、事件订阅、对外契约和“模块关系图”按钮；
- 静态校验覆盖实体、谓词、模块、路由、基数、排他谓词、同一三元组基数冲突、关系图环、流程 compose、事件发布者/topic、需求 id、重复 id；
- 规则来源强校验：模块调用不属于自己的规则返回 403 `rule_forbidden`；
- 动态 `ctx.api` 绕过门禁：变量形式的跨模块调用会被 `archscan` 直接判失败；
- 规则基数冲突曾被实际捕获：`lifecycle.default_project` 与 `lifecycle.project_snapshot` 同三元组但基数 `1:N` / `N:1` 冲突，最终把后者谓词改为 `observes`。

尚未完全落地：

- 模块关系图已能在面板中按规则聚合渲染，但还不是可拖拽/可下钻到单条规则的交互图；
- 规则冲突目前是“声明的语义约束”，不是完整的业务流程模型检查（例如条件互斥、补偿可达性）。

### 2.3 需求 → 流程 → 规则

- `docs/requirement-flows.json` 有 33 条需求流程，全部有 `status`、`evidence`、`nodes`；
- 规则/流程/事件目录中 18 条需求有显式跨模块规则；
- 9 条业务流程以 `composes` 顺序组合表达，例如 `ticket.create`、`ticket.close`、`project.create`、`chat.dispatch`；
- `rules.process` 支持 `when` 条件、`parallel` 并行和 `compensate` 显式补偿，测试实际跑过条件命中/跳过与并行流程；
- 没有把 UI/HTTPS/测试等单模块或基础设施需求强行写成 A→B 规则。

不足：

- 9 条现有流程尚未改用 `steps` 表达条件/并行，运行时能力已具备，但目录还没有示例化；
- 需求到规则仍是人工映射，没有“从流程语言自动推导规则”的编译器；
- `docs/requirements-flow-map.md` 的旧路径已修正，但需求流程文档仍需随代码持续回填。

### 2.4 前端边界

已落地：

- `web/` 只有宿主、`core/`、`style.css`、`rules-graph.css`、`state-machine.json`；
- 没有 `web/modules/` 第二套业务模块目录；
- 业务模块 UI 在自己的目录，由宿主通过 `/module-ui/<模块名>.js` 加载；
- 跨模块 UI 函数直调：0 条（`scan_ui_calls` 检查通过）；
- 跨模块 UI 交互改为事件：`project:open`、`chat:open`、`side:open`、`panel:open`、`idle:*`、`projects:refresh`、`ticket:fork`；
- 状态机 12 个状态、15 个事件、110 个 DOM id、57 个按钮、27 个控件，门禁通过。

已收口的对外 API 边界：

- 浏览器是外部客户端，模块 UI 调公开 API 属于“对外入口”，不是服务端模块之间的规则关系；
- `data/rules/surfaces.json` 登记了 12 条 `ui → target` 契约，覆盖 `projects`、`webchat`、`artifacts`、`health`、`library`；
- `archscan` 的 `scan_ui_calls` 会扫描所有 `"/api/<segment>"` 前缀；未登记前缀直接 `ARCH GATE FAIL`；
- 典型的 `projects/ui.js → /api/sessions/<sec>/compact` 现在被登记为 `ui.projects.sessions`，规则面板和 `rules.graph` 都能看到，不再是一条暗关系；
- 这不是把 UI API 调用改写成规则调用，也不建议用 `web` 宿主集中聚合业务数据——后者正是你之前否决的方案。

### 2.5 事件治理

已落地：

- 9 条事件规则覆盖 `obs`、`health` 两个基础设施通配订阅，以及 `idle`、`tickets`、`sessions`、`projects`、`gitflow`、`artifacts` 的业务事件；
- 所有原有业务模块 `bus.subscribe` 已迁走；
- 发布者未声明 topic、订阅者 `to` 不匹配、事件规则不存在，门禁均会失败；
- `Rules._bind_events` 在模块装配末尾按目录绑定，避免模块在 `setup` 阶段硬编码 topic。

待确认：

- `event.obs.stream`、`event.health.heartbeat` 使用 `from:"*"` / `topic:"*"`；现在通过 `infra: true` 显式标记为基础设施通配，非 infra 事件使用通配会被静态校验拒绝；
- 事件没有版本号/兼容策略，规则改名对历史事件消费者是硬切换。

### 2.6 测试、回滚、部署

| 项目 | 结果 |
| --- | --- |
| 全量回归 | 277/277 通过，74.2s |
| 架构门禁 | `ARCH GATE PASS` |
| 本地 HTTPS 真机 | 规则面板 `58 / 9 / 9`、12 条对外契约、模块关系图、校验通过 |
| 生产版本 | `0.5.0`，HEAD `9d69955`（本次修复未部署前） |
| 生产健康 | `ok`，`healthy: true`，watchdog active |
| 生产规则目录 | 58 关系 / 9 流程 / 9 事件 / 0 errors |
| 部署形态 | 本地 main → GitHub main → 生产 bare repo → post-receive 自动检出 + provision |

---

## 3. 逐条对照

| 设计原则 | 落地状态 | 证据 | 主要缺口 |
| --- | --- | --- | --- |
| 模块只提供能力，不定义关系 | 已落地 | 0 直接跨模块 API；58 条关系规则；`ticket.bind_project` | 无（服务端） |
| 关系有唯一归属 | 已落地 | `rules.run`、`rules.process`、`rules.event`；来源强校验 | 外部 `rules.run` 可用 `source` 省略走 API 来源，缺少调用者身份契约 |
| 规则可见、可解释 | 部分落地 | 规则面板、catalog、graph API、模块关系图 | 图不可下钻单条规则 |
| 规则可静态检查冲突 | 部分落地 | 基数冲突、排他谓词、路由/模块/需求/关系环校验 | 缺条件互斥/补偿可达性/事件版本检查 |
| 需求先结构化再映射 | 已修复（口径） | 33 条需求流程；18 条有规则；流程运行时支持条件/并行/补偿 | 人工映射；9 条流程仍以 composes 为主 |
| 业务模块互不感知 | 已落地 | 0 import 环、0 API 环、0 直接 bus | 无（服务端） |
| 前端宿主只做壳 | 已落地 | `web/` 无假模块目录；UI 函数直调 0；12 条对外契约 | 对外契约仍是公开 API 消费，不是 UI→UI 调用 |
| 事件也是关系 | 已落地 | 9 条事件规则；0 直接 `bus.subscribe`；`infra:true` 限制通配 | 事件版本/兼容策略未做 |
| 对外入口与跨模块关系分开 | 已落地 | 33 条需求均有 status/evidence/承载位置；面板双口径 | 对外契约证据需持续维护 |
| 可测试、可回退、可部署 | 已落地 | 277 条回归、archscan、生产 watchdog、push 即部署 | 生产端到端回归仍以本地为主 |

---

## 4. 需求覆盖的正确口径

### 4.1 33/33 是入口/承载覆盖

`docs/requirement-flows.json` 的 33 条需求全部有：

- `status`：29 条“已实现”，2 条“已实现（v4.1 修正）”，1 条“已决策”，1 条“已实现（v4.1 新增）”；
- `evidence`：33 条都有证据字段；
- `nodes/edges`：33 条都有需求流程节点。

所以“功能没有对外用”这个结论是不成立的；33 条都有承载入口或验收设施。

### 4.2 15 条没有跨模块规则的需求

| 需求 | 承载入口/模块 | 类型 |
| --- | --- | --- |
| req-01 侧边栏收起 | `web/core/shell.js` | 宿主 UI |
| req-03 去掉本地节点展示 | `web/core/`、状态机 | 宿主 UI |
| req-05 历史工单只做增量 | `hive/modules/tickets/module.py` | 单模块能力 |
| req-08 PM 并行编排 | `hive/modules/webchat/ui.js`、tickets 流程 | 前端/模块 UI |
| req-09 压缩项目秘书上下文 | `hive/modules/projects/ui.js` + sessions API | 模块 UI/单模块 API |
| req-10 流程可插拔复核 | `hive/modules/archgate/module.py` | 架构门禁 |
| req-12 仓库移到 `E:\AI` | `config/`、部署路径 | 环境/部署 |
| req-13 推送 GitHub | `hive/modules/gitsync/module.py`、`DEPLOY.md` | 运维 |
| req-16 3×3 并发演练 | `tests/run_all.py` | 测试 |
| req-17 HTTPS 加强安全 | `hive/kernel/http.py` | 传输层 |
| req-19 本地层是否必要 | 架构文档、前端 | 架构决策 |
| req-26 Markdown 渲染 | `hive/modules/webchat/ui.js` | 前端 UI |
| req-28 流式/打断/不超时 | `hive/kernel/llm.py`、`react.py`、webchat live | 内核/UI |
| req-29 项目/公共交付件、三库页面 | `library/ui.js`、`artifacts/ui.js` | 前端 UI |
| req-33 返回键/刷新恢复/状态机 | `web/core/core.js`、`state-machine.json` | 宿主 UI |

其中 req-09 是“项目 UI 直接调用 sessions API”的典型条目。修复后它已登记为 `ui.projects.sessions` 对外契约，不再需要升级为服务端规则；如果把它当规则，反而会把浏览器入口和服务端模块关系混在一起。

---

## 5. 修复结果与残余风险

### 已修复：P0 模块 UI 跨模块 API 暗调用

- 新增 `data/rules/surfaces.json`，登记 12 条对外 API 契约；每条包含 `ui`、`target`、`prefix`、`methods`、`intent`、`requirements`。
- `hive/archscan.py` 新增 UI API 前缀扫描：所有 `"/api/<segment>"` 只要不是本模块自有路由，就必须命中契约，否则门禁失败。
- `RuleBook` 校验契约的 UI 模块、目标模块、前缀、方法、需求 id；`rules.catalog`、`rules.graph` 和规则面板都能展示契约。
- 当前 5 个 UI 模块的 12 条跨模块 API 消费全部有契约；`ARCH GATE PASS`。

### 已修复：P1 流程运行时只有顺序组合

- `rules.process` 支持 `steps` 计划：`when` 条件、`parallel` 并行、`compensate` 显式补偿。
- `when` 支持 `truthy/falsy/eq/ne/contains/not_contains/in/not_in`，字段用 dotted path 读取 payload。
- 失败时只对已执行步骤按逆序执行声明的补偿；不做隐式事务回滚，避免假装有跨模块事务。
- 新增回归用例实际验证条件命中/跳过、并行执行和补偿调用。

### 已修复：P2 覆盖口径与文档漂移

- 规则面板改为“跨模块规则覆盖 18/33 · 对外入口 33/33 · 对外契约 12”。
- `docs/architecture/rule-coverage.md` 增加 12 条对外契约表，并更新维护规则。
- `docs/requirements-flow-map.md` 的旧路径已更新，不再是报告里的验收障碍。

### 已修复/部分修复：P3 可视化与静态分析

- 规则面板新增“模块关系图”，使用 `rules.graph` 按规则聚合渲染 14 个有关系模块和 29 条模块级关系边。
- `RuleBook` 新增关系图环检测；当前关系图为 0 环。
- 仍是部分修复：图不可拖拽/下钻单条规则；静态分析还没有条件互斥、补偿可达性等完整 BPM 语义检查。

### 残余：P4 规则数据跟踪与事件版本

- `data/` 仍被 `.gitignore` 忽略，`data/rules/*.json` 依赖 `git add -f`；需要提交时显式强制跟踪。
- `event.obs.stream`、`event.health.heartbeat` 已用 `infra: true` 标注；非 infra 事件使用 `from:"*"` / `topic:"*"` 会被静态校验拒绝。
- 事件没有版本号/兼容策略，规则改名对历史消费者仍是硬切换。

---

## 6. 建议的后续增强

1. **P3 深化**：把模块关系图做成可下钻到单条规则/需求的可交互图，并在图上标出孤立规则、零调用规则和关系环。
2. **P3 语义**：给 `when` 增加条件互斥检查、补偿可达性检查、并行写冲突检查；目前只做到结构校验。
3. **P4 数据门禁**：加测试断言 `git ls-files data/rules/catalog.json data/rules/ontology.json data/rules/surfaces.json` 非空，防止 `data/` 忽略导致部署缺规则。
4. **流程目录示例化**：把 1–2 条现有流程改成 `steps`，实际使用条件/并行/补偿，而不是只具备运行时能力。
5. **事件版本**：给事件规则增加 `version`/兼容策略，避免 topic 或 payload 变更造成静默断链。

---

## 附录：本次修复后的关键数字

```text
模块：21
路由：134
工具：14
关系规则：58
业务流程：9
事件订阅：9
对外契约：12
规则图节点/边：113 / 368
模块级关系边：29 / 环 0
需求流程：33 / 环 0
规则错误/warning：0 / 0
服务端直接跨模块 API：0
服务端直接 bus.subscribe：0
前端跨模块 UI 函数直调：0
未登记 UI API 契约：0
全量回归：277/277，74.2s
生产版本：0.5.0
生产 HEAD：9d69955
生产健康：ok，healthy true
```




