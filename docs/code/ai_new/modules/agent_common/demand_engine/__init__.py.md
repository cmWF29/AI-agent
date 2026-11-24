---
source: ai_new/modules/agent_common/demand_engine/__init__.py
hash: f13c08f5adb1ffa23e88514bfe48d52450b1a9e93d8c751b771f8c4dc1716ced
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
- _all_docs
- _path_nodes
- _find_doc
- _route_code_docs
- _route_code_docs_read
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

### `_all_docs`（function）
- 职责: 把生成器按模块分组的索引摊平成文件行；路径树自己再按目录重组。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_path_nodes`（function）
- 职责: 按源文件真实路径切目录树：目录节点带 group=路径前缀，文件节点带源码+镜像文档。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_find_doc`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_route_code_docs`（function）
- 职责: 源码 ↔ docs/code 映射：首屏给第一层目录，展开时按路径前缀取下一层。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_route_code_docs_read`（function）
- 职责: 按索引里的精确路径读源码与镜像文档；只认索引登记过的路径，不接受任意文件。
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
