---
source: ai_new/modules/agent_test/private/test_role_gates.py
hash: e66007a1c94dbc6a0bbfac715402fa724ad1012999d57951bf7928272d80947f
symbols:
- _load_seed
- yaml_safe_load
- _iter_states
- _records
- setUpClass
- _gate_states
- test_gate_present_must_and_forbid_well_formed
- test_must_ids_unique_across_library
- test_mirror_files_match_seed
- test_todo_in_every_state_tools
- _contract
- test_rendered_checklist_matches_gate_data
- _enforce
- test_developer_transition_gate
- test_developer_understand_can_inspect_repo
- test_requirement_owner_transition_gate
- test_skill_decomposer_contract_and_transitions
- test_prompts_are_prose_without_duplicated_checklist
- test_gate_must_is_the_single_checklist_source
- test_ref_flow_expands_into_contract
generated: gen_docs.py v1
updated_at: '2026-11-23T04:10:23'
---

# test_role_gates.py

> 由 `scripts/gen_docs.py` 生成；手改会被下次生成覆盖。
> 职责/入参出参/副作用/依赖/不变量/关联需求由人工在下方补充；生成器只提取 docstring 与符号。

## 概览

岗位门禁契约测试：种子岗位/流程的清单完整性、唯一性、渲染一致性与迁移门禁。

## 符号

### `_load_seed`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `yaml_safe_load`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_iter_states`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_records`（function）
- 职责: 展开后的岗位与流程记录表（种子盖覆盖层后的生效形状）。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `setUpClass`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_gate_states`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_gate_present_must_and_forbid_well_formed`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_must_ids_unique_across_library`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_mirror_files_match_seed`（method）
- 职责: 覆盖层镜像必须由种子派生：roles.yaml/flows.yaml 与 seed 深一致，防双源漂移。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_todo_in_every_state_tools`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_contract`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_rendered_checklist_matches_gate_data`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_enforce`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_developer_transition_gate`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_developer_understand_can_inspect_repo`（method）
- 职责: 理解阶段必须能读真实仓库，否则只能对着交付件空转。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_requirement_owner_transition_gate`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_skill_decomposer_contract_and_transitions`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_prompts_are_prose_without_duplicated_checklist`（method）
- 职责: 提示词只写 prose：不得复制 gate 清单（must id / 待办勾选框）。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_gate_must_is_the_single_checklist_source`（method）
- 职责: 记录里不得另挂一份手写 todos 清单；强制清单只来自 gate.must。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_ref_flow_expands_into_contract`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充
