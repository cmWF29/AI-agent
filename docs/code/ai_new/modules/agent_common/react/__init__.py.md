---
source: ai_new/modules/agent_common/react/__init__.py
hash: 5a8acf2a0dc480684e20f8af68b523a6b7acae88b89cb731d972ad3f94f47232
symbols:
- _msg_tpl
- setup
- _tool_threshold
- _logs_paths
- _exec_tool
- _rel_path
- _stash_tool_output
- _checkpoint
- _route_run
generated: gen_docs.py v1
updated_at: '2026-11-23T04:10:22'
---

# __init__.py

> 由 `scripts/gen_docs.py` 生成；手改会被下次生成覆盖。
> 职责/入参出参/副作用/依赖/不变量/关联需求由人工在下方补充；生成器只提取 docstring 与符号。

## 概览

ReAct 模块：只提供消息/工具形状的纯计算。循环在 react-run 需求里。

## 符号

### `_msg_tpl`（function）
- 职责: 消息模板表：react 模块自己的 data，读不到就退化成空。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `setup`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_tool_threshold`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_logs_paths`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_exec_tool`（function）
- 职责: 单条工具执行：注册表命中直跑；占位需求回退；工具报错归一成观察结果，不掀翻整轮。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_rel_path`（function）
- 职责: 路径模板填参：值为空的段整段去掉（未归属项目时不会拼出 projects//tickets/…）。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_stash_tool_output`（function）
- 职责: 工具输出分级：超限先落 ticket 层日志，回路径与读取提示；落盘失败兜底全文回填。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_checkpoint`（function）
- 职责: 轮内中间落盘：把当前累积消息/摘要/步数写回会话记录。失败不掀翻 ReAct 循环。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_route_run`（function）
- 职责: ReAct 闭环：轮次循环、终止判断、工具回填都在能力内部，需求树只留一次调用。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充
