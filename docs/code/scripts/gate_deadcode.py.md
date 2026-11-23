---
source: scripts/gate_deadcode.py
hash: c4970e3e1aa02e10183eb6eb818a578f8b54273297d09dfe85fe016e088799d1
symbols:
- _load_yaml
- _session_tool_names
- scan
- problems
- format_problem
- probe_frontend
- _free_port
- _wait_live
- main
generated: gen_docs.py v1
updated_at: '2026-11-23T04:10:23'
---

# gate_deadcode.py

> 由 `scripts/gen_docs.py` 生成；手改会被下次生成覆盖。
> 职责/入参出参/副作用/依赖/不变量/关联需求由人工在下方补充；生成器只提取 docstring 与符号。

## 概览

死代码静态扫描门禁：定义后从未被引用/调用的函数、方法、未使用 import、孤儿注册路由/工具。

## 符号

### `_load_yaml`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_session_tool_names`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `scan`（function）
- 职责: 跑全仓扫描，返回 {problems, stats, tiers}。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `problems`（function）
- 职责: 兼容既有门禁约定：返回格式化后的命中条目字符串列表。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `format_problem`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `probe_frontend`（function）
- 职责: 起桩 + 浏览器真实渲染取页面控件绑定；失败返回降级说明。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_free_port`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_wait_live`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `main`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充
