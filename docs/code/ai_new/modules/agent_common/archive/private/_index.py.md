---
source: ai_new/modules/agent_common/archive/private/_index.py
hash: de2b1dc048db44f62fc8ebcf29969fe1920db60dc941bbce90f696b639a731b3
symbols:
- _empty
- load
- save
- upsert
- get
- all_records
- remove
- query
- stats
- _ratio
- archived_summary
generated: gen_docs.py v1
updated_at: '2026-11-23T04:10:21'
---

# _index.py

> 由 `scripts/gen_docs.py` 生成；手改会被下次生成覆盖。
> 职责/入参出参/副作用/依赖/不变量/关联需求由人工在下方补充；生成器只提取 docstring 与符号。

## 概览

压缩索引：原大小 / 压缩后大小 / 算法 / 时间 / 校验和台账。

## 符号

### `_empty`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `load`（function）
- 职责: 读索引；文件缺失 / 损坏时按空台账收口，不把坏盘静默当成空库之外的状态。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `save`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `upsert`（function）
- 职责: 登记一条压缩记录；返回写入后的整份索引。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `get`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `all_records`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `remove`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `query`（function）
- 职责: 只读查询：按类别 / 年龄过滤，按压缩时间倒序，截断 limit。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `stats`（function）
- 职责: 聚合观测：条数、原始 / 压缩字节、节省空间、按类别拆分。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_ratio`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `archived_summary`（function）
- 职责: 已压缩条目台账汇总：只统计 ``archived``，raw 候选不计入压缩量。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充
