---
source: ai_new/modules/agent_common/demand_engine/private/_engine.py
hash: 545bef810606e8c8e81b779f6e6fe1e807bf3942d37f86f6684d9a6b79fc57ba
symbols:
- _store_base
- _slug
- _canon
- __init__
- _load
- _signature
- _read_all
- reload
- _views_using
- notify_write
- _publish_badges
- items
- manifest
- console
- screens
- inventory
- chrome
- set_enabled
- _span
- _span_close
- run_callable
- arun_callable
- dispatch
- adispatch
- _run_callable
- _event_digest
- _claim
- _settle
- _dispatch
- _arun_callable
- _adispatch
- _as_hooks
- _md
generated: gen_docs.py v1
updated_at: '2026-11-23T04:10:22'
---

# _engine.py

> 由 `scripts/gen_docs.py` 生成；手改会被下次生成覆盖。
> 职责/入参出参/副作用/依赖/不变量/关联需求由人工在下方补充；生成器只提取 docstring 与符号。

## 概览

需求引擎实现：把 data/demands/*.json 读成"可执行的需求"，在 hook 触发时跑它们。

## 符号

### `_store_base`（function）
- 职责: 数据根的可比较标识：真实模块用 root，测试桩用 _real('demands')。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_slug`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_canon`（function）
- 职责: 稳定文本：键按字典序、值递归，保证同一事实两次算出的摘要相同。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `__init__`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_load`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_signature`（method）
- 职责: 需求目录的指纹（文件名+大小+修改时刻）；无存储上下文时回 None，退化成不比对。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_read_all`（method）
- 职责: 按文件名+大小+修改时刻做单文件解析缓存：只重解被改过的那一条。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `reload`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_views_using`（method）
- 职责: 反查：哪些视图把某条数据源当 as 用；返回 [{view, as}]。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `notify_write`（method）
- 职责: 写需求跑完：声明了 touch 就按数据源推失效，没声明就不发（不噪）。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_publish_badges`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `items`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `manifest`（method）
- 职责: 全量需求的可视化形状：每条需求的执行链 + 树节点（成形归模块，渲染只认节点）。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `console`（method）
- 职责: 控制台外壳：品牌、词表、配色 + 导航菜单一次下发。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `screens`（method）
- 职责: 界面状态图：节点=界面状态（页面/浮层），边=具体控件点下去到哪个状态。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `inventory`（method）
- 职责: 可点实例清单（由 scripts/ui_inventory.py 生成）：每条都带控件 id、状态机与点后去向。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `chrome`（method）
- 职责: 登录页要的那点字：品牌 + 登录文案。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `set_enabled`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_span`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_span_close`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `run_callable`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `arun_callable`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `dispatch`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `adispatch`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_run_callable`（method）
- 职责: 按名跑一段"编排需求"（不挂在点上），返回最后一次调用的结果。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_event_digest`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_claim`（method）
- 职责: 拿执行权。台账不可用时宁可执行一次，也不丢活（fail-open 但留证据）。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_settle`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_dispatch`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_arun_callable`（method）
- 职责: 异步轨：按名跑一段编排需求（不挂在点上），返回最后一次调用的结果。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_adispatch`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_as_hooks`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_md`（function）
- 职责: 本模块自己的数据目录：数据跟着模块走，不是全系统一个筐。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充
