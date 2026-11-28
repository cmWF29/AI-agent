# ai-agent 仓库总览

稳定入口：先读这一篇拿地图，再按分类读对应文档。不要从目录从头扫。

## 1. 目录与入口

- `agent_start.py`：进程入口，装配交给 `ai_new/modules/agent_common/boot/private/_boot.py`，不写业务分支。
- `test_start.py`：验收入口，`--smoke` 才真正拉起 `agent_start.py`；清单在 `ai_new/modules/agent_test/data/checks.yaml`。
- `ai_new/modules/agent_common/`：公共能力，21 个模块：`api archive boot clock codec config demand_engine exec graph hooks host http llm net ops plat react runtime store tools trace`。
- `ai_new/modules/agent/`：业务能力，19 个模块：`artifacts asr auth channel cloud decompose health knowledge library logs nodes projects sandbox secretary sessions tickets timer todos web`。
- `ai_new/modules/agent_test/`：评审者模块，可 import 运行时模块；运行时不能反向 import 它。
- 根目录只有两个入口；没有 `tests/`、`tools/`、根级 `data/`、根级 `web/`、kernel 包。
- 装配由 `ai_new/modules/agent_common/boot/data/profiles.yaml` 决定，不按目录自动全装。

## 2. 一条需求怎么跑

1. 入口按 `ai_new/modules/agent_common/demand_engine/data/demands/*.yaml` 找需求。
2. 需求 `do` 树顺序 `call` 能力；输入输出显式写在 YAML。
3. 模块返回结果或 effect；需求交给 `runtime.apply` 统一落盘。
4. 异步交接用 `send: hooks.emit`，消费方再起 `runtime.dispatch`；不要在模块里抢跑。
5. 需求自带 `expect`，且必须被 `ai_new/modules/agent_test/data/checks.yaml` 点名。
6. 新增能力：注册路由 → 补 `api.yaml` → 改 `do` 树 → 补 `checks.yaml` → 补门禁。

## 3. 岗位、会话、工单

- 岗位事实源：`ai_new/modules/agent/library/data/seed.yaml`；提示词 `ai_new/modules/agent/library/data/prompts/roles/*.md`。
- 派生镜像 `roles.yaml` / `flows.yaml` 由 `scripts/sync_library_mirror.py` 生成，不手改。
- PM 提示词 `ai_new/modules/agent/sessions/data/prompts/pm.md`，秘书 `.../prompts/secretary.md`。
- 工单落 `ai_new/modules/agent/tickets/data/projects/<project>/tickets/<id>/`；交付件走 artifacts 层。
- 每个角色按阶段挂工具；返工必须显式给起始阶段，否则会回首阶段，可能没有写工具。
- 结单不等于验收；QA 未执行或未复核不能算通过。

## 4. 分门别类读

- 架构原理与设计取舍：`docs/technical-principles.md`
- 模块边界、数据形状、调用顺序、状态迁移、并发与失败处理：`docs/technical-details.md`
- 分层门禁、测试金字塔、各层超时与失败排查：`docs/testing-layers.md`
- 控制台前端规则与页面规格：`docs/frontend-rules.md`
- 部署拓扑、单入口控制面与执行节点：`docs/deploy-topology.md`
- 隔离与分布式状态：`docs/isolation-status.md`
- 知识库分层：`ai_new/modules/agent/knowledge/data/` 下分 `public/`、`projects/`、`tickets/` 三层；`public/repo-context.md` 是开局注入的压缩版，本篇是仓库级详细入口。

## 5. 验证与部署

- 快验：`python3 test_start.py --only structure|language|behaviour`。
- 分层门禁：`python3 scripts/gates.py --only L0,L1,L2 --timeout 900`；默认 120 秒不够。
- 文档同步：`python3 scripts/gen_docs.py` 连跑两次，第二次须输出「代码-文档同步通过」。
- UI：`python3 scripts/verify_ui.py` 是唯一浏览器验收入口；`verify_ui_forms.py` 是表单用例子集。
- UI 清单：改页面规格/`render.js` 后跑 `python3 scripts/ui_inventory.py`。
- 部署：`/opt/ai_new` 上 `bash scripts/deploy.sh`，重启 `hive-ai.service`，探活 `/api/health/live`。

## 6. 常见坑与下一轮

- `artifact_read` 长文会截断，用 `offset`/`limit` 分页；单件 ≤5500 字符，写完自读。
- 返工指定阶段：文档类用 `implement`，QA 报告用 `report`；Tester 的 `design` / `run` / `report` 三阶段现已全部挂 `shell`。
- 项目根不能是 `/`；`root="/"` 会被 `resolve_workspace` 拒绝为 `root_unsafe`。
- 秘书批次号从磁盘最大 `B-xxxx` 续号，避免重启后复用旧幂等键。
- `tool_output_chars=6000` 是硬阈值，超了整段落审计，只回路径。
- 下一轮：补「自然语言入队 → 自动建单 → 开发落盘 → QA 复核 → PM 验收」端到端回归；全量审计历史项目根；按商用标准重跑 L0–L2。
