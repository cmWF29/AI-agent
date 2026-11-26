# 分层门禁与测试金字塔

本文件说明 `scripts/gates.py` 统一入口下各层防什么、怎么单独跑、超时口径、
失败怎么看，以及新增用例往哪里放。既有 `python test_start.py` 与本入口并行存在，
互不吞掉。

## 分层总览

| 层 | 名称 | 防什么风险 | 跑什么 |
|---|---|---|---|
| L0 | 静态/架构/文档/映射 | 控件未登记状态机、指标取数源失真、可点实例缺去向、页面孤岛、条件表达式失效、只读裸奔、需求↔用例映射过期、表单/需求/API 参数断线、死代码 | 转调 L0 门禁 + 死代码扫描（`scripts/gate_*.py`） |
| L1 | 后端单元（UT） | 纯函数错误、状态机非法迁移、并发竞争、幂等失效、边界条件 | 转调 `agent_test/private/test_*.py` 下的 39 个 unittest 模块，含 React 流程/清单/逐轮压缩机制专项 |
| L2 | 接口契约 | 不可信输入打穿、未登录放行、内部路由外泄、越权直调、路径穿越、重复投递双跑 | 真装配 + 真 HTTP 闸，对业务路由跑非法输入矩阵与鉴权/越权/穿越/幂等探针 |
| L3 | 系统级 E2E（ST） | 前后端接线断裂：点按钮没反应、弹窗/表单没加载、提交后列表不更新、归档后仍可新建、行内动作被后端守卫静默拒绝 | 真浏览器（Chromium/Playwright）+ 真后端：自动发现并巡检全部视图与弹窗表单；`verify_e2e.py` 七个场景全进闸：项目建→改名→归档→删除、工单建→发消息→回复→结单、同单两轮追问逐轮收口（每轮 composer 回可用）、归档后新建工单入口不可用、定时器页面真实按钮（改表达式弹窗→暂停→恢复→删除，含禁用门槛）、多岗位协作（PM 先发一轮→派发 developer→群聊两路各自署名不串名→成员卡写出各自会话→结单回收） |
| L4 | 韧性 | 进程被杀、写盘中断、租约过期、节点下线、重复投递、恢复后双跑 | `scripts/resilience_drill.py`：真实 SIGKILL + 6 进程并发 + 真实幂等台账 `store.claim/renew/settle/sweep` |
| L6 | HTTP 黑盒业务 E2E（ST） | 接口单测绿但真实 HTTP 全链路断：壳层协议、鉴权/越权、并发建删、版本冲突、级联只读、上游炸了却假成功 | `scripts/verify_api_e2e.py` 26 个场景经真实 HTTP 打真装配（端口取自引导结果，不写死 8787）：项目改名与工单引用改挂、知识版本/追加作用域、定时器到点真建单、节点申领、12 路并发、多岗位并发不串扰、拆单上限、结单级联只读与会话回收、交付件越界、405/404/坏 YAML/ETag 304；另含真网络降级演练：上游 500 回 9 次真请求后回到 idle 且不伪造回复、上游恢复后同一服务自动可用、上游端口断连只降级不挂死 |
| L7 | 运维韧性 E2E（ST） | 内存里都对、盘上没有；重启丢历史；换机器搬不动；上游只接不回导致会话挂死 | `scripts/lib/layers/l7_ops.py` 真目录真停服：落盘断言（项目/工单/会话记录/日志索引/知识/定时器审计逐项核对内容）、停服后用同一份数据目录重装（旧端口必须拒绝连接、条数不减且本轮原文仍读得到、定时器/知识还在、能接着写且真落盘；事件队列文件落盘）、整树复制到新根（内容一致、新根可写、旧根不被污染）、上游接受连接但永不应答（限时回 idle、不伪造回复、降级后仍可接单）、cron `* * * * *` 不经接口由后台扫描线程自己到点建单且槽位落盘 |
| L5 | 覆盖率 | 用例跑绿但核心机制根本没被执行；只测表层入口 | `coverage run --branch` + `scripts/gate_coverage.py`：整体行/分支 100% + 关键模块（react/sessions/todos/library）单独 100%；另由 `gate_diff_coverage.py` 强制 base..HEAD 改动行 100% |

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
- **L1 边界用例**：`test_security_boundaries.py` 覆盖令牌字符集、空摘要、缺失过期时间、改密旧摘要、bwrap 虚拟路径逃逸、ASR 非法分块与音频类型、静态资源门槛、编解码/LLM 报文形状、登录节流键与台账、工单入参类型与长度；`test_core` 覆盖 GET 只读、匿名 allowlist、请求体上限、chunked 拒绝、安全响应头、登录节流真实往返与 peer 注入覆盖；check id `boundaries`、`http-gate`、`auth-throttle`。
- **L2 契约探针**：加在 `scripts/lib/layers/l2_contract.py`，按
  路由类补非法输入/鉴权/越权/穿越/幂等用例；不许只 mock 断言。
- **L3 E2E**：`scripts/lib/layers/l3_e2e.py` 起临时服务并转调 `scripts/verify_pages.py` 与 `scripts/verify_e2e.py`；页面/表单从后端 `views-list` 动态发现，浏览器业务闭环直接写这里，不 mock 断言。
- **L7 运维韧性 E2E**：`scripts/lib/layers/l7_ops.py` 只用真目录与真进程演四件事：落盘、停服重启、换根迁移、上游挂起。会话记录是追加型日志：标 running、轮内检查点、收尾写回三处都要把「快照之后人插进来的发言」补回（`_run_pure._merge_tail/_with_later`、`react/_pure._merge_tail/_keep_appended`），否则运行中发言会被旧快照整段覆盖。`_bootstrap.boot(root=...)` 支持原地复用同一份数据目录（重启/迁移的唯一真做法），`stub_net=False` 保留真 socket；cron 到点触发不给接口后门，只等后台 `timer-tick` 线程自己跑。断言一律读盘（项目 yaml、工单 yaml、`agent/logs/index.yaml`、会话记录、知识 md、`agent/timer/audit.jsonl` 与 `timers.yaml` 的 fired 槽位），不读内存返回值。
- **L6 黑盒 E2E**：`scripts/lib/layers/l6_blackbox.py` 引导真装配后转调 `scripts/verify_api_e2e.py`（26 场景），逐场景 OK/FAIL 翻成层内检查项；新增业务闭环写进脚本 `SCENARIOS` 即自动进闸，端口一律取引导结果（写死 8787 会在临时端口装配里假红）；客户端形如「上游 5xx/断连」的项由本层自己起会翻脸的真上游（`stub_net=False`），被判「不挂死、不伪造回复、恢复后可用」，不允许用进程内打桩冒充。
- **L4 韧性**：`scripts/lib/layers/l4_resilience.py` 转调 `scripts/resilience_drill.py`；真实 SIGKILL、6 进程并发抢键、租约 sweep、恢复不双跑，子进程独立 `AI_NEW_DATA`，不碰源码树。

## 覆盖率门禁

```bash
# 全量用例在 coverage 下跑，产物写到 /tmp/hive.coverage
cd ai_new/modules/agent_test/private
python3 -m coverage run --rcfile=../../../../scripts/coverage.ini --branch --data-file=/tmp/hive.coverage \
  --source="$(cd ../../../.. && pwd)/ai_new/modules" -m unittest <模块列表>
cd ../../../..
python3 scripts/gate_coverage.py --data-file /tmp/hive.coverage
```

- 阈值在 `scripts/coverage.json`：整体行 100%、分支 100%，关键模块行 100%、分支 100%，改动行 100%；
- 平台互斥分支按 Linux + Windows 两端 coverage 合并计覆盖，不能用单端 `pragma` 或排除模块凑数；
- 测试代码与前端静态资源不计入；
- 没有数据文件直接红，不允许「没跑 coverage 但当作通过」；
- 100% 不等于允许执行过一行就完：关键机制用例必须断言行为，线覆盖与分支覆盖都要有真实输入驱动。

改动行门禁：

```bash
python3 scripts/gate_diff_coverage.py --data-file /tmp/hive.coverage
```

- base 取 CI 的 `GITHUB_BASE_SHA`，本地回退 `HEAD^`；找不到 base 直接红；
- 只统 `ai_new/modules` 下产品 Python 新增行，测试与前端资源不计；
- 可执行性由 coverage 的 executed/missing 判定，阈值读 `coverage.json` 的 `changed_line`（90%）；
- 文件在报告里但新增行都不可执行时按通过；新增文件完全未进 coverage 报告直接红。

## 与既有模块的关系

L1 只做转调，不复制断言：

`test_core(129) · test_architecture(29) · test_demands(13) · test_demand_engine(11) ·
test_boot_graph(10) · test_transport(18) · test_idem(11) · test_stub_proto(5)`

既有分组（structure/assembly/language/transport/behaviour/demands）口径不变；
分层入口只是换了一个汇总与筛选口径，不删除、不替换既有模块。
