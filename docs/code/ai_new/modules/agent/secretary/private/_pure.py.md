---
source: ai_new/modules/agent/secretary/private/_pure.py
hash: 5e48d7233c7f15a96a6a24912753823be68b90fcc889e84ee6010aa938677819
symbols:
- empty_state
- _find
- enqueue
- claim_batch
- merge
- to_brief
- mark_merged
- mark_failed
- discard
- queue_view
- status_machine
generated: gen_docs.py v1
updated_at: '2026-11-23T04:10:20'
---

# _pure.py

> 由 `scripts/gen_docs.py` 生成；手改会被下次生成覆盖。
> 职责/入参出参/副作用/依赖/不变量/关联需求由人工在下方补充；生成器只提取 docstring 与符号。

## 概览

项目秘书纯函数：队列成形、批量认领、后发优先合并、回填与失败回滚。

## 符号

### `empty_state`（function）
- 职责: 新建一份空队列状态；路由层在读不到档案时用，纯函数不自带默认数据。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_find`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `enqueue`（function）
- 职责: 入队（幂等）：同一 (project, msg_id) 重复投递回原条目，不新建、不二次建单。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `claim_batch`（function）
- 职责: 原子取整批：全部 pending -> processing，挂同一个 batch_id。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `merge`（function）
- 职责: 后发优先合并：按 at 升序逐条覆盖，同字段后发的非空值覆盖前面的；逐字段留来源 msg_id。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `to_brief`（function）
- 职责: 成形需求结构化 brief：合并结果 + 原文兜底；goal 缺省取最后一条活跃消息原文。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `mark_merged`（function）
- 职责: 建单成功回填：批次条目 -> merged，记工单号与并入时间；批次记录挂工单。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `mark_failed`（function）
- 职责: 失败回滚：批次内 processing 条目全部回 pending，attempts+1、last_error 写入；
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `discard`（function）
- 职责: 撤回一条：pending/processing -> discarded；终态不许翻回。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `queue_view`（function）
- 职责: 视图数据：counts / rows / batches。纯展示成形，文案标签由视图词表映射。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `status_machine`（function）
- 职责: 队列状态机：回包状态枚举、合法迁移；带 entry 时附它当前状态与可去状态。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充
