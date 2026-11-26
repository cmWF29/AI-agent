---
source: ai_new/modules/agent_test/private/test_timer.py
hash: a0f96891aa32a826838b5a603da131a657ced0197b015819a1ec28e893b240eb
symbols:
- _future_iso
- setUpClass
- tearDownClass
- _stub_push
- _stub_tickets
- _apply
- _create
- _project_caller
- _ticket_caller
- _global_caller
- _audit_rows
- _records
- _tick
- test_create_once_next_at_and_view_row
- test_create_cron_next_at
- test_tick_notify_pushes_to_secretary_queue
- test_tick_spawn_ticket_creates_ticket_with_meta
- test_spawn_ticket_uses_payload_title_and_goal
- test_idempotent_create_returns_original_id
- test_cross_project_read_write_delete_forbidden
- test_cross_ticket_forbidden_and_same_ticket_rw
- test_project_secretary_manages_all_timers_in_project
- test_quota_exceeded
- test_pause_resume_delete
- test_bad_cron_bad_tz_rejected
- test_failure_preserved_visible_and_retryable
- test_index_groups_by_project
- test_history_rejects_cross_scope
- __call__
generated: gen_docs.py v1
updated_at: '2026-11-23T04:10:23'
---

# test_timer.py

> 由 `scripts/gen_docs.py` 生成；手改会被下次生成覆盖。
> 职责/入参出参/副作用/依赖/不变量/关联需求由人工在下方补充；生成器只提取 docstring 与符号。

## 概览

定时器验收：调度推算、notify/spawn_ticket 两路触发、幂等、作用域隔离与审计。

## 符号

### `_future_iso`（function）
- 职责: 相对当前 UTC 时刻的 ISO 时间（秒后），供 once 表达式使用。
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

### `_stub_push`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_stub_tickets`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_apply`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_create`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_project_caller`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_ticket_caller`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_global_caller`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_audit_rows`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_records`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_tick`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_create_once_next_at_and_view_row`（method）
- 职责: once 建单：下次触发时刻落档，列表行字段齐全。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_create_cron_next_at`（method）
- 职责: cron 建单：每天九点的规则推算出下次触发分钟。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_tick_notify_pushes_to_secretary_queue`（method）
- 职责: 到期 notify：秘书队列收到幂等 msg_id，字段带来源 timer/timer_id/slot。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_tick_spawn_ticket_creates_ticket_with_meta`（method）
- 职责: 到期 spawn_ticket：建工单，meta 记 source=timer/timer_id/slot，同槽位不重复建。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_spawn_ticket_uses_payload_title_and_goal`（method）
- 职责: payload 里显式声明的 title/goal 要生效：这是入参，不是摆设。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_idempotent_create_returns_original_id`（method）
- 职责: 同义重复创建：返回原 id 且 deduped=true，只落一条记录。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_cross_project_read_write_delete_forbidden`（method）
- 职责: 项目秘书跨项目：读取/修改/删除一律 forbidden_scope，且各留 deny 审计。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_cross_ticket_forbidden_and_same_ticket_rw`（method）
- 职责: 工单岗位：同项目其他工单的定时器不可见不可改；本工单可读写。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_project_secretary_manages_all_timers_in_project`（method）
- 职责: 项目秘书可管本项目全部工单下的定时器；global 可跨项目查看。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_quota_exceeded`（method）
- 职责: 超量创建 → quota_exceeded，deny 审计留痕。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_pause_resume_delete`（method）
- 职责: 暂停 → 恢复 → 删除：状态翻转落档，allow 审计齐全。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_bad_cron_bad_tz_rejected`（method）
- 职责: 非法表达式 → bad_cron；非法时区 → bad_tz。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_failure_preserved_visible_and_retryable`（method）
- 职责: 触发失败：last_run 留可见错误、attempts 累加、槽位保留；恢复后可重试成功。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_index_groups_by_project`（method）
- 职责: 定时器总览必须按项目分组，而不是只在表格里放一列项目名。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_history_rejects_cross_scope`（method）
- 职责: history 同样受作用域守卫：跨项目读取被拒并留 deny 审计。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `__call__`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充
