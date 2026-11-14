# Hive Agent 架构与门禁说明（v4.5 重构起点）

> 这份文档不是事后说明，而是门禁的一部分：`python -m hive.archscan --report` 会生成
> `docs/architecture/arch-report.json` 与 `arch-report.md`，记录模块出口、API 依赖、
> 流程 DAG、网页状态机的一致性。改代码前先看报告，改完必须让门禁重新通过。

## 1. 后端：一个模块一个唯一出口

- 每个模块的唯一出口是 `hive/modules/<name>/__init__.py`，内部实现是同目录的
  `module.py`，不对外导出；模块之间没有 Python `import`。
- 对外能力只有两类：`self.api.route(...)` 注册的 HTTP/内部 API，以及
  `Tool(...)` 注册的 Agent 工具；其余函数按内部实现处理。
- 跨模块调用统一走 `ctx.api("module.method", ...)`；`ctx.api` 实际寻址
  `Hub.request(路由 ID)`，调用方只认服务名，不持有对方模块对象。
- 运行期高频事件走实例通道 `domain:<instanceId>:<action>`；发现期只有
  `domain:mounted` 广播（项目域带 `projectId` 与 `mountContainerId`）。
- 事件名统一 `领域:动作`；历史点号名在总线边界自动归一化。门禁会拒绝静态
  字面量中不符合格式的事件名（`*` 通配除外）。
- 门禁硬错误：跨模块 import、import 环、事件名不合规、网页契约错误、流程 DAG 环、
  **基线之外的新 API 环**。
- API 环基线在 `docs/architecture/api-cycles-baseline.json`。当前 API 调用图为 **0 环**：
  - 项目详情/删除编排拆到 `lifecycle`（lifecycle -> projects / tickets，单向）；
  - `projects` 不再查工单，`tickets` 不再被 `projects` 反向依赖；
  - `sessions <-> projects` 改由 `project.delete.before` 同步事件清理；
  - `artifacts <-> tickets` 改为归档 index 记录 `closed`，压缩不再查工单；
  - `idle -> tickets` 改为 `idle.ticket.dispatch` + `idle.dispatch.ack` 事件，失败保留队列项。
- 新代码如果引入未登记环，默认门禁直接失败；`--strict-api` 则把所有环升级为阻塞。
  拆掉一条边后必须同步删除基线项，不能把基线当永久豁免。

### 1.1 非业务能力也是模块

- `archgate`：`GET /api/gate/arch`，运行同一套静态门禁。
- `testrunner`：`GET /api/test/catalog`、`POST /api/test/run`，只跑仓库内置套件。
- `gitsync`：`GET /api/gitsync/status`、`POST /api/gitsync/fetch`，不自动 merge/push。
- 模块装配表是动态导入；删除一个非核心模块目录后装配器跳过，其他模块不改代码。

### 1.2 前端：web 只做宿主，UI 回到业务模块

- `web/` 只保留一个宿主：`index.html`、`web/core/core.js`（全局状态/API/路由）、
  `web/core/ui.js`（弹窗壳）、`web/core/hive-ui.js`（前端事件与挂载注册）。
- `web/` 下不再有 `web/modules/project`、`web/modules/chat` 这类“第二套业务模块目录”。
- 每个业务模块自己的 UI 放在自己的目录：
  - `hive/modules/projects/ui.js`：项目页模板、工单列表、秘书卡片、新建工单、空闲/交付件；
  - `hive/modules/webchat/ui.js`：群聊模板、时间线、标签、流程、直播、输入区；
  - `hive/modules/artifacts/ui.js`：交付件/文件/源码侧栏；
  - `hive/modules/library|health|idle|ops/ui.js`：各自弹窗或操作。
- 宿主通过 `/module-ui/<模块名>.js` 加载 UI 文件；文件由各模块目录提供，不在 `web/` 复制。
- 业务按钮绑定也回到模块 UI：项目页按钮在 `projects/ui.js`，群聊 `send/刷新/标签/派生`
  在 `webchat/ui.js`，运维按钮在 `ops/ui.js`。宿主只绑登录、导航、返回、弹窗关闭等壳层控件。
- 模块之间不直接调用 UI 函数；项目页用 `chat:open`、`side:open`、`idle:open`、
  `idle:save`、`ticket:fork` 等事实事件，由目标模块自己订阅并处理。
- 静态门禁会拼接 `web/core/*.js` + `hive/modules/*/ui.js` 校验状态机、DOM 引用、
  按钮/控件绑定，并拒绝重新出现 `web/modules`。



## 2. 项目生命周期（归档 / 删除 / 级联）

| 动作 | 项目记录 | 秘书会话 | 工单 | 项目层交付件 | 项目层知识 | main 工作树 | 外部源码 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 归档 | 保留、置 archived | 保留 | 保留 | 保留 | 保留 | 保留 | 保留 |
| 删除（默认） | 删除 | 销毁 | 保留 | 保留 | 保留 | 保留 | 保留 |
| 删除 + tickets | 删除 | 销毁 | 只删已结单工单 | 保留（证据） | 保留（证据） | 视 main_tree | 保留 |
| 删除 + artifacts | 删除 | 销毁 | 视 tickets | 删除项目层 | 视 knowledge | 视 main_tree | 保留 |
| 删除 + knowledge | 删除 | 销毁 | 视 tickets | 视 artifacts | 删除项目层 | 视 main_tree | 保留 |
| 删除 + main_tree | 删除 | 销毁 | 视 tickets | 视 artifacts | 视 knowledge | 删除 | 保留 |
| 删除 + source | 删除 | 销毁 | 视 tickets | 视 artifacts | 视 knowledge | 视 main_tree | 仅解绑，不删外部目录 |

- 存在未结单工单时，删除默认被 409 拒绝；只有显式 `force` 才能越过。
- 归档是“保留全部数据”的轻动作；删除才是破坏性动作，选项由调用方逐项授权。
- 删除前用 `GET /api/projects/{id}/delete-preview` 查看工单数、未结单列表、交付件体积、
  知识文件数、main 树是否存在。

## 3. 三类“文件”不是包含关系

- **项目文件**：`data/projects/<pid>/main`，项目自己的 git 工作树，是 Agent 在项目里产出的文件。
- **项目源码**：用户绑定的外部源码目录（如 `E:\AI\hive-agent`、`/opt/hive/current`），只读浏览；
  不是项目 main 工作树，也不归 Hive 所有。
- **项目交付件**：`data/artifacts/{public,projects/<pid>,projects/<pid>/tickets/<tid>}` 的归档快照；
  可能来自项目文件或工单工作树，但它是“交付证据”，不是源码，也不是工作树。
- 交集只表示“某个交付件可能由项目文件生成”，职责与生命周期不同；删除项目时分别由
  `main_tree`、`source`、`artifacts` 三个级联开关控制。

## 4. 群聊：系统事件、模块报文、会话消息

- **生命周期事件**（created/starting/git_branch/pm_spawned/role_spawned/merged/closed 等）
  来自 `ticket.history`，现在**始终**进入群聊，显示为 `role=system` 的“系统”消息，
  与 `trace_enabled` 无关。历史工单也能看到“发生过什么”。
- **模块报文**（llm/tool/bus/api 等）只有工单 `trace_enabled=true` 才合并进群聊；
  旧工单 `trace=false` 时，这些报文**没有删除**，仍在 trace 文件/session transcript 里，
  只是不显示。群聊头部会明确显示 `trace off（只有系统事件）`。
- 原始 `role=system` 的模型上下文/系统提示词不会原样展示到群聊：它们是模型输入，
  可能包含内部约束和密钥风险。口径是：系统消息默认 `visible=False`（含 system_prompt），
  只有模块显式写入 `visible=True` 的系统通告才以“系统”身份进入时间线。
  群聊展示的主体是“系统事件”，不是系统提示词全文。

## 5. 流程库

- `library` 启动时 seed 11 个角色插件（architect/developer/...）。
- 代码内置 6 个需求级流程（`kind=process`，带 `nodes/edges`）：
  `project-lifecycle`、`architecture-gate`、`system-timeline`、`project-idle`、
  `requirement-to-flow`、`web-state-contract`。
- 历史审计的 33 条需求已逐条生成 `req-01` … `req-33`（`kind=requirement`），
  存放于 `docs/requirement-flows.json`，随 git 部署；每条都带来源、状态、证据和 DAG。
  需求与流程 id 的对照表见 `docs/requirements-flow-map.md`。
- 旧流程插件只有 `role/checks`，没有 DAG 字段；扫描器把它们视为单节点无环。
- 需求级流程必须写 `nodes/edges`，`python -m hive.archscan` 会检查环；新需求先入库再写代码。

## 6. 门禁

- 本地：`deploy/hooks/pre-push`，安装到 `.git/hooks/pre-push` 后每次 `git push` 自动跑
  `python -m hive.archscan --strict-api`，失败则阻断推送。
- 工单：`tickets.close(force=False)` 先跑同一个架构门禁；失败返回
  `code=arch_gate_failed`，工单不能进入 closing。
- 生产远端：VPS 的 `/opt/hive/repo.git/hooks/pre-receive` 已改为 `--strict-api` 并实测通过。
  生产部署版本 `0.4.7`，HEAD `a613939`（本轮收尾提交会继续前移）。
- `--strict-api` 已是默认门禁：API 环基线为空，任何新环都会直接阻塞推送/部署。
