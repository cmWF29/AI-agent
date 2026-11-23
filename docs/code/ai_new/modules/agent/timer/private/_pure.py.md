---
source: ai_new/modules/agent/timer/private/_pure.py
hash: d9ccbb4971e270d34836b9d698abbc099423e25823d70f23882bbb5176d416cb
symbols:
- normalize_caller
- idem_signature
- validate_shape
- validate_spec
- quota_check
- authorize
- filter_scope
- due_select
- run_record
- last_run_view
- view_row
- view_rows
- project_groups
- index_stats
generated: gen_docs.py v1
updated_at: '2026-11-23T04:10:21'
---

# _pure.py

> 由 `scripts/gen_docs.py` 生成；手改会被下次生成覆盖。
> 职责/入参出参/副作用/依赖/不变量/关联需求由人工在下方补充；生成器只提取 docstring 与符号。

## 概览

定时器纯函数：规格校验、配额、幂等键、槽位挑选、审计条目与视图成形。

## 符号

### `normalize_caller`（function）
- 职责: 调用方上下文归一：缺省按项目作用域；scope 不由模型随意抬到 global。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `idem_signature`（function）
- 职责: 幂等键原始串：项目|标题|类型|表达式|时区|动作|工单|岗位。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `validate_shape`（function）
- 职责: 必填与枚举形状校验；表达式/时区/间隔的时刻校验归 clock.schedule_next。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `validate_spec`（function）
- 职责: 规格校验收口：形状 + clock 推算结果 → next_at 或错误码。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `quota_check`（function）
- 职责: 项目内配额：在档定时器数 ≥ 上限 → quota_exceeded。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `authorize`（function）
- 职责: 作用域裁决：project 管本项目；ticket 再加工单相等；global 放行跨项目。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `filter_scope`（function）
- 职责: 按作用域过滤可见记录：global 全量，project/ticket 各自收口。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `due_select`（function）
- 职责: 挑出未执行过的到期槽位，受 max_catchup 上限截断；同槽位重复 tick 不重复触发。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `run_record`（function）
- 职责: 执行审计条目：成功/失败都留痕；失败保留槽位待重试，attempt 累加回退。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `last_run_view`（function）
- 职责: 最近一次结果视图形状：at/ok/detail/attempt。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `view_row`（function）
- 职责: 列表给 UI 的字段（契约 §10.2）。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `view_rows`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `project_groups`（function）
- 职责: 按项目分组的调度概览：项目是定时器的作用域，不是表格里一列就完事。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `index_stats`（function）
- 职责: 聚合统计：活动/暂停/本日触发。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充
