---
source: ai_new/modules/agent/tickets/__init__.py
hash: fdaeeea0cf9fe2e9780aac163f707bfea5aa2d70c867d9c6959b6db1c8b8134f
symbols:
- setup
- _register_tools
- _msg_tpl
- _cfg_paths
- _cfg_logs
- _as_handler
- _lookup_project
- _ticket_path
- _route_record_path
- _project_state
- _err
- _route_send
- _route_note_write
- _route_create
- _reuse_created
- _create
- _session_snapshot
- _route_close
- _route_split
- _route_rebind
- _route_stall_scan
generated: gen_docs.py v1
updated_at: '2026-11-23T04:10:20'
---

# __init__.py

> 由 `scripts/gen_docs.py` 生成；手改会被下次生成覆盖。
> 职责/入参出参/副作用/依赖/不变量/关联需求由人工在下方补充；生成器只提取 docstring 与符号。

## 概览

工单模块：工单记录的纯计算。生命周期编排在 ticket-* 需求里。

## 符号

### `setup`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_register_tools`（function）
- 职责: 编排工具就是需求桥接：PM 握分单/派角色/结单，角色只读文档与记备注。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_msg_tpl`（function）
- 职责: 消息模板表：工单模块自己的 data，读不到就退化成空。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_cfg_paths`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_cfg_logs`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_as_handler`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_lookup_project`（function）
- 职责: 按目录反查工单归属：唯一命中才算，多个项目下同时存在就拒绝猜。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_ticket_path`（function）
- 职责: 工单文件路径：项目目录下的 tickets/<id>/ticket.yaml。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_route_record_path`（function）
- 职责: 需求层取路径：给了项目就用，没给就按目录反查（反查不到的路径必然读不到东西）。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_project_state`（function）
- 职责: 项目档案里的两件事实：是否归档、哪些岗位被项目禁用。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_err`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_route_send`（function）
- 职责: 发消息闭环：工单守卫（结单只读）→ 项目守卫（归档只读）→ 解析目标 → 追加 → 派发。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_route_note_write`（function）
- 职责: 追加备注：同一套守卫，追加后立即落盘并回视图。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_route_create`（function）
- 职责: 建单：幂等键 = 项目 + 标题 + 目标。重放直接回原单，不建第二张。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_reuse_created`（function）
- 职责: 重放：按票据 id 读回原单并出视图，不再落盘、不再派发。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_create`（function）
- 职责: 建单闭环：项目守卫、查档、造记录、拉 PM、落盘。分岔与派发都在能力内部。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_session_snapshot`（function）
- 职责: 读会话留档快照；会话已不在则返 None。消息原文交纯函数裁剪。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_route_close`（function）
- 职责: 结单闭环：守子单 → 关闭落盘 → 对话固化进工单 → 回收 PM/角色会话 → 通知父单。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_route_split`（function）
- 职责: 拆单闭环：上限守卫 + 逐个建子单（每次建单都是一条独立编排）。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_route_rebind`（function）
- 职责: 引用改挂：遍历工单，把指向旧项目 id 的记录改写为新 id。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_route_stall_scan`（function）
- 职责: 停滞扫描闭环：开关/阈值/上限/是否开单由需求层从配置传入；遍历判定归本能力。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充
