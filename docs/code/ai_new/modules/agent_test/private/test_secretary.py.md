---
source: ai_new/modules/agent_test/private/test_secretary.py
hash: 42a3ce1fa8acee7bebc3794e2ad5897a62efeb01d34a7860141c81331794a5f2
symbols:
- __call__
- setUpClass
- tearDownClass
- _run
- _project
- _push
- _flush
- _queue
- _ticket_record
- _timer
- _caller
- _project_ticket_ids
- test_batch_merge_three_into_one_ticket
- test_idempotent_repush_and_reflush
- test_failure_preserves_queue_and_shows_error
- test_empty_flush_creates_no_ticket
- test_discarded_message_excluded_from_merge
- test_timer_create_dedup_and_project_scoped_list
- test_timer_forbidden_scope_is_visible
- test_ticket_scope_isolated_within_project
- test_secretary_caller_never_global
- test_timer_notify_enqueue_idempotent_and_merged
- test_spawn_ticket_same_slot_no_duplicate
- test_registered_timer_tools_are_scoped
generated: gen_docs.py v1
updated_at: '2026-11-23T04:10:23'
---

# test_secretary.py

> 由 `scripts/gen_docs.py` 生成；手改会被下次生成覆盖。
> 职责/入参出参/副作用/依赖/不变量/关联需求由人工在下方补充；生成器只提取 docstring 与符号。

## 概览

项目秘书验收：队列、批量合并、后发修正、幂等与失败保留。

## 符号

### `__call__`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `setUpClass`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `tearDownClass`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_run`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_project`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_push`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_flush`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_queue`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_ticket_record`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_timer`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_caller`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_project_ticket_ids`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_batch_merge_three_into_one_ticket`（method）
- 职责: 3 条消息合并成 1 张工单；后发修正覆盖同字段，来源可追溯。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_idempotent_repush_and_reflush`（method）
- 职责: 同 msg_id 重复投递只入队一次；同批次重复 flush 不二次建单。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_failure_preserves_queue_and_shows_error`（method）
- 职责: 建单失败：消息回待处理、attempts+1、last_error 可见，消息不丢、不出队。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_empty_flush_creates_no_ticket`（method）
- 职责: 空队列 flush：不建单、不造批次。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_discarded_message_excluded_from_merge`（method）
- 职责: 撤回的消息不参与合并：只并入未撤回的那条。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_timer_create_dedup_and_project_scoped_list`（method）
- 职责: 同义重复建定时器幂等去重；秘书代理只列本项目，不暴露别的项目。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_timer_forbidden_scope_is_visible`（method）
- 职责: 跨项目写操作被 timer 侧拒绝；返回 forbidden_scope，秘书侧不静默吞掉。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_ticket_scope_isolated_within_project`（method）
- 职责: 同项目内：工单 T1 的定时器对 T2 不可见；T2 写 T1 被拒；T1 可读写自己的。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_secretary_caller_never_global`（method）
- 职责: 秘书侧 caller 只由会话记录构造：project/ticket 作用域，绝不抬到 global。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_timer_notify_enqueue_idempotent_and_merged`（method）
- 职责: timer notify 入队：来源/定时器 id/slot 可见；同 slot 重复投递不丢不重；随批合并进工单。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_spawn_ticket_same_slot_no_duplicate`（method）
- 职责: spawn_ticket 同槽位重复触发不重复建单（工单内容一致走建单幂等）。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_registered_timer_tools_are_scoped`（method）
- 职责: 定时器工具登记给 pm/secretary；参数含周期/标题；project 由会话上下文注入。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充
