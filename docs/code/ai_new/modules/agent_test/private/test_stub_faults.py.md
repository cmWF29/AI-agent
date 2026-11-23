---
source: ai_new/modules/agent_test/private/test_stub_faults.py
hash: 2ff55fbdd20ada6f1c691117e92229b9ff1cefceee314fab51b56b2d21a246e1
symbols:
- _assemble
- _run
- setUp
- tearDown
- _start
- test_scripted_tool_call_then_close
- test_http_5xx_fault_returns_failed
- test_connection_close_returns_failed
- test_token_limit_returns_failed
- test_delay_jitter_still_closes
generated: gen_docs.py v1
updated_at: '2026-11-23T04:10:23'
---

# test_stub_faults.py

> 由 `scripts/gen_docs.py` 生成；手改会被下次生成覆盖。
> 职责/入参出参/副作用/依赖/不变量/关联需求由人工在下方补充；生成器只提取 docstring 与符号。

## 概览

本地打桩 LLM 服务的故障与链路场景测试。

## 符号

### `_assemble`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_run`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `setUp`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `tearDown`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_start`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_scripted_tool_call_then_close`（method）
- 职责: 脚本化：第一轮回 tool_call，第二轮收口；工具结果回填进消息。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_http_5xx_fault_returns_failed`（method）
- 职责: 服务端 5xx：重试耗尽后链路透出 failed，不抛异常。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_connection_close_returns_failed`（method）
- 职责: 断连：连接被关，链路透出 unreachable/net_error，不掀翻。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_token_limit_returns_failed`（method）
- 职责: 上下文/token 超限：桩返 context_length_exceeded，链路透出 failed。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `test_delay_jitter_still_closes`（method）
- 职责: 延迟抖动下链路仍能正常收口。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充
