---
source: ai_new/modules/agent/sandbox/private/_winpath.py
hash: 8cd4598e1cfc61bdb044a2b3c2950c83e8c439fb42b1a6c242de6151bb957d96
symbols:
- strip_long_prefix
- is_reserved_name
- normalize_segment
- split_root
- canonical
- _segment_codes
- guard_rel
- guard_path
generated: gen_docs.py v1
updated_at: '2026-11-23T09:13:12'
---

# _winpath.py

> 由 `scripts/gen_docs.py` 生成；手改会被下次生成覆盖。
> 职责/入参出参/副作用/依赖/不变量/关联需求由人工在下方补充；生成器只提取 docstring 与符号。

## 概览

Windows 路径语义纯判定（不碰 OS、不读盘，可在 Linux/macOS 上跑同一批单测）。

## 符号

### `strip_long_prefix`（function）
- 职责: 剥离长路径前缀。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `is_reserved_name`（function）
- 职责: 段名是否为 Win32 保留设备名（大小写不敏感，忽略扩展名）。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `normalize_segment`（function）
- 职责: 段归一：剥段尾点号 / 空格，转小写（Win32 大小写不敏感比较）。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `split_root`（function）
- 职责: 把路径拆成根类型 + 根标识 + 分段。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `canonical`（function）
- 职责: 生成用于包含比较的规范形式（小写、段尾点空格剥离、``/`` 分隔）。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_segment_codes`（function）
- 职责: 分段级违规判定：穿越 / 保留名。返回错误码或 None。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `guard_rel`（function）
- 职责: 相对路径守卫：拒绝绝对路径、盘符、UNC、穿越段、保留设备名。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `guard_path`（function）
- 职责: 根目录包含守卫（Windows 语义）。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充
