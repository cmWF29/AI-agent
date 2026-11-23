---
source: ai_new/modules/agent/cloud/private/_seal.py
hash: 7ebd09f7d26a70c314fbf9ffca045bbdcf1db547e3cab65e29fabacf63eeaa35
symbols:
- __init__
- _master
- _keystream
- is_sealed
- seal
- open_sealed
- seal_map
- open_map
generated: gen_docs.py v1
updated_at: '2026-11-23T04:10:19'
---

# _seal.py

> 由 `scripts/gen_docs.py` 生成；手改会被下次生成覆盖。
> 职责/入参出参/副作用/依赖/不变量/关联需求由人工在下方补充；生成器只提取 docstring 与符号。

## 概览

凭证封装层（seal/open）。

## 符号

### `__init__`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_master`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_keystream`（function）
- 职责: 由主密钥 + nonce 派生重复密钥流（混淆用，不具密码学强度）。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `is_sealed`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `seal`（function）
- 职责: 明文 → 密封串。secret 必须是非空字符串。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `open_sealed`（function）
- 职责: 密封串 → 明文；格式不符或解封失败抛 SealError。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `seal_map`（function）
- 职责: 整包凭证逐个密封；返回新字典。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `open_map`（function）
- 职责: 整包密封凭证逐个解封；返回明文字典（仅内存使用，勿回写）。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充
