---
source: ai_new/modules/agent_common/demand_engine/__init__.py
hash: bd86f7a7c58b032689d9a0c1f3f0f8e040f45cef04e1c41cba6501dd1bbeca75
symbols:
- _route_run
- _route_batch
- _dig
- _value
- _fill
- _refs
- _unwrap
- _route_views_index
- _route_view_spec
- _route_resolve
- _doc_children
- _route_code_docs
- _route_click_machine
- _noop
- setup
- dispatch
generated: gen_docs.py v1
updated_at: '2026-11-23T04:10:21'
---

# __init__.py

> 由 `scripts/gen_docs.py` 生成；手改会被下次生成覆盖。
> 职责/入参出参/副作用/依赖/不变量/关联需求由人工在下方补充；生成器只提取 docstring 与符号。

## 概览

需求引擎：业务是结构化的语言，引擎负责让它跑起来。

## 符号

### `_route_run`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_route_batch`（function）
- 职责: 一次往返跑多条需求：控制台每翻一页要好几份数据，跨公网每条一个 RTT 就是几秒。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_dig`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_value`（function）
- 职责: 一条取值表达式的实际值：只认 route / data / cache 三种来源。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_fill`（function）
- 职责: 把规格里的参数模板填成实际值（与前端 spec.fill 同一套语义）。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_refs`（function）
- 职责: 规格里引用到的数据源名：只有 data./cache. 才是"要等别的数据源"，route/row 上手就有。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_unwrap`（function）
- 职责: 需求返回外面套了一层 {ok, demand, result, calls}，页面只认里面的 result。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_route_views_index`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_route_view_spec`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_route_resolve`（function）
- 职责: 整页取数：前端只报"看哪一页、什么参数"，依赖与并发都由视图规格自己决定。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_doc_children`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_route_code_docs`（function）
- 职责: 源码 ↔ docs/code 映射：首屏只给分组与计数，点开某组再取该组条目。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_route_click_machine`（function）
- 职责: 点击状态机规格：前端按它做门禁，架构页按它显示，测试按它做全覆盖。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_noop`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `setup`（function）
- 职责: 装配入口：装填 ctx.demand_engine（需求装载 + 解释执行）。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `dispatch`（function）
- 职责: 把一次 hook 触发交给需求引擎。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充
