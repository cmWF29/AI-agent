---
source: ai_new/modules/agent_common/archive/private/_backend.py
hash: dc3b22ff5876cc6bdb6a598650cb98ef275235e23366b311dd34e128484a56b6
symbols:
- available_algorithms
- backend_info
- _zstd_compress
- _zstd_decompress
- compress_bytes
- decompress_bytes
- suffix_for
generated: gen_docs.py v1
updated_at: '2026-11-23T04:10:21'
---

# _backend.py

> 由 `scripts/gen_docs.py` 生成；手改会被下次生成覆盖。
> 职责/入参出参/副作用/依赖/不变量/关联需求由人工在下方补充；生成器只提取 docstring 与符号。

## 概览

压缩后端：gzip 为必然可用基线，zstd 为可选接入点。

## 符号

### `available_algorithms`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `backend_info`（function）
- 职责: 后端档位上报：zstd 未装时显式标未接入，不冒充支持。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_zstd_compress`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_zstd_decompress`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `compress_bytes`（function）
- 职责: 压缩原始字节；返回 ``{data, algorithm}``。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `decompress_bytes`（function）
- 职责: 按记录里的算法解压；算法不匹配 / 流损坏抛异常，不静默返回坏数据。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `suffix_for`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充
