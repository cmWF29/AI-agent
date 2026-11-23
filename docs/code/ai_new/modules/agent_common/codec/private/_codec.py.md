---
source: ai_new/modules/agent_common/codec/private/_codec.py
hash: 268ade8066265bcc3516ed4ec799b6c8688b43cbedc57de37580406482b810e5
symbols:
- json_encode
- json_decode
- yaml_encode
- yaml_encode_flow
- yaml_decode
- sse_decode
- base64_decode_bytes
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

### `digest`（function）
- 职责: 摘要：内容指纹，不是业务语义。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `nonce`（function）
- 职责: 安全随机令牌：URL 安全，给会话/一次性凭证用。随机数是能力，业务模块不自带。
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
