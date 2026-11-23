---
source: ai_new/modules/agent_common/api/private/_registry.py
hash: e067bef252c07ece5bdfd259ed134428f6dd62aac1644b2202488c7e5cea8756
symbols:
- __init__
- _cfg_int
- _cfg_str
- _ensure_loop
- _adapt
- register
- substitute
- routes
- route
- _load_contracts
- contract
- _check
- _group_of
- _implicit_caller
- _internal_calls
- violations
- _authorize
- _route
- _span_ctx
- _span_enter
- _span_exit
- _span_open
- _span_close
- _scoped
- _ascoped
- call
- acall
- notify
generated: gen_docs.py v1
updated_at: '2026-11-23T04:10:21'
---

# _registry.py

> 由 `scripts/gen_docs.py` 生成；手改会被下次生成覆盖。
> 职责/入参出参/副作用/依赖/不变量/关联需求由人工在下方补充；生成器只提取 docstring 与符号。

## 概览

API 注册表实现。

## 符号

### `__init__`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_cfg_int`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_cfg_str`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_ensure_loop`（method）
- 职责: 进程级事件循环：惰性建在专属守护线程上，供同步壳桥接异步路由。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_adapt`（method）
- 职责: 传输层统一以 handler(ctx, payload) 调用；单参新签名在这里包成两参。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `register`（method）
- 职责: 注册路由。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `substitute`（method）
- 职责: 替换同一条路由的实现（契约不变）：通信方式可换，调用方无感。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `routes`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `route`（method）
- 职责: 按名取一条路由（不存在返回 None）。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_load_contracts`（method）
- 职责: 逐模块读 `data/api.yaml`：谁提供能力，谁声明它收发什么。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `contract`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_check`（method）
- 职责: 按契约校验入参。warn 模式只留证据，enforce 模式缺必填直接拒。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_group_of`（method）
- 职责: 模块属于哪个组：agent_common 是平台件，其余组是业务件。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_implicit_caller`（method）
- 职责: 没显式传 caller 时：按当前 handler 的所属模块判定。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_internal_calls`（method）
- 职责: 跨模块直调台账：caller 模块 -> 允许的目标模块集合（intenal-calls.yaml）。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `violations`（method）
- 职责: warn 模式下收集到的未登记直调证据（caller 模块 + 目标路由）。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_authorize`（method）
- 职责: 身份规则：需求引擎与平台件放行；模块只能调自己或在台账里登记的目标。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_route`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_span_ctx`（method）
- 职责: 当前线程正在执行的 span（嵌套调用据此接父）。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_span_enter`（method）
- 职责: 把新 span 设为当前，返回进入前的那个，供退出时恢复。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_span_exit`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_span_open`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_span_close`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_scoped`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_ascoped`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `call`（method）
- 职责: 同步入口：先服从通道绑定，再按"同步/异步"决定怎么执行。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `acall`（method）
- 职责: 异步入口：与 call 同一套通道判定，异步路由直接 await。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `notify`（method）
- 职责: 单向投递：不取返回值。本机直连时立刻执行，跨机时只承诺"已发出"。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充
