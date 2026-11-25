---
source: ai_new/modules/agent_test/private/test_cloud.py
hash: 8b88a5c9ac80b05b950075a4e5d9e793ec45a49f7f6053fa436fb76586795b28
symbols:
- _global_caller
- _project_caller
- setUpClass
- tearDownClass
- setUp
- _apply
- _save
- _stage_local_file
- test_validate_profile_accepts_and_rejects
- test_provider_contract_and_http_dir
- test_cloud_pure_edges
- test_fake_provider_roundtrip_digest
- test_save_profile_masks_and_no_secret_leak
- test_sync_idempotent_second_run
- test_retry_then_success_and_backoff
- test_multi_profile_isolation
- test_project_role_config_denied
- test_conflict_remote_not_overwritten
- test_profile_route_errors_and_delete
- test_connection_and_probe_paths
- test_sync_edges_and_prune
- test_resume_recovery_and_manifest_failure_guard
- _state
- _write_state
- test_archive_seam_degrades
- test_guard_endpoint_and_redirect_edges
- test_seal_edges
- test_cloud_helper_edges_and_tools
- test_sanitize_key_traversal
generated: gen_docs.py v1
updated_at: '2026-11-23T04:10:22'
---

# test_cloud.py

> 由 `scripts/gen_docs.py` 生成；手改会被下次生成覆盖。
> 职责/入参出参/副作用/依赖/不变量/关联需求由人工在下方补充；生成器只提取 docstring 与符号。

## 概览

云端资料库验收：适配层 mock 全链路、凭证不泄漏、增量幂等、重试退避、多公司隔离、越权拒绝。

## 符号

### `_global_caller`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_project_caller`（function）
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

### `setUp`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_apply`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_save`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_stage_local_file`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_validate_profile_accepts_and_rejects`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_provider_contract_and_http_dir`（method）
- 职责: 提供方适配层：抽象基类未实现、内存桩/HTTP 目录/占位通道、注册表与元数据。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_cloud_pure_edges`（method）
- 职责: cloud 纯函数：权限未知动作、缺字段校验、差分幂等/删除传播。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_fake_provider_roundtrip_digest`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_save_profile_masks_and_no_secret_leak`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_sync_idempotent_second_run`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_retry_then_success_and_backoff`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_multi_profile_isolation`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_project_role_config_denied`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_conflict_remote_not_overwritten`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_profile_route_errors_and_delete`（method）
- 职责: 配置路由的拒绝/更新/删除分支：非法端点、空凭证、沿用旧凭证、未知 id、删默认。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_connection_and_probe_paths`（method）
- 职责: 连通/往返：未知 id、端点复检、密封失败、提供方错误、体积上限、成功。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_sync_edges_and_prune`（method）
- 职责: 同步边界：无 profile、远端清单来源、清单损坏、重试耗尽、prune 删除与阻断、清单写失败。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_resume_recovery_and_manifest_failure_guard`（method）
- 职责: 断点续传：上次 pending 快照在本轮计划里恢复并优先重传。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_state`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_write_state`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_archive_seam_degrades`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_guard_endpoint_and_redirect_edges`（method）
- 职责: 端点/跳转校验：IPv6、缺协议、私网、白名单与相对跳转。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_seal_edges`（method）
- 职责: 信封层：空明文、缺 crypto、格式不符、截断、篡改、密钥来源失败。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_cloud_helper_edges_and_tools`（method）
- 职责: 云端内部接缝：jitter 退化、mtime 异常、归档条目回读、远端清单损坏、工具注册。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_sanitize_key_traversal`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充
