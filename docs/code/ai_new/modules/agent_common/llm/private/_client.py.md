---
source: ai_new/modules/agent_common/llm/private/_client.py
hash: abcfbb46676309936c23ba91b28578e47fc7ea51dfb1fed397f453612b25b92b
symbols:
- _sanitize
- encode
- _choice
- decode
- decode_sse
- wire
generated: gen_docs.py v1
updated_at: '2026-11-23T04:10:22'
---

# _client.py

> 由 `scripts/gen_docs.py` 生成；手改会被下次生成覆盖。
> 职责/入参出参/副作用/依赖/不变量/关联需求由人工在下方补充；生成器只提取 docstring 与符号。

## 概览

LLM 语义实现（纯计算）：标准输入 → 载荷，响应对象 → 对话结果。

## 符号

### `_sanitize`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `encode`（function）
- 职责: 标准输入 → {url, headers, payload}。payload 是对象，序列化交给 codec。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_choice`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `decode`（function）
- 职责: 响应对象 → {content, tool_calls, finish, usage}；形状不对返回 ok=False。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `decode_sse`（function）
- 职责: SSE 事件列表（已由 codec 解析）→ 同样的对话结果。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `wire`（function）
- 职责: 网络报文成形：请求体、响应原文与连接事实，密钥类头一律打码，只留可回查的东西。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充
