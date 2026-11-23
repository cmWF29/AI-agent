---
source: ai_new/modules/agent/sessions/private/_pure.py
hash: a6c168b03cce1cf670d28f780afaaed064f3e46276bb4cfbe11de80e886a08bb
symbols:
- _seed
- refresh_constraint_message
- refresh_stage_message
- inject_assigned_message
- build
- _machine_brief
- view
- present
- screen
- gone
- compactp
- machine_applyp
- missing
- record_path
- wire_at
- role_name
generated: gen_docs.py v1
updated_at: '2026-11-23T04:10:20'
---

# _pure.py

> 由 `scripts/gen_docs.py` 生成；手改会被下次生成覆盖。
> 职责/入参出参/副作用/依赖/不变量/关联需求由人工在下方补充；生成器只提取 docstring 与符号。

## 概览

会话纯函数：造记录、拼系统消息、露出字段、裁剪上下文。不读盘、不取时间。

## 符号

### `_seed`（function）
- 职责: 会话开局消息：system 人设在前；流程约束独立成结构化消息；原始需求作为首条 user 在后。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `refresh_constraint_message`（function）
- 职责: 用最新流程约束块替换独立的 flow-context 消息；人设 system 与其余消息保留不动。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `refresh_stage_message`（function）
- 职责: 用最新阶段段替换首条 system 里的旧阶段段；其余人设/红线原文保留。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `inject_assigned_message`（function）
- 职责: 把工单已分派角色清单并入首条 system；已有同标题段先剥离再重写，避免重复注入。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `build`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_machine_brief`（function）
- 职责: 流程状态机快照：阶段链与活跃集合，形状与 tickets 的 machine 一致，不带重字段。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `view`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `present`（function）
- 职责: 读档后定型：缺记录返 not_found，否则返视图。分支在模块内部。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `screen`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `gone`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `compactp`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `machine_applyp`（function）
- 职责: 把并入后的状态机契约写回会话快照；活跃态不在新契约内则回收，空则回退初始。纯数据成形。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `missing`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `record_path`（function）
- 职责: 会话记录落盘相对路径：模板由需求层配置表给出，纯函数只填参。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `wire_at`（function）
- 职责: 按会话与消息序位取那一条的真实网络报文原文（请求体/响应原文）。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `role_name`（function）
- 职责: 角色会话名：岗位标识 - 工单 id，纯拼装。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充
