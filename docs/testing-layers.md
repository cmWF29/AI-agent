# 分层门禁与测试金字塔

本文件说明 `scripts/gates.py` 统一入口下各层防什么、怎么单独跑、超时口径、
失败怎么看，以及新增用例往哪里放。既有 `python test_start.py` 与本入口并行存在，
互不吞掉。

## 分层总览

| 层 | 名称 | 防什么风险 | 跑什么 |
|---|---|---|---|
| L0 | 静态/架构/文档/映射 | 控件未登记状态机、指标取数源失真、可点实例缺去向、页面孤岛、条件表达式失效、只读裸奔、需求↔用例映射过期、死代码 | 转调既有六道门禁 + 死代码扫描（`scripts/gate_*.py`） |
| L1 | 后端单元（UT） | 纯函数错误、状态机非法迁移、并发竞争、幂等失效、边界条件 | 转调既有 8 个 unittest 模块（`agent_test/private/test_*.py`） |
| L2 | 接口契约 | 不可信输入打穿、未登录放行、内部路由外泄、越权直调、路径穿越、重复投递双跑 | 真装配 + 真 HTTP 闸，对业务路由跑非法输入矩阵与鉴权/越权/穿越/幂等探针 |
| L3 | 系统级 E2E（ST） | 前后端接线断裂：点按钮没反应、弹窗/表单没加载、提交后列表不更新 | 真浏览器（Chromium/Playwright）+ 真后端，跑“打开项目→新建项目→提交→列表出现→清理” |
| L4 | 韧性 | 进程被杀、写盘中断、租约过期、节点下线、重复投递、恢复后双跑 | 本机多进程模拟，走真实幂等台账 `store.claim/renew/settle/sweep` |

## 怎么单独跑

```bash
# 全量
python3 scripts/gates.py

# 只跑某几层
python3 scripts/gates.py --only L0,L2

# 名单式：L0 挑具体门禁，L1 挑具体模块
python3 scripts/gates.py --only controls,views,test_idem

# 机读 JSON（CI 采集用）
python3 scripts/gates.py --json

# 单层超时（秒），默认 120
python3 scripts/gates.py --timeout 180
```

- 每层独立可跑；某层红不影响其余层出结论。
- L0 各门禁仍是独立子进程，可直接 `python3 scripts/gate_<名>.py`。
- L1 模块仍可经 `python test_start.py --only <check-id>` 跑。

## 超时口径

- `--timeout` 为单层墙钟超时；L0 按门禁逐个计时，L1 按模块计时，L2 按探针计时。
- 探针客户端默认 5 秒响应上限； malformed 输入不许挂死、不许崩成 500。
- 超时记红并在失败摘要里标注「超时未退出」，不静默跳过。

## 失败怎么看

人读汇总按层打印：`[PASS]/[FAIL] 层 · 标题 · 耗时`，随后是每层原始输出与
失败检查项（`!! 检查名 · 依据`）。末尾给总览 `x/y 层通过`。

- 每条失败都附依据链（路由/状态码/取数源/控件 id），不只给一句红。
- `--json` 下结构为 `{ok, layers:[{layer,title,ok,duration,checks,output,note}]}`。
- 先看 L0（结构/映射），再 L1（单元），再 L2（契约）；L3/L4 是最后兜底。

## 新增用例往哪放

- **L0 静态规则**：优先复用 `scripts/lib/scan/`（模块能力图、函数引用图、
  前端控件/状态机图、需求↔测试映射）；新门禁脚本挂在 `scripts/gate_*.py`，
  在 L0 `GATES` 登记。不另建一套扫描解析。
- **L1 后端用例**：按模块放进 `ai_new/modules/agent_test/private/`，
  沿用 `_fixtures.py` 暂存与 `stub_llm.py` 桩；在 `data/checks.yaml` 登记 check。
- **L2 契约探针**：加在 `scripts/lib/layers/l2_contract.py`，按
  路由类补非法输入/鉴权/越权/穿越/幂等用例；不许只 mock 断言。
- **L3 E2E**：`scripts/lib/layers/l3_e2e.py` 起临时服务并转调 `scripts/verify_e2e.py`；浏览器业务闭环直接写这里，不 mock 断言。
- **L4 韧性**：`scripts/lib/layers/l4_resilience.py`，多进程模拟 + 真实幂等台账。

## 与既有 8 个模块的关系

L1 只做转调，不复制断言：

`test_core(124) · test_architecture(29) · test_demands(13) · test_demand_engine(11) ·
test_boot_graph(10) · test_transport(18) · test_idem(11) · test_stub_proto(5)`

既有分组（structure/assembly/language/transport/behaviour/demands）口径不变；
分层入口只是换了一个汇总与筛选口径，不删除、不替换既有模块。
