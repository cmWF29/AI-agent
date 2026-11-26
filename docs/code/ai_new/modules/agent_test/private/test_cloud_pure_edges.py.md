---
source: ai_new/modules/agent_test/private/test_cloud_pure_edges.py
hash: 6e6be381f1c2a304381bed412c8906b81f660fce9749e25790c14d1dd07fefd3
symbols:
- __init__
- call
- __init__
- test_seal_b64_encode_failure
- test_generate_key_file_write_failure_cleans_tmp
- test_generate_key_file_replace_failure_without_tmp
- test_generate_key_file_oserror_mapped
- _payload
- test_bad_provider
- test_unknown_category
- test_bad_conflict_policy
- test_bad_root_dir
- test_valid_profile_passes
- test_project_sync_view_included_and_excluded
- test_host_with_port
- test_sync_without_checksum
- test_sync_tree_copy_failure
- test_sync_tree_delete_propagates
- setUp
- tearDown
- test_transcribe_empty_parts
generated: gen_docs.py v1
updated_at: '2026-11-26T11:20:49'
---

# test_cloud_pure_edges.py

> 由 `scripts/gen_docs.py` 生成；手改会被下次生成覆盖。
> 职责/入参出参/副作用/依赖/不变量/关联需求由人工在下方补充；生成器只提取 docstring 与符号。

## 概览

cloud 纯计算/封装/rsync/守卫与 ASR 识别残余分支。

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

### `test_seal_b64_encode_failure`（method）
- 职责: 信封成形阶段 base64 失败：显式报错，不吞成空串。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_generate_key_file_write_failure_cleans_tmp`（method）
- 职责: 密钥落盘中途异常：临时文件被清掉，异常原样上抛。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_generate_key_file_replace_failure_without_tmp`（method）
- 职责: 改名阶段先丢临时文件再失败：清理分支按“不存在”走，异常仍上抛。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_generate_key_file_oserror_mapped`（method）
- 职责: 目录建不出来：OSError 归一成 master_key_missing 稳定错误码。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_payload`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_bad_provider`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_unknown_category`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_bad_conflict_policy`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_bad_root_dir`（method）
- 职责: root_dir 含穿越段：委托 key 校验拒绝，不再靠前缀判断。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_valid_profile_passes`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_project_sync_view_included_and_excluded`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_host_with_port`（method）
- 职责: host:port 形式剥端口再判私网；公网域名的端口不误伤。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_sync_without_checksum`（method）
- 职责: checksum=False 时命令行不带 --checksum，其余开关照旧。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_sync_tree_copy_failure`（method）
- 职责: 复制阶段 OSError 归一成 rsync_error，带原始细节。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_sync_tree_delete_propagates`（method）
- 职责: delete=True 且源为目录内容形式：目标侧多出的文件与子目录一并删掉。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `setUp`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `tearDown`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_transcribe_empty_parts`（method）
- 职责: 识别器分片与收尾都返回空文本：结果为空串而不是拼出空洞。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充
