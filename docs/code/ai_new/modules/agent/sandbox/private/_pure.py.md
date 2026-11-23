---
source: ai_new/modules/agent/sandbox/private/_pure.py
hash: 8cc9e3c1f43ca3e368070d4cfdbaec9ff27ed2b51cd7b1ed82484c994a3962c6
symbols:
- describe
- _root_segments
- validate_root
- pick_tier
- plan
generated: gen_docs.py v1
updated_at: '2026-11-23T04:10:20'
---

# _pure.py

> 由 `scripts/gen_docs.py` 生成；手改会被下次生成覆盖。
> 职责/入参出参/副作用/依赖/不变量/关联需求由人工在下方补充；生成器只提取 docstring 与符号。

## 概览

隔离档位策略纯计算：轻/强两档描述、切换条件、资源开销、执行计划。

## 符号

### `describe`（function）
- 职责: 两档描述 + 条件 + 开销表（只读策略数据，不含本机探测结果）。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_root_segments`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `validate_root`（function）
- 职责: 项目根路径校验：必须绝对、无 .. 穿越片段。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `pick_tier`（function）
- 职责: 按策略选择档位。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `plan`（function）
- 职责: 生成执行计划（纯计划，不起进程、不写盘）。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充
