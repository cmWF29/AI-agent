# Hive Agent 架构与门禁说明（v4.5 重构起点）

> 这份文档不是事后说明，而是门禁的一部分：`python -m hive.archscan --report` 会生成
> `docs/architecture/arch-report.json` 与 `arch-report.md`，记录模块出口、API 依赖、
> 流程 DAG、网页状态机的一致性。改代码前先看报告，改完必须让门禁重新通过。

## 1. 后端：一个模块一个唯一出口

- 每个模块的唯一出口是 `hive/modules/<name>.py`，模块之间没有 Python `import`。
- 对外能力只有两类：`self.api.route(...)` 注册的 HTTP/内部 API，以及
  `Tool(...)` 注册的 Agent 工具；其余函数按内部实现处理。
- 跨模块调用统一走 `ctx.api("module.method", ...)`，扫描器据此生成模块 API 依赖图。
- 门禁硬错误：跨模块 import、import 环、网页契约错误、流程 DAG 环、**基线之外的新 API 环**。
- API 环基线在 `docs/architecture/api-cycles-baseline.json`。当前只剩 3 条已登记债务：
  `projects <-> tickets`、`sessions -> projects -> tickets -> sessions`、
  `idle -> sessions -> projects -> tickets -> idle`。本轮已拆掉
  `sessions <-> projects`（项目秘书改由 `project.delete.before` 同步事件清理）和
  `artifacts <-> tickets`（压缩只读归档 index 的 `closed`，不再查工单状态）。
- 新代码如果引入未登记环，默认门禁直接失败；`--strict-api` 则把所有环（包括基线）
  升级为阻塞。拆掉一条边后必须同步删除基线项，不能把基线当永久豁免。

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
  可能包含内部约束和密钥风险；群聊展示的是“系统事件”，不是系统提示词全文。

## 5. 流程库

- `library` 启动时 seed 11 个角色插件（architect/developer/...）。
- v4.5 新增 6 个需求级流程（`kind=process`，带 `nodes/edges`）：
  `project-lifecycle`、`architecture-gate`、`system-timeline`、`project-idle`、
  `requirement-to-flow`、`web-state-contract`。
- 旧流程插件只有 `role/checks`，没有 DAG 字段；扫描器把它们视为单节点无环。
- 需求级流程必须写 `nodes/edges`，`python -m hive.archscan` 会检查环；新需求先入库再写代码。

## 6. 门禁

- 本地：`deploy/hooks/pre-push`，安装到 `.git/hooks/pre-push` 后每次 `git push` 自动跑
  `python -m hive.archscan`，失败则阻断推送。
- 工单：`tickets.close(force=False)` 先跑同一个架构门禁；失败返回
  `code=arch_gate_failed`，工单不能进入 closing。
- 生产远端：VPS 的 `/opt/hive/repo.git/hooks/pre-receive` 已安装并实测通过（对
  `430c564..8333a60` 的 tree 跑同一扫描器）。生产部署后版本为 `0.4.5`，HEAD `8333a60`。
- `--strict-api` 是下一阶段的严格模式：解决 API 环后再打开，才能把“API 依赖也是 DAG”
  变成真正的硬约束。
