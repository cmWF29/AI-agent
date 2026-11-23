---
source: ai_new/modules/agent/cloud/private/_seal.py
hash: a661658059af4abe16a3c8b03f14988d80deb4f373c176055194fea1f438b8a3
symbols:
- __init__
- _b64encode
- _b64decode
- _nonce_bytes
- _random_key_material
- _key_path
- _decode_key
- _read_key_file
- _generate_key_file
- _load_key
- _aad
- is_sealed
- seal
- open_sealed
- seal_map
- open_map
- mask
- mask_map
generated: gen_docs.py v1
updated_at: '2026-11-23T04:10:19'
---

# _seal.py

> 由 `scripts/gen_docs.py` 生成；手改会被下次生成覆盖。
> 职责/入参出参/副作用/依赖/不变量/关联需求由人工在下方补充；生成器只提取 docstring 与符号。

## 概览

凭证封装层：AES-256-GCM 信封加密。

## 符号

### `__init__`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_b64encode`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_b64decode`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_nonce_bytes`（function）
- 职责: 12 字节随机数：两个 nonce 令牌喂摘要，取前 12 字节；随机数能力归 codec。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_random_key_material`（function）
- 职责: 32 字节密钥材料：nonce 令牌经摘要派生；熵来自 codec 安全随机令牌。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_key_path`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_decode_key`（function）
- 职责: base64 文本 → 32 字节密钥；长度/编码非法抛 SealError。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_read_key_file`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_generate_key_file`（function）
- 职责: 密钥文件缺失：0600 安全生成 32 字节随机密钥并原子落盘。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_load_key`（function）
- 职责: 按优先级取 32 字节主密钥；任何来源失败都显式报错，不回退明文。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_aad`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `is_sealed`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `seal`（function）
- 职责: 明文 → v1 信封串。secret 必须是非空字符串；明文不回写、不落日志。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `open_sealed`（function）
- 职责: v1 信封串 → 明文；格式不符、tag/AAD 校验失败抛 SealError。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `seal_map`（function）
- 职责: 整包凭证逐个密封；返回新字典，不改动入参。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `open_map`（function）
- 职责: 整包密封凭证逐个解封；返回明文字典（仅内存使用，勿回写、勿进视图）。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `mask`（function）
- 职责: 统一脱敏：任何凭证值进日志/消息/视图前替换为占位符。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `mask_map`（function）
- 职责: 整包凭证脱敏：键保留，值一律占位；不回显密封串或明文。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充
