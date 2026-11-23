---
source: ai_new/modules/agent/todos/__init__.py
hash: 673e92dd252277a704c303cd6b96c6a194f15d84968a3b3e1b5b08a5ba7f71a9
symbols:
- _limit
- _msg_tpl
- setup
- _route_apply
- _route_context
generated: gen_docs.py v1
updated_at: '2026-11-23T04:10:21'
---

# __init__.py

> 由 `scripts/gen_docs.py` 生成；手改会被下次生成覆盖。
> 职责/入参出参/副作用/依赖/不变量/关联需求由人工在下方补充；生成器只提取 docstring 与符号。

## 概览

待办模块：模型自生成的 todolist，增删查改只走 todo 工具；状态存会话快照。

## 符号

### `_limit`（function）
- 职责: 待办上限只有一处来源：配置；读不到就按 0 处理（等于不收新条目），不在这里写死。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_msg_tpl`（function）
- 职责: 消息模板表：待办模块自己的 data，读不到就退化成空。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `setup`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_route_apply`（function）
- 职责: 待办动作：当前表 + 本次参数 → 新表；有改动才回会话补丁，由会话快照一并落盘。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_route_context`（function）
- 职责: 待办上下文：拼成 system 消息；空表回 None 让编排跳过。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充
