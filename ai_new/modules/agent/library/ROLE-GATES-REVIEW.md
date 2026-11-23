# 岗位门禁整改说明与对照表（第四批 / 第五批）

## 1. 事实源与装配约定

- **唯一事实源**：`library/data/seed.yaml`。内置岗位与流程的 must/forbid、状态机、工具名单、交付件校验全部在此登记。
- **覆盖层镜像**：`roles.yaml` / `flows.yaml` 由 `scripts/sync_library_mirror.py` 从 seed 派生，运行时用户自建条目才写这两个覆盖层；内置条目恒以种子为准，禁止两处各写一份漂移。
- **提示词只写 prose**：`prompts/roles/*.md` 与 `sessions/data/prompts/pm.md` 只写职责与流程叙述；must/forbid 清单段由 `library/private/_pure.py` 的 `flow_contextp` / `stage_blockp` 从数据生成，提示词里不复制第二份清单（测试断言提示词不含 must id、不含待办勾选框）。
- **门禁生效方式**：迁移时 `stage_transitionp` 按当前/源态 `gate.must` 逐项校验，未交齐拒迁（`checklist_unmet`，missing 列出全部 must id）；踩红线拒迁（`forbidden_hit`）。

## 2. 12 岗位 / 流程总对照表

条数均由 seed.yaml 现算（状态数 = 非 ref 门禁状态数；must / forbid 为各状态门禁累计）。

| 岗位 / 流程 | 类型 | 门禁状态数 | must 条数 | forbid 条数 |
| --- | --- | --- | --- | --- |
| pm | 协调岗（ref `requirement-owner`） | 0 | 0 | 0 |
| architect | 架构 | 4 | 6 | 7 |
| developer | 开发 | 6 | 10 | 13 |
| reviewer | 评审 | 3 | 4 | 7 |
| tester | 测试 | 3 | 3 | 6 |
| ops | 运维（ref `ticket-health`） | 0 | 0 | 0 |
| researcher | 调研 | 4 | 4 | 8 |
| writer | 文案 | 4 | 4 | 6 |
| process | 流程专家 | 4 | 4 | 6 |
| skill-decomposer | 拆解者 | 11 | 12 | 20 |
| requirement-owner | 需求归属流程 | 7 | 7 | 14 |
| ticket-health | 健康巡检流程 | 8 | 8 | 14 |

ref 包装节点（pm→requirement-owner、ops→ticket-health）本身不带 gate；子流程状态展开后各自带门禁。

## 3. 逐岗位现实流程与门禁理由

- **architect 架构**：研读约束与边界 → 结构设计 → 方案核对 → 交付。每条关键设计决策须写明依据、备选方案与风险；红线：不直接改业务代码实现、不替测试下验收结论、不把未核对方案当定稿。
- **developer 开发**：理解验收标准 → 拉特性分支 → 实现 → 自验 → CI 门禁 → 评审合并。红线：不直推 master/main、不从过期基线开分支、不跳 CI、不在 CI 未过时推进合并、不自审自合、不 force push、不硬覆盖冲突、不伪造/省略失败测试结果。
- **reviewer 评审**：研读交付件与验收标准 → 逐条评审（通过项 / 缺口项 / 修复建议，标级别与复现步骤）→ 结论落档。红线：不改业务代码、不替开发补实现、不替测试下验收结论、不隐瞒阻塞项。
- **tester 测试**：用例设计（正常/边界/异常/回归，可追溯到标准条目）→ 执行并记录实际结果与证据 → 报告质量结论。红线：不照抄开发自测、不遗漏验收条目、不改被测业务代码、不隐藏或跳过失败用例、不把未跑用例记为通过。
- **ops 运维**：复用健康巡检流程：扫描 → 判定 → 停滞审计 → 根因诊断 → 恢复 / 上抛裁决 → 闭环归档。变更须有回滚触发条件与回滚步骤；不在被审计工单上直接改动其产物绕过诊断。
- **researcher 调研**：界定问题边界与假设 → 多源取证并标注来源 → 比对证据整理一致/冲突/不确定项 → 结论落档。红线：不预设结论、不引用无法核实的来源、不整段贴源码充结论、不把猜测当事实、不丢弃冲突证据。
- **writer 文案**：读素材与事实口径 → 按目标读者成稿 → 校对（事实/口径/错别字/一致性）留记录 → 落档。红线：不编造事实或数据、不引入未核实事实、不跳校对直接交付。
- **process 流程专家**：梳理现状流程/节点/校验规则 → 产出流程配置（节点、边、校验项、触发条件、分支/回退规则、影响面）→ 合规核对 → 交付。红线：不改业务代码、不夹带未声明改动、不把未核对配置当生效。
- **pm 协调**：复用需求归属流程：受理澄清 → 结构化规格 → 编排计划 → 分派拆分 → 执行跟踪 → 验收核对 → 闭环结单。派活只给目标、输入路径、产出路径、验收标准与边界；角色数量克制（默认 2-3 个）；未交付要说清卡点与遗留项，不假装完成。

## 4. skill-decomposer 状态机专章（第五批）

覆盖"外部 skill 包 → 可落地的岗位 / 工具 / 流程"全过程，稳定 id 后续能力线按同一套对接。

### 4.1 状态与门禁 id 对照表

| 状态 id | 名称 | must 条数 | must id | forbid 条数 | forbid 要点 |
| --- | --- | --- | --- | --- | --- |
| sd.intake | 读入包与清单 | 2 | sd.intake.m1、sd.intake.m2 | 2 | 不可信就当可信；臆造包内未声明内容 |
| sd.env | 检查运行环境 | 1 | sd.env.m1 | 2 | 缺运行时强行继续；未探测当成满足 |
| sd.deps | 检查缺失依赖 | 1 | sd.deps.m1 | 2 | 缺依赖当已满足；跳过版本约束直接比对 |
| sd.install | 隔离安装依赖 | 1 | sd.install.m1 | 4 | 无审核执行包内脚本；sudo/提权；进 shell 拼命令；未锁版本直装 |
| sd.analyze | 拆解职责与步骤 | 1 | sd.analyze.m1 | 2 | 只输出描述不产出结构；写无依据步骤 |
| sd.roles | 新增岗位/角色 | 1 | sd.roles.m1 | 2 | 改 builtin 岗位核心红线；绕过登记手写数据 |
| sd.tools | 新增所需工具 | 1 | sd.tools.m1 | 1 | 未登记就写进岗位工具名单 |
| sd.flow | 新增岗位流程 | 1 | sd.flow.m1 | 1 | 无门禁的裸流程入库 |
| sd.verify | 自检与门禁 | 1 | sd.verify.m1 | 1 | 校验失败仍落盘 |
| sd.deliver | 交付 | 1 | sd.deliver.m1 | 1 | 交付无来源/无审计的产物 |
| sd.reject | 拒绝结局 | 1 | sd.reject.m1 | 2 | 隐瞒拒绝原因；拒绝产物混入交付 |

合计：11 态，must 12 条，forbid 20 条。

### 4.2 迁移分支 / 回退 / 拒绝终态

- 缺依赖：`sd.deps` → `sd.install`（存在缺失依赖，待隔离安装）；依赖已满足则 `sd.deps` → `sd.analyze`。
- 安装失败：`sd.install` → 回 `sd.deps`，保留错误；安装成功 → `sd.analyze`。
- 自检不通过：`sd.verify` 按失败项回退 `sd.roles` / `sd.tools` / `sd.flow`；自检全过 → `sd.deliver`。
- 包非法或内容不可信：`sd.intake` / `sd.env` 直接转 `sd.reject` 终态；拒绝原因、非法点与证据留痕归档，拒绝产物不混入交付。
- 终态：`sd.deliver`、`sd.reject`。

### 4.3 必备门禁主题核对

| 环节 | 门禁覆盖点 |
| --- | --- |
| 读入包与清单 | 来源 URL / 版本 / 许可证可追溯；包结构（清单/正文/目录）校验留痕 |
| 运行环境 | 所需运行时 / 命令 / 权限逐项给出探测结果 |
| 缺失依赖 | requirements 与已装清单比对，列出 missing / pinned 与版本约束 |
| 隔离安装 | 隔离环境 + 锁版本 + 来源/许可证/审计日志 |
| 拆解结构 | 职责 / 步骤 / 输入输出 / 验收逐条可核对，标注原文依据 |
| 岗位登记 | 提示词、工具名单、状态机、gate 清单，经 library 校验登记 |
| 工具登记 | schema + deps 登记，可被岗位引用 |
| 流程登记 | 状态 / next / when / gate.must / forbid 齐全，过 library.check |
| 自检 | 契约校验、可被项目引用、幂等重跑不重复 |
| 交付 | 产物清单 + 审计 + 引用位置一并交付 |

## 5. todo 清单同源核查

- **单一强制清单数据源**：seed.yaml 各状态 `gate.must`（稳定唯一 id）。迁移门禁、提示词渲染、前端门禁卡片都从这份数据取数，不存在第二份手写待办清单。
- **运行态 `todos` 字段**：会话记录里模型自排的分步计划，初始为空，经 `todo-write` 需求（`todos.apply` 纯函数）增删查改。测试 `test_gate_must_is_the_single_checklist_source` 断言：岗位/流程记录不另挂 `todos` 清单字段，must id 全库不重复。
- **差异与边界**：todo 工作计划与 gate.must 在设计上分离——gate 是强制门禁（不交齐拒迁），todo 是工作计划。运行态初始 todo 不自动从当前态 gate.must 投影；若后续要求初始待办也按 gate.must 生成，需在会话构建 / 需求层加投影，属运行态代码接线。本批改动边界为 library data / prompts / pm.md / 新测试 / checks.yaml 追加，未改运行态 todo 生成代码。

## 6. 测试与门禁结果

### 6.1 本批通过

- `test_role_gates`：11 项全绿（清单形状、must id 唯一性、镜像与 seed 一致、每态工具含 todo、渲染清单与数据一致、开发/需求流程迁移门禁、ref 展开、拆解者契约与迁移分支、提示词 prose 同源、单数据源断言）。
- `test_boot_graph`：10 项全绿。
- 六门禁：`gate_inventory`、`gate_ops`、`gate_controls`、`gate_views` 通过。

### 6.2 残留失败（另一批 secretary / graph / archive / decompose 接线，不在本批边界）

| 失败用例 | 归属 |
| --- | --- |
| test_all_modules_loaded | 缺 graph / secretary 模块接线 |
| test_registered_routes_are_demand_bound_or_platform | graph.gate_reasons 等路由未绑定需求 |
| test_screen_machine_is_closed | view:secretary 无入边、入口不可达 |
| test_console_shell_is_backend_driven | 菜单分组排序（另一批菜单改动） |
| test_demand_test_map_is_fresh | archive-gc、decompose-* 等需求未绑定用例 |
| test_every_control_has_a_declared_state_machine | row_act 删除 / 恢复控件未在 console.yaml 登记 |
| test_every_registered_route_declares_contract | archive.resolve_raw 缺模块 api.yaml 契约 |
| test_every_demand_is_claimed_by_a_check | archive / decompose / cloud / nodes / sandbox 等需求未被验收清单点名 |
| test_tags_are_registered | secretary 标签未在 tags 登记 |

以上均不涉及岗位 / 流程 / seed 门禁数据；本批未改 web 控件、视图、路由、需求模块及其它业务代码。

## 7. 改动文件与边界

**改动 / 新增**

- `library/data/seed.yaml`：12 岗位/流程门禁与拆解者全过程状态机。
- `library/data/roles.yaml`、`flows.yaml`：脚本派生镜像（勿手改内置条目）。
- `library/data/prompts/roles/*.md`：9 个角色提示词 prose 重写。
- `sessions/data/prompts/pm.md`：卡点 / 遗留项与克制派活口径微调。
- `agent_test/private/test_role_gates.py`：新建门禁契约测试。
- `agent_test/data/checks.yaml`：精确追加 `role-gates` 一条。
- `agent_test/data/demand-tests.md`：`gate_demand_tests.py --write` 脚本刷新。
- `scripts/sync_library_mirror.py`：镜像派生脚本。
- `agent_test/private/stub_llm.py`：桩状态链对齐新契约。

**边界约束（已遵守）**

- 未 commit；未起 8787 端口。
- 未改 `render.js` / `manage.html` / `boot.js` / assets、已有 `view-*.yaml`、`console.yaml`、`.github/` 及其它业务模块。
