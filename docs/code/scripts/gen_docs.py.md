---
source: scripts/gen_docs.py
hash: a02c38de815c02727a78f1563345db35f260ca9e97c7c7f99ab774922dbe602f
symbols:
- _sha256
- _py_symbols
- _js_symbols
- _yaml_keys
- _safe_yaml
- _collect_sources
- _summary
- render_doc
- _now_iso
- _doc_path
- parse_doc
- generate
- main
generated: gen_docs.py v1
updated_at: '2026-11-23T04:10:23'
---

# gen_docs.py

> 由 `scripts/gen_docs.py` 生成；手改会被下次生成覆盖。
> 职责/入参出参/副作用/依赖/不变量/关联需求由人工在下方补充；生成器只提取 docstring 与符号。

## 概览

源码文档幂等生成器：每个源码文件一份 `docs/code/<镜像路径>.md`，拆到函数/类级别。

## 符号

### `_sha256`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_py_symbols`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_js_symbols`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_yaml_keys`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_safe_yaml`（function）
- 职责: 解析 yaml；失败返回 ({}, 错误信息)，不让门禁崩溃在并发改动的文件上。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_collect_sources`（function）
- 职责: 返回 [(rel, kind, src)]。kind: py / js / yaml。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_summary`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `render_doc`（function）
- 职责: 生成单篇文档。prev 为已有文档头（用于保留更新时间）。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_now_iso`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_doc_path`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `parse_doc`（function）
- 职责: 解析文档机读头；无头或坏头返回 None。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `generate`（function）
- 职责: 全量生成/比对。返回 {drift, missing, stale_hash, stale_symbols, orphans, stats}。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `main`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充
