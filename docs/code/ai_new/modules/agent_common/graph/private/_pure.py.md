---
source: ai_new/modules/agent_common/graph/private/_pure.py
hash: 96e15eb706a9c4f12fde22e4716e53b1f7757a49c58e8bab8865699a9e0365f9
symbols:
- _as_list
- _dedupe
- _default_policy
- _gate_item_id
- _gate_item_text
- merge_branch_updates
- step_limit
- _resolve_gate
- gate_reasons
- subprocess_checklist
generated: gen_docs.py v1
updated_at: '2026-11-23T04:10:22'
---

# _pure.py

> 由 `scripts/gen_docs.py` 生成；手改会被下次生成覆盖。
> 职责/入参出参/副作用/依赖/不变量/关联需求由人工在下方补充；生成器只提取 docstring 与符号。

## 概览

图模式纯函数：并行分支合并、步数上限语义、门禁拒绝原因、嵌套子流程清单归属。

## 符号

### `_as_list`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_dedupe`（function）
- 职责: 保序去重：可哈希键用 repr 兜底，清单条目 dict 也能区分。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_default_policy`（function）
- 职责: 未声明策略时的默认归并：标量覆盖，列表追加去重（LangGraph 默认 reducer 的本仓库口径）。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_gate_item_id`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_gate_item_text`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `merge_branch_updates`（function）
- 职责: 并行分支结果合并（reducer 纯规则）。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `step_limit`（function）
- 职责: 步数（递归）上限求值：显式定义到限语义，不含循环本身。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_resolve_gate`（function）
- 职责: 在契约 by_id 里按清单 id 反查状态与原文；查不到就原样回传。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `gate_reasons`（function）
- 职责: 门禁拒绝原因归一：forbid 命中 / must 未交齐 → 结构化原因列表。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `subprocess_checklist`（function）
- 职责: 嵌套子流程的清单归属与父级汇总。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充
