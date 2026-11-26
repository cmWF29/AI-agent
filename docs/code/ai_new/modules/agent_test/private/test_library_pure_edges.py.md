---
source: ai_new/modules/agent_test/private/test_library_pure_edges.py
hash: 87e82ed176a0352f56e14d5602bd94208ebf5f0d5ecf29a254fc3cd0931b9ab1
symbols:
- _contract
- test_target_already_active
- _payload
- test_missing_forbid_template_skips_line
- test_missing_must_template_skips_line
- test_gate_rule_after_gate_lines
- test_note_check_satisfied
- test_plain_active_state_without_next
- test_checks_without_heading
- test_gate_lines_without_rule
- test_glob_matched_reports_nothing
- test_checks_without_heading
- test_tool_name_not_registered
- test_non_dict_tool_entry_kept
- test_setup_registers_all_routes
generated: gen_docs.py v1
updated_at: '2026-11-26T11:20:50'
---

# test_library_pure_edges.py

> 由 `scripts/gen_docs.py` 生成；手改会被下次生成覆盖。
> 职责/入参出参/副作用/依赖/不变量/关联需求由人工在下方补充；生成器只提取 docstring 与符号。

## 概览

岗位库纯函数残余分支：分叉后目标已在活跃集、无后继非终态的段渲染、

## 符号

### `_contract`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_target_already_active`（method）
- 职责: 并行分叉：目标态已在活跃集里时不重复并入，仍合法。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_payload`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_missing_forbid_template_skips_line`（method）
- 职责: 模板无 forbid 句式：红线项不生成空行，must 清单照常输出并带总则。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_missing_must_template_skips_line`（method）
- 职责: 模板无 must 句式：打勾项不生成空行，只有红线行，也不带总则。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_gate_rule_after_gate_lines`（method）
- 职责: 流程约束块：清单非空且模板给总则时，总则行随清单一起下发。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_note_check_satisfied`（method）
- 职责: note 类交付条件：备注长度达标即放行，不再报缺。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_plain_active_state_without_next`（method）
- 职责: 活跃态既无后继也非终态：只出境况行，不追加迁移行。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_checks_without_heading`（method）
- 职责: 流程约束块：验收规则非空但模板不给标题时，规则照列不造标题。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_gate_lines_without_rule`（method）
- 职责: 有清单但模板不给总则：只下发清单，不补规则行。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_glob_matched_reports_nothing`（method）
- 职责: glob 条件已命中：不报缺，checked 计数仍为规则条数。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_checks_without_heading`（method）
- 职责: 有验收规则但模板不给标题：规则直接列出，不造标题行。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_tool_name_not_registered`（method）
- 职责: 登记名单里有未落地的工具名：跳过不报错，已登记的工具被摘除。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_non_dict_tool_entry_kept`（method）
- 职责: 工具字典里存在非字典项：按 skill 归属清理时跳过，不误删。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_setup_registers_all_routes`（method）
- 职责: 装配：26 条岗位库路由按名登记到 library 模块。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充
