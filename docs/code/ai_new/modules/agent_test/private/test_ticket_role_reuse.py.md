---
source: ai_new/modules/agent_test/private/test_ticket_role_reuse.py
hash: c49a67686526edf58561ee610bca82f92a19ab1ab305727b517dc3eca081fde9
symbols:
- session
- rec
- row
- test_idle_and_spawned_are_reusable_not_only_active
- test_active_wins_then_latest
- test_cross_ticket_role_and_gone_are_not_reused
- test_gone_does_not_block_new
- test_create_then_reuse_keeps_one_row_and_marks_receipt
- test_different_session_same_role_stays_parallel
- setUp
- test_tree_is_sequential_calls_only
- test_one_spawn_call_and_receipt_flows_from_module
generated: gen_docs.py v1
updated_at: '2026-11-28T23:02:47'
---

# test_ticket_role_reuse.py

> 由 `scripts/gen_docs.py` 生成；手改会被下次生成覆盖。
> 职责/入参出参/副作用/依赖/不变量/关联需求由人工在下方补充；生成器只提取 docstring 与符号。

## 概览

同工单同岗位复用：role_spawn 不重复建会话（T-20261128-0003 AC1-AC6）。

## 符号

### `session`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `rec`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `row`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_idle_and_spawned_are_reusable_not_only_active`（method）
- 职责: AC1 真实历史：T-0002 的 tester 是 idle/spawned，不能因为不在途就再建。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_active_wins_then_latest`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_cross_ticket_role_and_gone_are_not_reused`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_gone_does_not_block_new`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_create_then_reuse_keeps_one_row_and_marks_receipt`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_different_session_same_role_stays_parallel`（method）
- 职责: 历史脏数据不合并：不同会话各有记录，清理另开工单。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `setUp`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_tree_is_sequential_calls_only`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_one_spawn_call_and_receipt_flows_from_module`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充
