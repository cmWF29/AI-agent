# 100% 行 + 分支覆盖率 Todolist

口径：**全局行 100% / 分支 100%，全量用例、全量门禁；开发阶段不为每个中间提交跑门禁，最后一次性过。**
依据：`docs/testing-layers.md`（L0–L5 分层）、`docs/technical-principles.md`（中央编排/纯函数/效果清单/平台边界）、`ROADMAP.md`（trace 与平台收敛方向）。

## A. 门禁与文档先对齐

- [x] `scripts/coverage.json`：整体行/分支、关键模块、改动行全部改为 100。
- [x] `scripts/gate_coverage.py`：100% 口径下逐文件输出“仍缺 N 行 / N 分支”。
- [x] `docs/testing-layers.md`：阈值段落改为 100/100，模块数改 39，并补“平台矩阵合并”口径。
- [x] `docs/technical-principles.md`：改为“100% 是唯一门槛，关键机制优先但不豁免”。
- [ ] Windows job 增加 coverage 产物，与 Linux 合并成一份平台矩阵覆盖率；跨平台互斥分支不再靠单端硬凑。
- [ ] `gate_diff_coverage.py` 的 100% 口径回归自测（新增/改动行不全覆盖必须红）。

## B. 一次性盘点，不再逐步跑门禁

- [x] 发现并接回从未进 runner 的测试模块：`test_asr`、`test_platform_branches`（`test_stub_faults` 挂死，待修后再接）。
- [x] 全量 39 模块 + `--branch` coverage 跑出基线：38 个已接回模块 0 失败，耗时 1600.77s。
- [x] 生成逐文件 `missing_lines / missing_branches` 清单：99 个文件有缺口，`docs/reports/coverage-gaps.md`。
- [ ] 标记“平台互斥”“故障注入才可达”“结构性不可达”三类，分别用矩阵测试/故障测试/纯函数拆分解决，禁止 `pragma` 掩盖。

## C. 代码缺陷批量修

- [x] cloud：已存在 profile 更新时允许不重填凭证，沿用旧密封凭证。
- [x] cloud：同步台账 `failed` 字段被列表覆盖，拆成 `failed_count` + `failed` 明细。
- [x] projects：未知岗位 id 写入项目覆盖层，入口层校验公共库 + 用户层岗位集合。
- [ ] tickets：归档/结单/子单上限等路由错误分支逐条补测并修裸露异常。
- [ ] store：原子替换、Windows 退避重读、越界/未知路径分支补测。
- [ ] archive：压缩索引/孤儿/损坏档案恢复分支补测。
- [ ] decompose：需求拆分失败、空任务、依赖成环分支补测。
- [ ] api/http：断连、SSE 写失败、畸形报文、未知路由分支补测。
- [ ] library：岗位/流程/技能覆盖层与内置保护全部错误分支补测。
- [ ] plat：Windows Job/lock/net/rsync 分支改为可注入后端，在 Linux 也能真实执行。

## D. 测试批量补到 100%

按文件缺口从大到小分批，每批只跑定向模块，不跑全量门禁：

- [ ] `agent/cloud/__init__.py`、`_providers.py`、`_webdav.py`、`_s3.py`
- [ ] `agent/tickets/__init__.py`、`_pure.py`
- [ ] `agent_common/store/private/_panel.py`、`_files.py`、`_isolate.py`
- [ ] `agent_common/archive/private/_engine.py`、`_index.py`、`_backend.py`
- [ ] `agent/decompose/__init__.py`、`_pure.py`
- [ ] `agent_common/api/private/_transport.py`、`_serve.py`、`_registry.py`
- [x] `agent/library/private/_pure.py`：行覆盖 100%，分支 98.8%，剩 12 条不可达/模板空值分支。
- [ ] `agent_common/plat/private/_winjob.py`、`_lock.py`、`_net.py`
- [ ] `agent_common/boot/private/_graph.py`、`_boot.py`
- [ ] `agent_common/tools/__init__.py`、`_registry.py`、`_pure.py`
- [ ] `agent/sessions/__init__.py`、`_pure.py`、`_run_pure.py`
- [ ] `agent/nodes/__init__.py`、`_pure.py`
- [ ] `agent/knowledge/__init__.py`、`_pure.py`
- [ ] `agent_common/demand_engine/private/_engine.py`、`_lang.py`
- [ ] `agent_common/trace/private/_trace.py`
- [ ] `agent/projects/__init__.py`、`_pure.py`
- [ ] `agent/timer/__init__.py`、`_pure.py`
- [ ] `agent/secretary/__init__.py`、`_pure.py`
- [ ] `agent/asr/private/_engine.py`、`_pure.py`
- [ ] 其余 <50 行缺口文件收尾

## E. E2E 扩容

- [ ] HTTP 黑盒从 24 条扩到 30+：项目权限、工单多轮、知识归档、云连通/往返、定时器真实触发、公开只读入口。
- [ ] 浏览器 E2E 从 4 条扩到 8 条：知识库打开/版本、权限启停、归档后全链路只读、多角色多轮。
- [ ] 视觉回归补知识/权限视图基线，仍用独立端口与固定字体。
- [ ] 性能门禁保持 p95/p99/RPS，补一次真实突发回归。

## F. 最终收口

- [ ] 全量 39 模块 0 失败（最近一次 38 模块 0 失败，`test_pure_edges` 接入后待重跑）。
- [ ] `gate_coverage.py` 100% 通过（逐文件缺口为 0）。
- [ ] `gate_diff_coverage.py` 100% 通过。
- [ ] L0–L4 全绿，HTTP E2E / 浏览器 E2E / 视觉 / 性能全绿。
- [ ] `gen_docs.py` 连跑两次通过，`code-docs.json` 与 docs 入库。
- [ ] Linux + Windows 两个 CI job 全绿，平台矩阵 coverage 合并后 100%。
- [ ] 推送并确认 CI run 成功，再对外说完成。

## G. 阶段记录

1. **runner 缺陷修复**：`TimeoutExpired` 的 bytes/stdout 直接相加会让 runner 自身抛 `TypeError`，超时模块永远报不出来；已统一解码。每个分片的暂存目录原先从不回收，全量跑会把 `/tmp` inode 打满；已在 `finally` 里 `rmtree`，单模块知识并发用例从挂死 15 分钟回到 2.1s。
2. **基线**：38 个模块 0 失败，整体行 83.04%（12679/14770）、分支 75.10%（3911/5208）；旧基线为 80.22%/71.87%。
3. **library 纯函数**：新增 `test_pure_edges` 22 组用例，`_pure.py` 行覆盖从 82.7% 到 100%；同时删掉 `_records` 里永远不可达的“用户覆盖种子”分支。
