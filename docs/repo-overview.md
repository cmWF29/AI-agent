# ai-agent 仓库总览

给后续 agent 的稳定入口：先读这一篇拿到全局地图，再按指针读原文。结论以当前 master 实测为准，证据路径均相对仓库根。

## 1. 入口与目录

- `agent_start.py`：进程入口，只把装配交给组合根 `ai_new/modules/agent_common/boot/private/_boot.py`，不写业务分支。
- `test_start.py`：验收入口，`--smoke` 才真正拉起 `agent_start.py`；清单在 `ai_new/modules/agent_test/data/checks.yaml`。
- `ai_new/modules/agent_common/`：公共能力，21 个模块：`api archive boot clock codec config demand_engine exec graph hooks host http llm net ops plat react runtime store tools trace`。
- `ai_new/modules/agent/`：业务能力，19 个模块：`artifacts asr auth channel cloud decompose health knowledge library logs nodes projects sandbox secretary sessions tickets timer todos web`。
- `ai_new/modules/agent_test/`：评审者模块，可 import 运行时模块；运行时不能反向 import 它。
- 根目录只有两个入口，没有 `tests/`、`tools/`、根级 `data/`、根级 `web/`、kernel 包。
- 模块形状：公开 `__init__.py` 只做注册与转调，实现在 `private/`，数据在 `data/`。
- 装配由 `ai_new/modules/agent_common/boot/data/profiles.yaml` 决定，不是靠目录名自动全装。

## 2. 核心模块职责

- `demand_engine`：需求引擎。只装载、路由、解释 `data/demands/*.yaml` 的 `do` 树，不认识业务名词。
- `api`：模块间唯一通道。`ctx.api.call(name, payload, caller)` 走注册表；跨模块直调要登记 `ai_new/modules/agent_common/api/data/internal-calls.yaml`。
- `store` / `codec` / `artifacts`：存储、编码、分层交付件路径。交付件写入/读取在 `artifacts-*` 需求里，能力只在模块里算。
- `library`：岗位与流程的纯计算。事实源 `ai_new/modules/agent/library/data/seed.yaml`，派生镜像 `roles.yaml` / `flows.yaml`，由 `scripts/sync_library_mirror.py` 生成，不手改。
- `sessions`：会话、上下文装配、阶段状态机、工具裁剪。PM 提示词在 `ai_new/modules/agent/sessions/data/prompts/pm.md`，秘书在 `.../prompts/secretary.md`。
- `tickets`：工单记录与编排。工单落 `ai_new/modules/agent/tickets/data/projects/<project>/tickets/<id>/`。
- `web`：控制台只认注册表和需求清单，页面规格读 `ai_new/modules/agent_common/demand_engine/data/console.yaml` 与 `.../data/demands/view-*.yaml`。
- `react`：单轮工具循环；大输出会落审计日志，只回摘要和路径。
- `hooks` / `runtime`：事件发射与 effect 执行；需求算 effect，`runtime.apply` 统一写盘。

## 3. 一条需求怎么跑

1. 入口收到请求，按 `demands/*.yaml` 找需求。
2. 需求 `do` 树顺序 `call` 能力；每个 `call` 的输入输出都显式写在 YAML 里。
3. 模块返回结果或 effect；需求最后把 effect 交给 `runtime.apply` 落盘。
4. 需要异步交接时，用 `send: hooks.emit` 发事件，消费方再起下一次 `runtime.dispatch`；不要在模块里直接抢跑。
5. 需求自带 `expect`（given/calls/payload），且必须被 `ai_new/modules/agent_test/data/checks.yaml` 点名。
6. 新增能力：注册路由 → 补 `api.yaml` → 改需求 `do` 树 → 补 `checks.yaml` → 补门禁。

## 4. 岗位、会话、工单的数据流

- 岗位事实源：`ai_new/modules/agent/library/data/seed.yaml`；岗位提示词 `ai_new/modules/agent/library/data/prompts/roles/*.md`。
- 会话：PM 收到工单后先用 `prompt_read`/`prompt_patch` 固口径，再计划 AC1..ACn 到 `docs/pm/plan.md`，用 `role_spawn`/`role_task` 派角色。
- 阶段：每个角色有状态机；每个阶段只挂该阶段工具。返工要显式给起始阶段，否则会回到首阶段，可能没有写工具。
- 工单：ticket 层存计划、交付件、QA；project 层存跨工单资料；public 层存可复用知识。
- 结单：PM 按 AC 逐条核验，QA 未执行或未复核不能算通过；`closed` 不等于 `accepted`。

## 5. 架构哲学与风格

1. 能力在模块，业务在数据。模块只提供服务和扩展点，业务写在需求 YAML。
2. 模块无特权，只留 hook。`setup(ctx)` 只注册路由，不藏业务分支。
3. 结构可静态读出。需求里所有服务调用都在 `call` 字段，既能跑，也能被扫描。
4. 纯函数优先。`*p` 表纯函数，`private/` 表实现；取数、写盘放边界。
5. 前端不写字面量。控件、文案、菜单从后端词表和页面规格来。
6. 审计单向。`agent_test` 可看运行时，运行时不可反向依赖测试。

## 6. 验证、门禁、部署

- 快验：`python3 test_start.py --only structure|language|behaviour`。
- 分层门禁：`python3 scripts/gates.py --only L0,L1,L2 --timeout 900`。默认 120 秒不够，L1 整层约 10 分钟。
- 代码文档：`python3 scripts/gen_docs.py` 连跑两次；第二次必须输出「代码-文档同步通过」。
- UI：`python3 scripts/verify_ui.py` 是唯一浏览器验收入口；`verify_ui_forms.py` 是表单用例子集，不是独立入口。
- 清单：改 `render.js`/页面规格后跑 `python3 scripts/ui_inventory.py`，否则 L0 的 inventory 签名会过期。
- 岗位镜像：改 `seed.yaml` 后跑 `python3 scripts/sync_library_mirror.py`。
- 部署：VPS `/opt/ai_new`，`bash scripts/deploy.sh` 会 fetch、reset 到 `origin/master`、重启 `hive-ai.service`、探活 `/api/health/live`。

## 7. 常见坑

- `artifact_read` 一次读长文会截断；用 `offset`/`limit` 分页，单件交付控制在 5500 字符内，写完自读确认。
- 给已有角色返工，必须显式指定阶段；文档类返工用 `implement`，QA 报告用 `report`，否则阶段工具集不匹配。
- 项目根不能是 `/`；根路径会被 `resolve_workspace` 拒绝为 `root_unsafe`，项目根要落到具体目录或空串走 legacy。
- 秘书批次号从磁盘最大 `B-xxxx` 续号；否则进程重启后会复用旧幂等键，新消息不建单。
- `tool_output_chars=6000` 是硬阈值，超了整段落审计，只回路径，不要把路径当交付件。
- `ticket-get` / `ticket-thread` 用 `id` + `project`；传 `ticket` 会 200 但返回 null。

## 8. 下一轮优先项

1. 把总览从 ticket 层提升到仓库稳定入口：本篇即入口，后续改动直接更新这里。
2. QA 复核要同时具备 shell 与 artifact_write；已补 `tester.report` 阶段工具，需用真实工单复验。
3. 开发在 `understand` 阶段没有写工具；返工必须带 `stage=implement`，避免“读完了但写不了”。
4. 补一条端到端回归：自然语言入队 → 自动建单 → 开发落盘 → QA 复核 → PM 验收。
5. 全量审计历史项目根，清掉不可用的 `root="/"`。
6. 按商用标准重跑 `gates.py --only L0,L1,L2 --timeout 900` 后再收口。

## 9. 读法

- 先读本篇第 1-4 节拿地图；要改某条需求，读对应 `ai_new/modules/agent_common/demand_engine/data/demands/<id>.yaml`。
- 要动岗位/提示词，读 `seed.yaml` + `prompts/roles/*.md`，再跑镜像同步。
- 要动前端，读 `console.yaml`、`view-*.yaml`、`web/data/console/`，再跑 UI 清单和 `verify_ui.py`。
- 跨模块调用先查 `internal-calls.yaml`，再走 `ctx.api.call`。
