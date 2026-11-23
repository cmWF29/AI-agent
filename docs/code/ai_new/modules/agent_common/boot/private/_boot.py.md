---
source: ai_new/modules/agent_common/boot/private/_boot.py
hash: a52f53fb36b5dcdd07d47b8ea3a00e0dd7617a25130fd83d9e566a6da9d096b1
symbols:
- _profile
- _demands_dir
- _plan
- _build
- main
- _await_serve
generated: gen_docs.py v1
updated_at: '2026-11-23T04:10:21'
---

# _boot.py

> 由 `scripts/gen_docs.py` 生成；手改会被下次生成覆盖。
> 职责/入参出参/副作用/依赖/不变量/关联需求由人工在下方补充；生成器只提取 docstring 与符号。

## 概览

组合根：扫描装配依赖图，动态加载并按 DAG 装配所有模块。

## 符号

### `_profile`（function）
- 职责: 装配用哪些模块组：读 data/profiles.yaml，不写在代码里。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_demands_dir`（function）
- 职责: 需求数据在 demand_engine 模块自己的 data 下；扫描器用它算需求接线图。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_plan`（function）
- 职责: 扫描装配 DAG，返回计划（roots / order / edges / reasons / warnings / hooks / packages）。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_build`（function）
- 职责: 按扫描出来的顺序装配所有模块，返回已装配模块名列表。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `main`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_await_serve`（function）
- 职责: 常驻模式：装配完成后主线程驻留，直到收到终止信号。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充
