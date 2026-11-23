---
source: ai_new/modules/agent_test/private/test_boot_graph.py
hash: 3711d803e14fdee99bbece42da42c02fc0634c962a8acdc60451fa5c0017bdd7
symbols:
- module_path
- module_dirs
- test_plan_covers_every_module_except_root
- test_order_respects_every_edge
- test_plan_is_deterministic
- test_http_serves_only_in_start_phase
- test_no_undeclared_ctx_surface
- test_no_private_state_on_ctx
- test_no_assembly_labels
- test_demands_are_closed_over_hook_points
- test_cycle_is_detected
- test_every_provided_surface_is_wired
generated: gen_docs.py v1
updated_at: '2026-11-23T04:10:22'
---

# test_boot_graph.py

> 由 `scripts/gen_docs.py` 生成；手改会被下次生成覆盖。
> 职责/入参出参/副作用/依赖/不变量/关联需求由人工在下方补充；生成器只提取 docstring 与符号。

## 概览

装配图验收：扫描出的 DAG 必须无环、可复现、覆盖全部模块、面都真的接上。

## 符号

### `module_path`（function）
- 职责: 模块目录（组下面一层）；这里不猜布局，按名字搜。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `module_dirs`（function）
- 职责: 运行时模块（按 data/profiles.json 的 agent 剖面读，不维护第二份名单）。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_plan_covers_every_module_except_root`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_order_respects_every_edge`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_plan_is_deterministic`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_http_serves_only_in_start_phase`（method）
- 职责: 监听不在 setup 里发生：http.setup 只绑端口，http.start 才 serve_forever。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_no_undeclared_ctx_surface`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_no_private_state_on_ctx`（method）
- 职责: 模块私有状态必须放模块自己的 private/_state.py，不许往 ctx 上挂 ctx._xxx。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_no_assembly_labels`（method）
- 职责: 装配关系不许用模块级标签声明：谁提供 ctx.X 由赋值动作本身说明。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_demands_are_closed_over_hook_points`（method）
- 职责: 需求层闭合：点、触发、需求三者互相证明，没有"留了不用的点"。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_cycle_is_detected`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_every_provided_surface_is_wired`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充
