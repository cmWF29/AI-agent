---
source: ai_new/modules/agent_test/private/test_core.py
hash: 9861e91e0ed61278f88a70a4561a7d07813a46f55898804a23022c6c3286d6be
symbols:
- __init__
- __call__
- _demand_bound_routes
- setUpClass
- tearDownClass
- setUp
- test_every_registered_route_declares_contract
- test_call_identity_is_judged_by_ledger
- test_contract_enforces_required_fields
- test_all_modules_loaded
- test_modules_have_no_log_capability
- test_api_executor_pool_capacity_is_configured
- test_runtime_hook_points_match_static_scan
- test_demand_calls_bind_to_real_routes
- test_demand_test_map_is_fresh
- test_every_control_has_a_declared_state_machine
- test_views_guarded_and_tool_card_single_exit
- test_ops_metrics_have_real_sources
- test_screen_machine_is_closed
- test_registered_routes_are_demand_bound_or_platform
- test_write_routes_are_governed
- test_console_carries_no_business_demand_ids
- test_console_click_bindings_are_stable_ids
- test_console_clicks_have_one_entry_and_state_machine
- test_click_machine_spec_covers_every_clickable_kind
- test_console_scripts_have_no_duplicate_toplevel_names
- test_console_render_keeps_scroll_position
- test_console_shell_is_backend_driven
- _run
- _clean_hooks
- _glob
- _remove_session
- test_knowledge_roundtrip
- test_knowledge_index_tree_groups_tickets_under_project
- test_channel_post_tail_roundtrip
- test_chat_demand_answers_and_does_not_self_trigger
- test_chat_drain_async_dispatches_reply
- test_defer_queue_persists_and_replays_after_restart
- test_runtime_stream_events_pushes_on_change_and_clears
- test_net_stream_pushes_draft_and_collects_frames
- test_net_request_decodes_chunked_body
- test_net_unreachable_returns_error_code
- test_net_passes_through_4xx_status
- test_net_passes_through_5xx_status
- test_net_stream_skips_bad_frames_and_stops_on_done
- test_net_stream_eof_keeps_received_frames
- test_net_stream_read_timeout_returns_error
- test_runtime_dispatch_clears_run_slot_after_finish
- test_artifacts_roundtrip_and_escape
- test_artifacts_ticket_layer_resolves_project_from_ticket
- test_artifacts_index_tree_groups_tickets_under_project
- test_codec_decode_hex_utf8_and_binary
- test_logs_index_tree_leaf_carries_name_and_type
- test_ticket_artifact_project_follows_ticket
- test_project_workspace_root_config
- test_project_lifecycle
- test_project_purge_cascades_children
- test_ticket_lifecycle_and_role_tool
- test_ticket_close_archives_transcript_and_recycles_sessions
- test_project_tree_thread_and_positions
- test_ticket_requires_existing_project
- test_stall_audit_ticket_skips_pm_and_dispatch
- test_session_spawn_send_run_wait
- test_spawn_reuses_active_same_role_no_duplicate
- test_react_stash_tool_output_branches
- test_react_checkpoint_writes_session_record
- test_react_tool_calls_run_concurrently
- test_session_resume_demand_forms_effects
- test_runtime_call_nested_demand_skips_loop_bridge
- test_session_stuck_scan_demand_forms_effects
- test_react_non_structured_keeps_old_summary
- test_ops_overview_logs_and_library
- test_tool_library_splits_builtin_and_external
- test_external_tool_registers_and_runs_pending
- test_project_tool_override_toggle_pick_and_execute
- test_project_role_override_rejects_unknown_role
- test_shell_only_on_execution_roles
- test_exec_creates_ticket_workspace
- test_exec_runs_real_subprocess_and_captures_output
- test_exec_kills_on_timeout
- test_project_skills_and_tools_list
- test_install_plan_empty_deps_is_ready
- test_deps_report_groups_present_and_missing
- test_deps_report_all_ready_blocks_install
- test_tools_deps_demand_runs_report
- test_pip_name_maps_to_import_name
- test_assembled_demands_include_new_entries
- test_module_caller_is_forbidden
- test_demand_caller_allowed
- test_sse_gate_rejects_non_stream_and_unknown
- test_health_and_http
- test_health_live_public_and_assemble_gated
- _raw_http
- test_http_method_and_path_edges
- test_http_body_framing_edges
- test_http_static_etag_gzip
- test_sse_stream_and_client_disconnect
- test_rpc_endpoint_returns_raw_result
- test_auth_pure_functions
- test_position_pure_functions
- test_history_event_carries_recipient
- test_purge_orphan_tickets_script
- test_stage_state_machine
- test_seed_flow_refs_wired
- test_react_context_pure_functions
- test_session_stuck_plan_classifies_missing_and_stalled
- test_active_same_role_idempotent_dedupe
- test_skill_unit_pure_functions
- test_decompose_safe_pkg_validates_name
- test_decompose_run_reacts_with_restricted_tools
- test_decompose_install_effects_only_on_valid_parts
- test_decompose_install_route_skips_write_on_invalid
- test_decompose_install_reports_upstream_failure
- test_decompose_install_end_to_end_writes_library
- test_project_override_pure_parts_and_toggle
- test_project_screen_filters_non_record_files
- test_flow_plan_effects
- test_flow_plan_awaiting_user_skips_review_loop
- test_flow_plan_auto_session_not_waiting
- test_flow_plan_delivered_round_not_waiting
- test_react_schema_normalizes_list_to_array
- test_react_result_carries_failure
- test_finish_records_and_clears_last_error
- test_finish_does_not_duplicate_checkpointed_run_messages
- test_finish_keeps_messages_arrived_during_run
- test_finish_records_stage_and_alert
- test_thread_exposes_session_meta
- test_thread_messages_carry_at
- test_thread_members_carry_task
- test_spawn_refuses_role_disabled_by_project
- test_thread_carries_wire_brief_and_wire_at_reads_raw
- test_react_summarize_falls_back_only_without_model_summary
- test_llm_wire_masks_secret_and_keeps_raw
- test_todo_ops_crud_and_patch
- test_todo_apply_declares_session_patch_only_when_changed
- test_todo_tool_is_demand_bound
- test_stage_tool_whitelists_keep_todo
- test_bind_tools_marks_project_disabled
- test_thread_members_carry_machine
- test_thread_does_not_duplicate_pm_session
- test_auth_verify_session_path_is_guarded_and_expiry_is_enforced
- test_auth_verify_legacy_token
- test_auth_status_is_public
- test_auth_login_success_issues_valid_session_with_default_ttl
- test_auth_login_throttles_repeated_failures_by_peer
- test_auth_login_guard_disabled_skips_ledger
- test_auth_login_demand_is_public
- _http
- test_http_get_is_read_only_and_carries_security_headers
- test_http_rejects_oversize_and_chunked_bodies
- test_static_data_files_require_login
- test_next_seq_seeds_from_disk_baseline
- test_next_seq_is_unique_under_concurrency
- test_view_index_exposes_every_modal_form
- setUp
- test_gate_blocks_until_every_must_checked
- test_gate_checks_redline_and_stay
- test_glob_variants
- test_next_n_ignores_bad_ids
- test_missing_record_and_view_edges
- test_screen_filters_and_note_branch
- test_review_and_pick_and_branch
- test_ticket_files_and_paths
- test_template_stale_and_record_path
- test_archive_and_brief_helpers
generated: gen_docs.py v1
updated_at: '2026-11-23T04:10:22'
---

# test_core.py

> 由 `scripts/gen_docs.py` 生成；手改会被下次生成覆盖。
> 职责/入参出参/副作用/依赖/不变量/关联需求由人工在下方补充；生成器只提取 docstring 与符号。

## 概览

核心流程冒烟：真实装配（临时 data 目录）+ HTTP 端到端。

## 符号

### `__init__`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `__call__`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_demand_bound_routes`（function）
- 职责: 需求 do 树编排的路由 ∪ 已编排聚合能力的内部路由（B1 下沉，见 capability-routes.yaml）。
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

### `setUp`（method）
- 职责: 用例隔离：先收口前序用例后台派发的会话任务，再清掉非种子会话记录，
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_every_registered_route_declares_contract`（method）
- 职责: 消息结构是数据：注册的每条路由都要在模块 data/api.yaml 里声明收发字段。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_call_identity_is_judged_by_ledger`（method）
- 职责: 调用方身份不是自报的：handler 执行期按所属模块判定；跨模块直调必须登记。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_contract_enforces_required_fields`（method）
- 职责: enforce 模式下缺必填字段直接拒；warn 模式只留证据，不改变行为。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_all_modules_loaded`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_modules_have_no_log_capability`（method）
- 职责: ctx 上没有日志：记日志是运维的业务，模块只能 emit hook。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_api_executor_pool_capacity_is_configured`（method）
- 职责: api-loop 桥接执行器是有界池，容量由 config.runtime.api_workers 显性声明。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_runtime_hook_points_match_static_scan`（method）
- 职责: 运行期的点必须等于静态扫描出来的点：否则静态图就是在骗人。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_demand_calls_bind_to_real_routes`（method）
- 职责: 需求绑定的 func 必须真注册：改函数名/删函数，静态和运行期都躲不过。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_demand_test_map_is_fresh`（method）
- 职责: 需求 ↔ 用例映射是算出来的，不是手写的：表过期即失败。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_every_control_has_a_declared_state_machine`（method）
- 职责: 每个按钮都有自己的状态机：页面控件与 console.yaml controls 双向闭合。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_views_guarded_and_tool_card_single_exit`（method）
- 职责: 视图层静态门禁：条件表达式可解析、项目/工单页写操作带归档判据、工具卡单一折叠出口。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_ops_metrics_have_real_sources`（method）
- 职责: 运维指标门禁：统计条与指标清单一一对应，每个指标的取数源真实存在。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_screen_machine_is_closed`（method）
- 职责: 界面状态图门禁：页面/浮层节点闭合、浮层可关、壳层控件已登记、入口全可达；
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_registered_routes_are_demand_bound_or_platform`（method）
- 职责: 注册表只收两类路由：被需求 do 树编排的业务能力，或清单登记的平台入口。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_write_routes_are_governed`（method）
- 职责: 落盘是有副作用的业务动作：写能力要么被需求编排，要么是清单登记的平台件。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_console_carries_no_business_demand_ids`（method）
- 职责: 控制台外壳只认规格，不许自带第二份需求清单。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_console_click_bindings_are_stable_ids`（method）
- 职责: 点击绑定必须是"单调 id 表 + 保活带走"，不许用数组下标。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_console_clicks_have_one_entry_and_state_machine`（method）
- 职责: 所有点击只有一个入口：handleClick + 显式状态迁移表。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_click_machine_spec_covers_every_clickable_kind`（method）
- 职责: 规格与页面必须齐：页面上每一个可点位置，都得在规格里声明门禁。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_console_scripts_have_no_duplicate_toplevel_names`（method）
- 职责: console 的 js 会合成一个脚本执行：顶层同名函数后者覆盖前者。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_console_render_keeps_scroll_position`（method）
- 职责: 重渲染不许把用户滚到的位置清掉：整页 render 与局部 refreshAs 都要记账再还。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_console_shell_is_backend_driven`（method）
- 职责: 导航、品牌、字与配色都只存后端一份：页面改了后端也跟着变，反过来也一样。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_run`（method）
- 职责: 按名跑一条 callable 需求，返回引擎结果 {ok, demand, result, calls}。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_clean_hooks`（method）
- 职责: 用例隔离：先 drain 消化前序残留 defer，再清空队列，避免跨用例串扰污染计数。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_glob`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_remove_session`（method）
- 职责: 用例收尾：删掉本用例在盘上造的会话，避免残留在途记录串扰后续
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_knowledge_roundtrip`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_knowledge_index_tree_groups_tickets_under_project`（method）
- 职责: 知识目录树：公共平铺，项目文档与其工单文档按归属归到项目节点下。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_channel_post_tail_roundtrip`（method）
- 职责: 频道：需求发两条、按序读回；watch 门面按游标回 {items, cursor}。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_chat_demand_answers_and_does_not_self_trigger`（method）
- 职责: 一条业务闭环：用户消息 → 模型 → 回复写回；assistant 不再触发模型。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_chat_drain_async_dispatches_reply`（method）
- 职责: 异步轨收尾：drain_async 经 adispatch/arun/acall 直连事件循环，回复照常落盘。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_defer_queue_persists_and_replays_after_restart`（method）
- 职责: 延迟事件落盘：入队即持久化；新 Runtime 从盘回填；认领/清空后盘上摘除。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_runtime_stream_events_pushes_on_change_and_clears`（method）
- 职责: 草稿事件流：订阅后 put/clear 唤醒推快照；游标对齐后不重复推。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_net_stream_pushes_draft_and_collects_frames`（method）
- 职责: SSE 流式出站：逐帧正文增量进草稿槽，事件对象汇总交 decode_sse 归一。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_net_request_decodes_chunked_body`（method）
- 职责: 非流响应 chunked 编码：按块解码还原完整 JSON，不被 keep-alive 挂住。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_net_unreachable_returns_error_code`（method）
- 职责: 连接不可达：非流与流都归 unreachable 失败结果，不外抛；retries=0 不拖退避。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_net_passes_through_4xx_status`（method）
- 职责: 4xx 是请求本身问题：传输成功即透传状态码，不当瞬时故障重试。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_net_passes_through_5xx_status`（method）
- 职责: 5xx 响应体正常读出：状态码透传，业务层据状态判定；读阶段异常才走重试。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_net_stream_skips_bad_frames_and_stops_on_done`（method）
- 职责: 坏 JSON / 非对象帧被跳过，合法帧保留；[DONE] 提前结束读取。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_net_stream_eof_keeps_received_frames`（method）
- 职责: 流中途断线：已收到的帧保留返回，不当失败（草稿槽不回滚）。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_net_stream_read_timeout_returns_error`（method）
- 职责: 连接建立后上游不吐帧：读帧超时归 unreachable，流已连上不重试。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_runtime_dispatch_clears_run_slot_after_finish`（method）
- 职责: 后台任务跑完（正常/报错/被接管作废）即自清运行表，死任务条目不随工单数堆积。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_artifacts_roundtrip_and_escape`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_artifacts_ticket_layer_resolves_project_from_ticket`（method）
- 职责: 工单层交付件只给 ticket 时，必须从工单档案回查项目；查不到要显式拒绝。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_artifacts_index_tree_groups_tickets_under_project`（method）
- 职责: 文档目录树：公共平铺，项目文档与其工单文档按归属归到项目节点下。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_codec_decode_hex_utf8_and_binary`（method）
- 职责: hex 解码成形：utf8 直出；非 utf8 退 base64；超阈值标 truncated。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_logs_index_tree_leaf_carries_name_and_type`（method）
- 职责: 日志目录叶子：带 type=log 与 name/path，前端按叶子渲染不空卡。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_ticket_artifact_project_follows_ticket`（method）
- 职责: ticket 层写产物：归属项目以工单记录为准，模型传错/漏填都不能错位到 projects/item。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_project_workspace_root_config`（method）
- 职责: 项目路径：建项目时落到档案，工作区解析给出共享层与工单隔离目录；清空回 legacy。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_project_lifecycle`（method）
- 职责: 项目：建 → 列表露出字段 → 归档 → 彻底删除（纯形状解包不能漏层）。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_project_purge_cascades_children`（method）
- 职责: 彻底删项目：工单、PM 会话、项目产物、项目知识一并清；public 知识保留。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_ticket_lifecycle_and_role_tool`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_ticket_close_archives_transcript_and_recycles_sessions`（method）
- 职责: 结单：往来对话固化进工单 transcript，随后 PM/角色会话文件被回收。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_project_tree_thread_and_positions`（method）
- 职责: 项目→工单分级树；工单 1:1 主会话线程；岗位带流程规范。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_ticket_requires_existing_project`（method）
- 职责: 工单必须绑定存在的项目：缺项目 / 项目不存在都被拦下。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_stall_audit_ticket_skips_pm_and_dispatch`（method）
- 职责: 停滞审计单不拉 PM，也不派发首轮开工。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_session_spawn_send_run_wait`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_spawn_reuses_active_same_role_no_duplicate`（method）
- 职责: 重复触发同岗：已有在途会话时复用，不并出第二条同岗线。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_react_stash_tool_output_branches`（method）
- 职责: T1 大输出分级：阈值内全文；落盘成功回日志路径；apply 失败兜底全文回填。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_react_checkpoint_writes_session_record`（method）
- 职责: 轮内检查点：带 path 时收口步经 runtime.apply 把会话记录写回，崩溃后存档不丢本轮增量。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_react_tool_calls_run_concurrently`（method）
- 职责: 同一轮多个 tool_call 并发提交工具池：总耗时≈max(单工具) 而非 sum；回填按原序。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_session_resume_demand_forms_effects`（method）
- 职责: 启动续跑需求：读配置/文案 → 能力分类残留 running → 成形 write+dispatch 效果清单。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_runtime_call_nested_demand_skips_loop_bridge`（method）
- 职责: 能力内同步壳嵌套需求直接走同步引擎，不经 demand_engine.run async 路由回投 loop。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_session_stuck_scan_demand_forms_effects`（method）
- 职责: 自愈扫描需求：无在途任务的 running 会话被复位 idle，成形 write 效果交 apply。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_react_non_structured_keeps_old_summary`（method）
- 职责: T2 非结构化收口不清空滚动摘要；旧摘要跨轮保留。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_ops_overview_logs_and_library`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_tool_library_splits_builtin_and_external`（method）
- 职责: 内置清单只列代码内置；内置行字段齐全、来源标记正确。外部边界由注册表占位用例覆盖。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_external_tool_registers_and_runs_pending`（method）
- 职责: 外部登记工具装配进注册表但不进内置清单；占位执行回 external_pending，业务参数透传、tool 键剥离。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_project_tool_override_toggle_pick_and_execute`（method）
- 职责: 项目覆盖层禁用工具：pick 名单剔除、execute 拦截；启用后恢复占位执行。公共库定义不被改写。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_project_role_override_rejects_unknown_role`（method）
- 职责: 未知岗位 id 不得写进项目覆盖层：入口层校验公共库 + 用户层岗位集合，显式 404。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_shell_only_on_execution_roles`（method）
- 职责: shell 按岗位名单裁剪：developer/tester 可取，只读文档岗取不到。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_exec_creates_ticket_workspace`（method）
- 职责: 项目配了根路径：工单目录不存在时，执行层按工作区路径创建并以它为 cwd。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_exec_runs_real_subprocess_and_captures_output`（method）
- 职责: 异步子进程核心：起真实解释器，收 stdout/stderr 与退出码。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_exec_kills_on_timeout`（method）
- 职责: 超时打断：长睡眠进程被 kill，killed=timeout。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_project_skills_and_tools_list`（method）
- 职责: 项目技能/工具清单取数：直读公共库并按覆盖层打标记，成行字段齐全。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_install_plan_empty_deps_is_ready`（method）
- 职责: 空依赖清单的安装计划直接就绪；有未在位 pip 包才进待装清单。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_deps_report_groups_present_and_missing`（method）
- 职责: 盘点按类别聚合在位/缺失：在位项进 present，缺失项带归属工具；统计与可装标志成形。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_deps_report_all_ready_blocks_install`（method）
- 职责: 全部在位时盘点就绪、无可自动装项，安装按钮应被禁用。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_tools_deps_demand_runs_report`（method）
- 职责: 盘点需求闭环：取外部登记与禁用过滤 → tools.deps 成形分类盘点，只读不装包。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_pip_name_maps_to_import_name`（method）
- 职责: pip 规范名与导入名不一致时，探测按映射后的导入名走；未收录的兜底连字符转下划线。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_assembled_demands_include_new_entries`（method）
- 职责: 装配后需求清单含本轮入口（冒烟断言固化进门禁，避免下线后静默丢失）。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_module_caller_is_forbidden`（method）
- 职责: 能力只对需求开放：模块自己伸手会被注册表拦（旧跨模块矩阵已收敛成这道闸）。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_demand_caller_allowed`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_sse_gate_rejects_non_stream_and_unknown`（method）
- 职责: SSE 入口：未知路由 404；已注册但非流式 400。流式路由仅 channel.watch。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_health_and_http`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_health_live_public_and_assemble_gated`（method）
- 职责: 存活探头免鉴权且 uptime 非负；业务概览自检无令牌必须 401。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_raw_http`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_http_method_and_path_edges`（method）
- 职责: GET 写路由 405；拼错的 API 404；RPC 少一段 400；模块清单可读。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_http_body_framing_edges`（method）
- 职责: chunked / 非法长度 / 超限 / 非 YAML 都必须结构化拒绝，不读脏字节。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_http_static_etag_gzip`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_sse_stream_and_client_disconnect`（method）
- 职责: SSE 真开流；客户端读一帧后断开，服务端只关连接不抛 500。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_rpc_endpoint_returns_raw_result`（method）
- 职责: 网络通道的服务端：/api/rpc/ 返回未包装的原始结果，供另一个进程直接消费。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_auth_pure_functions`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_position_pure_functions`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_history_event_carries_recipient`（method）
- 职责: 历程事件带接收人 to/to_kind：建单→本单，PM 开工→PM，派角色→岗位，拆子单→子工单，评审/回催→本单。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_purge_orphan_tickets_script`（method）
- 职责: 孤儿工单清理脚本：盘点→备份→删除→清清单，幂等；在册工单条目保留。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_stage_state_machine`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_seed_flow_refs_wired`（method）
- 职责: 种子岗位流程经 ref 复用公共子流程：契约展开子链全路径与终态。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_react_context_pure_functions`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_session_stuck_plan_classifies_missing_and_stalled`（method）
- 职责: 自愈扫描：任务丢失 / 停滞超阈值复位 idle；在途新鲜会话保留；非 running 不碰。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_active_same_role_idempotent_dedupe`（method）
- 职责: 同工单同岗在途查重：只并在途（queued/running/stalled），排除空闲/终态/异岗异单。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_skill_unit_pure_functions`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_decompose_safe_pkg_validates_name`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_decompose_run_reacts_with_restricted_tools`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_decompose_install_effects_only_on_valid_parts`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_decompose_install_route_skips_write_on_invalid`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_decompose_install_reports_upstream_failure`（method）
- 职责: 模型没交答复时，需求回上游错误码，不许误报成"缺少标识 id"。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_decompose_install_end_to_end_writes_library`（method）
- 职责: 真链路：包正文 → 模型拆解 JSON → 四库合并 → Skill 单元落盘可列。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_project_override_pure_parts_and_toggle`（method）
- 职责: 覆盖层纯函数：缺省五类空清单；禁用加入、启用移出、去重保序；非法类型/标识返错误形状。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_project_screen_filters_non_record_files`（method）
- 职责: 列表/分级树：messages.yaml 这类无档案 id 的文案模板 dict 不渲染成空壳项目。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_flow_plan_effects`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_flow_plan_awaiting_user_skips_review_loop`（method）
- 职责: 对话型会话仅读知识后向用户提问、无产物/编排动作：判等待用户，只落盘不回催不复盘。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_flow_plan_auto_session_not_waiting`（method）
- 职责: 后台自动会话（pm/role）不设等待闸门：读类工具后陈述也按终态判定进入闭环。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_flow_plan_delivered_round_not_waiting`（method）
- 职责: 本轮有写产物工具调用：不算等待，正常进入评审闭环。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_react_schema_normalizes_list_to_array`（method）
- 职责: 内部 list 类型要归一为模型侧 JSON Schema 的 array，并带 items。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_react_result_carries_failure`（method）
- 职责: 后端未答复的原因要随结果透出，不能在循环里丢掉。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_finish_records_and_clears_last_error`（method）
- 职责: 失败原因落进会话 meta；下一轮成功后清除上一次的错误痕迹。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_finish_does_not_duplicate_checkpointed_run_messages`（method）
- 职责: 轮内检查点已把本轮消息写进 latest，收尾不能把同一批消息再拼一遍。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_finish_keeps_messages_arrived_during_run`（method）
- 职责: 运行期间真正新插入的用户消息仍要接在尾部，不能被检查点去重误删。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_finish_records_stage_and_alert`（method）
- 职责: 合法跳转落新阶段；非法跳转保留旧阶段并留告警；无校验时按 out.stage 落库。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_thread_exposes_session_meta`（method）
- 职责: 线程视图要露出主会话 meta，界面才能判断 PM 有无卡点。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_thread_messages_carry_at`（method）
- 职责: 群聊按时间穿插表征：历史消息缺时间戳时用会话起始时刻补，且同会话单调递增。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_thread_members_carry_task`（method）
- 职责: 成员卡要展示职责，members 必须自带 task，前端不得回查 roles 补字段。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_spawn_refuses_role_disabled_by_project`（method）
- 职责: 项目里禁用岗位必须联动到派单：禁掉的岗位不能再被拉起，且拒绝原因要显形。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_thread_carries_wire_brief_and_wire_at_reads_raw`（method）
- 职责: 报文原文不再随群聊流下发：视图只带摘要与序位，原文按需回读同一条消息。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_react_summarize_falls_back_only_without_model_summary`（method）
- 职责: 逐轮压缩：模型给了摘要就听模型的；没给（步数耗尽/中断）才由系统按上限补工具往返。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_llm_wire_masks_secret_and_keeps_raw`（method）
- 职责: 网络报文要能原样回查：请求体与响应原文保留，密钥类头打码。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_todo_ops_crud_and_patch`（method）
- 职责: 待办是模型自排计划的工具：增删查改都走同一条能力，改过才回会话补丁。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_todo_apply_declares_session_patch_only_when_changed`（method）
- 职责: 落盘是会话检查点的事：只有改动才回补丁，查询不产生写盘。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_todo_tool_is_demand_bound`（method）
- 职责: 待办的增删查改必须是工具，且工具只是需求身份，不持有实现、不自己写盘。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_stage_tool_whitelists_keep_todo`（method）
- 职责: 阶段裁剪按状态 tools 白名单走：漏了 todo 就会把待办工具裁掉，数据契约必须齐。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_bind_tools_marks_project_disabled`（method）
- 职责: 岗位↔流程↔项目工具绑定要能一行摊开：可用数、禁用名与状态链都在行上。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_thread_members_carry_machine`（method）
- 职责: 状态机可视化要显式看见每个角色在哪个阶段，members 必须带流程链与活跃集合。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_thread_does_not_duplicate_pm_session`（method）
- 职责: by_ticket 会把 PM 主会话一并归集；线程视图不得把它当角色二次并入成员与消息流。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_auth_verify_session_path_is_guarded_and_expiry_is_enforced`（method）
- 职责: 会话令牌只走合法字符路径；过期会话拒绝，越界令牌不读盘。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_auth_verify_legacy_token`（method）
- 职责: 夹具配了旧令牌 t：命中放行，空/错令牌拒绝。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_auth_status_is_public`（method）
- 职责: 状态路由不鉴权：登录页要先问当前是否需要登录。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_auth_login_success_issues_valid_session_with_default_ttl`（method）
- 职责: 登录真跑一遍：摘要比对通过才会发令牌，非正 ttl 回落到 86400，令牌能过闸。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_auth_login_throttles_repeated_failures_by_peer`（method）
- 职责: 连续失败先计数再锁定：锁定期内正确口令也拒绝；换个 IP 不被牵连。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_auth_login_guard_disabled_skips_ledger`（method）
- 职责: 显式关掉登录守卫时不能因为台账不可写把登录打成 503。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_auth_login_demand_is_public`（method）
- 职责: 登录需求本身必须先可达：不带令牌也能过闸（凭据由需求内部判，失败返 401）。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_http`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_http_get_is_read_only_and_carries_security_headers`（method）
- 职责: GET 只留给读入口；带令牌也不能用链接触发写路由。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_http_rejects_oversize_and_chunked_bodies`（method）
- 职责: 请求体先量长度再读；chunked 不解析，避免未消费字节污染下一条请求。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_static_data_files_require_login`（method）
- 职责: api.yaml 等数据文件不能因为不是 HTML 就匿名可取；壳资源仍放行。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_next_seq_seeds_from_disk_baseline`（method）
- 职责: 新桶以磁盘最大号为基线，首号 = baseline + 1。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_next_seq_is_unique_under_concurrency`（method）
- 职责: AtomicAdd 发号：多线程同桶取号不重复，且从基线连续递增。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_view_index_exposes_every_modal_form`（method）
- 职责: 系统级 UT：运行时视图目录必须把页面引用的每个弹窗表单都送到前端。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `setUp`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_gate_blocks_until_every_must_checked`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_gate_checks_redline_and_stay`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_glob_variants`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_next_n_ignores_bad_ids`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_missing_record_and_view_edges`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_screen_filters_and_note_branch`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_review_and_pick_and_branch`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_ticket_files_and_paths`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_template_stale_and_record_path`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_archive_and_brief_helpers`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充
