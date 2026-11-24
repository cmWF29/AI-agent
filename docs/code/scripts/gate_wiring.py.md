---
source: scripts/gate_wiring.py
hash: d2fdc1a857c921a4f976f68bd389fb198deb4e54b9b4d87fd9ee5bd0d896834c
symbols:
- _load
- route_inputs
- demand_calls
- form_submits
- waivers
- scan
- main
generated: gen_docs.py v1
updated_at: '2026-11-24T20:07:37'
---

# gate_wiring.py

> 由 `scripts/gen_docs.py` 生成；手改会被下次生成覆盖。
> 职责/入参出参/副作用/依赖/不变量/关联需求由人工在下方补充；生成器只提取 docstring 与符号。

## 概览

接线门禁：表单提交 → 需求 with → API 路由 in，参数必须逐项贯通。

## 符号

### `_load`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `route_inputs`（function）
- 职责: route -> declared input names。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `demand_calls`（function）
- 职责: demand id -> {route: set(with keys)}。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `form_submits`（function）
- 职责: (form id, demand id, form param keys)。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `waivers`（function）
- 职责: (route, param) -> reason。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `scan`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `main`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充
