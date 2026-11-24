---
source: scripts/gate_diff_coverage.py
hash: 9666e2b2c01784915e84ce7ef2d27b6348b0b7be16a386e6bc6fb17a7a306006
symbols:
- _load_min
- _resolve_base
- _diff
- _added_lines
- _coverage_lines
- evaluate
- main
generated: gen_docs.py v1
updated_at: '2026-11-25T03:45:03'
---

# gate_diff_coverage.py

> 由 `scripts/gen_docs.py` 生成；手改会被下次生成覆盖。
> 职责/入参出参/副作用/依赖/不变量/关联需求由人工在下方补充；生成器只提取 docstring 与符号。

## 概览

改动行覆盖率门禁：本轮新增/修改过的产品代码行，必须有 90% 被用例执行。

## 符号

### `_load_min`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_resolve_base`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_diff`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_added_lines`（function）
- 职责: 从 unified=0 diff 里取新增行号；跳过空行与注释，可执行性交给 coverage 判定。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_coverage_lines`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `evaluate`（function）
- 职责: 按改动行与实际执行行算覆盖率；0 行可执行视为通过，阈值判定独立可测。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `main`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充
