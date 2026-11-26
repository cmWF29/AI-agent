---
source: ai_new/modules/agent_common/store/private/_files.py
hash: e3aa76de4e08987e796a31c6486aefbf4f614cb5513479f986a12fcc82e447cd
symbols:
- replace_file
- ensure_dir
- write_text_atomic
- write_bytes_atomic
- _read_text_once
- read_text
- write_text
- safe_id
- write_bytes
- append_text_atomic
- remove_tree
- pack
- modules_root
generated: gen_docs.py v1
updated_at: '2026-11-23T04:10:22'
---

# _files.py

> 由 `scripts/gen_docs.py` 生成；手改会被下次生成覆盖。
> 职责/入参出参/副作用/依赖/不变量/关联需求由人工在下方补充；生成器只提取 docstring 与符号。

## 概览

纯函数文件工具。

## 符号

### `replace_file`（function）
- 职责: 原子改名；Windows 上杀软/读句柄短暂占用目标时退避重试，不把并发放大成写失败。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `ensure_dir`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `write_text_atomic`（function）
- 职责: 先写临时文件再改名：断电/并发都不会留下半个文件。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `write_bytes_atomic`（function）
- 职责: 二进制原子写：临时文件 + 原子改名，掉电不留半个文件。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_read_text_once`（function）
- 职责: 单次读文本；单独成函数，平台分支用例可替换 IO 而不改真实 os.name。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `read_text`（function）
- 职责: 读文本；Windows 上目标正被原子改名/杀软扫描时短暂占用，退避重读。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `write_text`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `safe_id`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `write_bytes`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `append_text_atomic`（function）
- 职责: 追加写走「读全量 → 临时文件 → 原子改名」：不留半截文件。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `remove_tree`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `pack`（function）
- 职责: entries: [(目录, 归档前缀)]；把目录内容压进 dest（zip）。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `modules_root`（function）
- 职责: 仓库里的 modules 根（从本文件往上找）。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充
