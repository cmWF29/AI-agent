---
source: ai_new/modules/agent_common/codec/private/_codec.py
hash: 67ccc1461e3517c9a677ab31f130e262cdf993a3b343b511fb182caf3fa834de
symbols:
- json_encode
- json_decode
- _jsonish
- _json_field
- _json_array
- json_salvage
- yaml_encode
- yaml_encode_flow
- yaml_decode
- sse_decode
- base64_decode_bytes
- base64_encode
- digest
- nonce
- decode_hex
- hex_from_base64
- wave_decode
generated: gen_docs.py v1
updated_at: '2026-11-23T04:10:21'
---

# _codec.py

> 由 `scripts/gen_docs.py` 生成；手改会被下次生成覆盖。
> 职责/入参出参/副作用/依赖/不变量/关联需求由人工在下方补充；生成器只提取 docstring 与符号。

## 概览

JSON / SSE 编解码实现。失败是结果：{ok: False, error}。

## 符号

### `json_encode`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `json_decode`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_jsonish`（function）
- 职责: 尽量解一段 JSON 字面量：先严格，再把模型写坏的反斜杠去掉重试。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_json_field`（function）
- 职责: 从坏 JSON 里抽一个字符串字段：只认开引号后的原文，按 JSON 字符串规则收口。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_json_array`（function）
- 职责: 从坏 JSON 里抽数组字段：按括号深度和字符串状态截取，再走同一套容错解码。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `json_salvage`（function）
- 职责: 坏收口报文的最小抢救：逐字段抽字符串/数组，抽到任何一项就算结构化。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `yaml_encode`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `yaml_encode_flow`（function）
- 职责: 报文/SSE 用：YAML flow 单行，保持现有分帧与 Content-Length。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `yaml_decode`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `sse_decode`（function）
- 职责: 把 `data: {...}` 行解析成对象列表；非 data 行（注释/空行）忽略。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `base64_decode_bytes`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `base64_encode`（function）
- 职责: 文本/字节 → base64 文本；与 base64_decode_bytes 成对，供契约里成对声明的调用方使用。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `digest`（function）
- 职责: 摘要：内容指纹，不是业务语义。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `nonce`（function）
- 职责: 安全随机令牌：URL 安全，给会话/一次性凭证用。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `decode_hex`（function）
- 职责: hex 字节 → utf8 文本；非 utf8 退 base64 承载。截断阈值与截断标记在此成形。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `hex_from_base64`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `wave_decode`（function）
- 职责: WAV(PCM) 字节 → {pcm 字节, rate, channels}；压缩/解析失败结构化报错。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充
