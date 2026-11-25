---
source: ai_new/modules/agent_common/demand_engine/private/_lang.py
hash: 92951607ea7fb6f3484e4ccadd8192050296c718985e49351081dbdf417ad061
symbols:
- is_expr
- eval_expr
- _get
- routes_of
- run
- arun
- _mark
- _run_one
- _arun_one
generated: gen_docs.py v1
updated_at: '2026-11-23T04:10:22'
---

# _lang.py

> 由 `scripts/gen_docs.py` 生成；手改会被下次生成覆盖。
> 职责/入参出参/副作用/依赖/不变量/关联需求由人工在下方补充；生成器只提取 docstring 与符号。

## 概览

需求语言：表达式 + 语句 + 解释器。

## 符号

### `is_expr`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `eval_expr`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_get`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `routes_of`（function）
- 职责: 语句树里所有的服务调用（给静态分析和可见性用）。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `run`（function）
- 职责: 同步轨：顺序跑语句树，首个失败立即终止，失败原因留在结果里。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `arun`（function）
- 职责: 异步轨：顺序 await 语句服务调用，首个失败立即终止。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_mark`（function）
- 职责: 记录一条调用：业务失败（ok:false）必须被识别，后续顺序语句随即终止。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_run_one`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_arun_one`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充
