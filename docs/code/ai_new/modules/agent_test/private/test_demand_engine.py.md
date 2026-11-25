---
source: ai_new/modules/agent_test/private/test_demand_engine.py
hash: c662f256b09c0a192ce7e95aed594fa414134ba58afd139474a9fd6a5da65c00
symbols:
- __init__
- call
- __init__
- own
- list_dir
- json_read
- json_write
- yaml_read
- yaml_write
- stat_size
- stat_mtime
- __init__
- _demand
- test_call_gets_payload_from_event
- test_rejected_operators_raise
- test_control_flow_statement_stops_sequence
- test_failure_is_recorded_not_raised_and_stops_sequence
- test_business_failure_stops_before_later_write
- test_runtime_apply_runs_after_business_failure_to_persist_audit
- test_routes_of_lists_sequential_calls
- test_dispatch_only_runs_matching_demands
- test_on_accepts_single_string
- test_items_do_not_carry_a_demand_level_guard
- test_disable_takes_effect_immediately
- test_items_expose_routes_for_static_reading
- test_view_index_ships_forms_of_keyless_pages
- test_manifest_counts_steps_views_callable_and_drift
- test_view_spec_and_missing_view
- test_console_menus_group_order_and_short_name
- test_screens_builds_pages_routes_controls_and_overlays
- test_callable_run_error_paths
generated: gen_docs.py v1
updated_at: '2026-11-23T04:10:23'
---

# test_demand_engine.py

> 由 `scripts/gen_docs.py` 生成；手改会被下次生成覆盖。
> 职责/入参出参/副作用/依赖/不变量/关联需求由人工在下方补充；生成器只提取 docstring 与符号。

## 概览

需求语言与需求引擎：语法、求值、守卫、循环、插拔。

## 符号

### `__init__`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `call`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `__init__`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `own`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `list_dir`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `json_read`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `json_write`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `yaml_read`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `yaml_write`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `stat_size`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `stat_mtime`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `__init__`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_demand`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_call_gets_payload_from_event`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_rejected_operators_raise`（method）
- 职责: 判断/逻辑/集合/度量运算符已下沉模块纯函数，需求表达式求值必须拒绝。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_control_flow_statement_stops_sequence`（method）
- 职责: 控制流语句已经不在语法里：引擎记一条失败并终止后续顺序语句。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_failure_is_recorded_not_raised_and_stops_sequence`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_business_failure_stops_before_later_write`（method）
- 职责: 能力返回 ok:false 是业务拒绝，后续写步骤绝不能继续执行。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_runtime_apply_runs_after_business_failure_to_persist_audit`（method）
- 职责: 失败能力携带的审计 effects 必须由 runtime.apply 落盘，之后不再跑正常步骤。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_routes_of_lists_sequential_calls`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_dispatch_only_runs_matching_demands`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_on_accepts_single_string`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_items_do_not_carry_a_demand_level_guard`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_disable_takes_effect_immediately`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_items_expose_routes_for_static_reading`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_view_index_ships_forms_of_keyless_pages`（method）
- 职责: 表单是跨页能力：没有 key 的表单页也必须随目录下发，否则弹窗拿不到规格。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_manifest_counts_steps_views_callable_and_drift`（method）
- 职责: 清单要把视图/可调/步骤数、非结构语句与 expect 漂移都摊平。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_view_spec_and_missing_view`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_console_menus_group_order_and_short_name`（method）
- 职责: 菜单从视图声明汇总，不另存一份；组序/短名/底栏序都必须保留。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_screens_builds_pages_routes_controls_and_overlays`（method）
- 职责: 页面地图/控件清单从视图自动推导：跳页、弹窗、父级返回都要有边。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_callable_run_error_paths`（method）
- 职责: 按名调用：不存在/未可调/已下线/无调用都要明确 code，不吞成 None。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充
