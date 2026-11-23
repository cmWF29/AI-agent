---
source: ai_new/modules/agent_common/api/__init__.py
hash: f9780db71a9fc84d0bc239d5b26d8278d06669e7ab280dc967cd85db32530e29
symbols:
- setup
- _open_listen
- _restart_listen
- start
- _route_snapshot
- _route_compile
- compile_transport
- register
- call
- notify
- routes
- contract
- transport
generated: gen_docs.py v1
updated_at: '2026-11-23T04:10:21'
---

# __init__.py

> 由 `scripts/gen_docs.py` 生成；手改会被下次生成覆盖。
> 职责/入参出参/副作用/依赖/不变量/关联需求由人工在下方补充；生成器只提取 docstring 与符号。

## 概览

API 模块：路由注册 + 跨模块消息 + 消息契约 + 通信通道编译。无任何业务。

## 符号

### `setup`（function）
- 职责: 装配入口：装填 ctx.ApiError 与 ctx.api（这两个面由赋值动作本身声明）。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_open_listen`（function）
- 职责: 按当前绑定起本机 IPC 监听；全直连时什么都不开（不占端口和 socket 文件）。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_restart_listen`（function）
- 职责: 运行中重编后换拓扑：先收旧监听，再按新绑定起。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `start`（function）
- 职责: 装配末尾（绑定已编好）：按绑定里实际用到的通道起本机 IPC 监听。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_route_snapshot`（function）
- 职责: 现状快照：通道分布 + 路由契约键，给需求层与巡检看，不改任何状态。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_route_compile`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `compile_transport`（function）
- 职责: 把部署意图 data/deploy.yaml 编译成 data/gen/bindings.yaml（模板代码不变，换拓扑只重编）。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `register`（function）
- 职责: 注册路由 name（约定 "module.fn"）；stream=True 表示它可以被当流读。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `call`（function）
- 职责: 调用路由。caller 是发起方模块名：只有需求（demand_engine）与被装配的系统面能调。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `notify`（function）
- 职责: 单向通知：不取返回值，只承诺"已投递"。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `routes`（function）
- 职责: 全部已注册路由（name/doc/module + 契约的 in/out 键）。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `contract`（function）
- 职责: 消息契约：给名字返回单条，不给就返回全表（来自各模块 data/api.yaml）。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `transport`（function）
- 职责: 当前通信通道绑定（direct / memory / http 的分布与来源）。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充
